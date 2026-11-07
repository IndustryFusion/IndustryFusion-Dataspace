#
# Copyright (c) 2026 IndustryFusion Foundation
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#   http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.
#

"""Checking incoming tokens, and getting this adapter's own token."""

import hashlib
import hmac
import time

import httpx
import jwt
from fastapi import HTTPException, Request

from app.config import Settings, role_for

TRANSFER_TOKEN_HEADER = "X-Transfer-Token"


READ_PAYLOAD, DELIVER_CONTENT = "payload", "inbox-receive"


def transfer_token(settings: Settings, route: str, message_id: str) -> str:
    """Lets its holder call one of the connector's routes here, for one message. See protocol.md."""
    material = f"{route}:{message_id}".encode()
    return hmac.new(settings.keycloak_client_secret.encode(), material, hashlib.sha256).hexdigest()


def require_transfer_token(request: Request, route: str, message_id: str) -> None:
    settings = request.app.state.services.settings
    given = request.headers.get(TRANSFER_TOKEN_HEADER)
    if given is None:
        raise HTTPException(status_code=401, detail="Missing transfer token")
    if not hmac.compare_digest(transfer_token(settings, route, message_id).encode(), given.encode()):
        raise HTTPException(status_code=401, detail="Wrong transfer token")


class TokenVerifier:
    """Checks RS256 signature and exact issuer. As keycloak.md says, the audience is not checked."""

    def __init__(self, settings: Settings, http: httpx.AsyncClient) -> None:
        self.issuer = settings.issuer
        self.http = http
        self.keys: dict[str, object] = {}

    async def _refresh(self) -> None:
        try:
            response = await self.http.get(f"{self.issuer}/protocol/openid-connect/certs")
            response.raise_for_status()
        except httpx.HTTPError as error:
            raise HTTPException(status_code=502, detail="Signing keys are unreachable") from error
        try:
            self.keys = {
                key["kid"]: jwt.PyJWK(key).key
                for key in response.json()["keys"]
                if key.get("use", "sig") == "sig" and key.get("kty") == "RSA"
            }
        except (ValueError, KeyError, TypeError, jwt.PyJWTError) as error:
            raise HTTPException(status_code=502, detail="Signing keys are unreadable") from error

    async def claims(self, token: str) -> dict:
        try:
            kid = jwt.get_unverified_header(token).get("kid")
        except jwt.PyJWTError as error:
            raise HTTPException(status_code=401, detail="Invalid token") from error
        if kid not in self.keys:
            await self._refresh()
        key = self.keys.get(kid)
        if key is None:
            raise HTTPException(status_code=401, detail="Invalid token")
        try:
            return jwt.decode(
                token,
                key,
                algorithms=["RS256"],
                issuer=self.issuer,
                options={"verify_aud": False, "require": ["exp"]},
            )
        except jwt.PyJWTError as error:
            raise HTTPException(status_code=401, detail="Invalid token") from error


def bearer_token(request: Request) -> str:
    scheme, _, token = request.headers.get("Authorization", "").partition(" ")
    if scheme.lower() != "bearer" or not token:
        raise HTTPException(status_code=401, detail="Missing token")
    return token


def holds_role(claims: dict, participant_id: str) -> bool:
    return role_for(participant_id) in claims.get("realm_access", {}).get("roles", [])


async def require_participant(request: Request) -> dict:
    """Allow only a token holding this adapter's participant role."""
    services = request.app.state.services
    claims = await services.verifier.claims(bearer_token(request))
    if not holds_role(claims, services.settings.participant_id):
        raise HTTPException(status_code=403, detail="This token is not for this participant")
    return claims


class OwnToken:
    """This adapter's client-credentials token, for notifying peers."""

    MARGIN_SECONDS = 30

    def __init__(self, settings: Settings, http: httpx.AsyncClient) -> None:
        self.settings = settings
        self.http = http
        self.token: str | None = None
        self.expires = 0.0

    async def get(self) -> str:
        if self.token is None or time.monotonic() >= self.expires:
            response = await self.http.post(
                f"{self.settings.issuer}/protocol/openid-connect/token",
                data={
                    "grant_type": "client_credentials",
                    "client_id": self.settings.participant_id,
                    "client_secret": self.settings.keycloak_client_secret,
                },
            )
            response.raise_for_status()
            answer = response.json()
            self.token = answer["access_token"]
            self.expires = time.monotonic() + answer["expires_in"] - self.MARGIN_SECONDS
        return self.token
