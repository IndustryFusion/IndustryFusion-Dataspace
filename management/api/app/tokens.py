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

"""Checks an administrator's token, and gets one from Keycloak."""

import time
from collections.abc import Callable

import httpx
import jwt
from fastapi import HTTPException

ADMIN_ROLE = "dataspace-admin"
SECONDS_BETWEEN_KEY_FETCHES = 10


class AdminTokens:
    def __init__(self, issuer: str, http: httpx.AsyncClient, clock: Callable[[], float] = time.monotonic) -> None:
        self.issuer = issuer
        self.http = http
        self.clock = clock
        self.keys: dict[str, object] = {}
        self.last_fetch: float | None = None

    async def _load_keys(self) -> None:
        """Fetch signing keys, unless that was just done: a stream of bad tokens must not cause a fetch each."""
        if self.last_fetch is not None and self.clock() - self.last_fetch < SECONDS_BETWEEN_KEY_FETCHES:
            return
        try:
            answer = await self.http.get(f"{self.issuer}/protocol/openid-connect/certs")
            answer.raise_for_status()
            published = answer.json()["keys"]
            self.keys = {
                entry["kid"]: jwt.PyJWK(entry).key
                for entry in published
                if entry.get("kty") == "RSA" and entry.get("use", "sig") == "sig"
            }
        except (httpx.HTTPError, ValueError, KeyError, TypeError, jwt.PyJWTError) as error:
            raise HTTPException(status_code=502, detail="Signing keys are unavailable") from error
        self.last_fetch = self.clock()

    def _claims(self, token: str, kid: str) -> dict:
        return jwt.decode(
            token,
            self.keys[kid],
            algorithms=["RS256"],
            issuer=self.issuer,
            options={"verify_aud": False, "require": ["exp"]},
        )

    async def claims(self, token: str) -> dict:
        refused = HTTPException(status_code=401, detail="Invalid token")
        try:
            kid = jwt.get_unverified_header(token).get("kid")
        except jwt.PyJWTError as error:
            raise refused from error
        if kid not in self.keys:
            await self._load_keys()
            if kid not in self.keys:
                raise refused
        try:
            return self._claims(token, kid)
        except jwt.InvalidSignatureError as error:
            # A rotation can keep a key's id, so look at the published keys once more.
            await self._load_keys()
            if kid not in self.keys:
                raise refused from error
            try:
                return self._claims(token, kid)
            except jwt.PyJWTError as second:
                raise refused from second
        except jwt.PyJWTError as error:
            raise refused from error

    async def require_admin(self, authorization: str | None) -> str:
        """Return the bearer token, if it belongs to an administrator."""
        scheme, _, token = (authorization or "").partition(" ")
        if scheme.lower() != "bearer" or not token:
            raise HTTPException(status_code=401, detail="Missing token")
        claims = await self.claims(token)
        access = claims.get("realm_access")
        roles = access.get("roles") if isinstance(access, dict) else None
        if not isinstance(roles, list) or ADMIN_ROLE not in roles:
            raise HTTPException(status_code=403, detail=f"This needs the role {ADMIN_ROLE}")
        return token


async def fetch_admin_token(http: httpx.AsyncClient, issuer: str, client_id: str, client_secret: str) -> dict:
    try:
        answer = await http.post(
            f"{issuer}/protocol/openid-connect/token",
            data={"grant_type": "client_credentials", "client_id": client_id, "client_secret": client_secret},
        )
    except httpx.HTTPError as error:
        raise HTTPException(status_code=503, detail="Keycloak is unavailable") from error
    if answer.status_code in (400, 401, 403):
        raise HTTPException(status_code=401, detail="Wrong client credentials")
    if answer.status_code != 200:
        raise HTTPException(status_code=502, detail="Keycloak refused to give a token")
    try:
        return answer.json()
    except ValueError as error:
        raise HTTPException(status_code=502, detail="Keycloak gave an unusable answer") from error
