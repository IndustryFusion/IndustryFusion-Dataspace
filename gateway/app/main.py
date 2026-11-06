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

"""API Gateway: the single public entry point for agents. Routing only, with no state beyond caches."""

import posixpath
import time
from collections.abc import AsyncIterator, Callable
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from os import environ
from urllib.parse import quote, unquote

import httpx
import jwt
from fastapi import FastAPI, HTTPException, Request, Response
from fastapi.responses import JSONResponse

REGISTRY_CACHE_SECONDS = 30
KEY_REFETCH_LIMIT_SECONDS = 10
ADAPTER_TIMEOUT_SECONDS = 120
METHODS = ["GET", "POST", "PUT", "DELETE", "PATCH"]
NOT_FORWARDED = {
    "host", "connection", "keep-alive", "proxy-authenticate", "proxy-authorization", "te", "trailer",
    "transfer-encoding", "upgrade", "content-length", "content-encoding",
}  # fmt: skip


@dataclass(frozen=True)
class Settings:
    keycloak_url: str = field(default_factory=lambda: environ.get("KEYCLOAK_URL", "").rstrip("/"))
    keycloak_realm: str = field(default_factory=lambda: environ.get("KEYCLOAK_REALM", "dataspace"))
    registry_url: str = field(default_factory=lambda: environ.get("REGISTRY_URL", "").rstrip("/"))

    @property
    def issuer(self) -> str:
        return f"{self.keycloak_url}/realms/{self.keycloak_realm}"


class TokenChecker:
    def __init__(self, issuer: str, http: httpx.AsyncClient, clock: Callable[[], float]) -> None:
        self.issuer = issuer
        self.http = http
        self.clock = clock
        self.keys: dict[str, object] = {}
        self.fetched_at: float | None = None

    async def _fetch_keys(self) -> None:
        response = await self.http.get(f"{self.issuer}/protocol/openid-connect/certs")
        response.raise_for_status()
        self.keys = {
            key["kid"]: jwt.PyJWK(key).key
            for key in response.json()["keys"]
            if key.get("use", "sig") == "sig" and key.get("kty") == "RSA"
        }
        self.fetched_at = self.clock()

    async def _refresh(self) -> bool:
        """Fetch the keys unless that was done moments ago, so bad tokens can't cause a fetch each."""
        if self.fetched_at is not None and self.clock() - self.fetched_at < KEY_REFETCH_LIMIT_SECONDS:
            return False
        await self._fetch_keys()
        return True

    def _decode(self, token: str, key: object) -> dict:
        return jwt.decode(token, key, algorithms=["RS256"], issuer=self.issuer, options={"verify_aud": False})

    async def claims(self, authorization: str | None) -> dict:
        scheme, _, token = (authorization or "").partition(" ")
        if scheme.lower() != "bearer" or not token:
            raise HTTPException(status_code=401, detail="Missing token")
        try:
            kid = jwt.get_unverified_header(token).get("kid")
        except jwt.PyJWTError as error:
            raise HTTPException(status_code=401, detail="Invalid token") from error

        if kid not in self.keys:
            try:
                await self._refresh()
            except httpx.HTTPError as error:
                raise HTTPException(status_code=502, detail="Signing keys are unreachable") from error
        key = self.keys.get(kid)
        if key is None:
            raise HTTPException(status_code=401, detail="Invalid token")

        try:
            return self._decode(token, key)
        except jwt.InvalidSignatureError as first_error:
            # A rotation can reuse a key id, so look again before refusing.
            try:
                refreshed = await self._refresh()
            except httpx.HTTPError:
                refreshed = False
            if not refreshed or kid not in self.keys:
                raise HTTPException(status_code=401, detail="Invalid token") from first_error
            try:
                return self._decode(token, self.keys[kid])
            except jwt.PyJWTError as error:
                raise HTTPException(status_code=401, detail="Invalid token") from error
        except jwt.PyJWTError as error:
            raise HTTPException(status_code=401, detail="Invalid token") from error


class Directory:
    """Registry lookups, cached for a short time. Failures aren't cached."""

    def __init__(self, base_url: str, http: httpx.AsyncClient, clock: Callable[[], float]) -> None:
        self.base = base_url
        self.http = http
        self.clock = clock
        self.cache: dict[str, tuple[float, dict]] = {}

    async def _get(self, path: str) -> httpx.Response:
        try:
            response = await self.http.get(f"{self.base}{path}")
        except httpx.HTTPError as error:
            raise HTTPException(status_code=503, detail="The registry is unavailable") from error
        if response.status_code >= 500:
            raise HTTPException(status_code=503, detail="The registry is unavailable")
        return response

    async def lookup(self, participant_id: str) -> dict | None:
        cached = self.cache.get(participant_id)
        if cached and self.clock() - cached[0] < REGISTRY_CACHE_SECONDS:
            return cached[1]
        response = await self._get(f"/participants/{quote(participant_id, safe=':')}")
        if response.status_code == 404:
            self.cache.pop(participant_id, None)
            return None
        record = response.json()
        self.cache[participant_id] = (self.clock(), record)
        return record

    async def compatible(self, participant_id: str) -> list[dict]:
        response = await self._get(f"/participants/compatible/{quote(participant_id, safe=':')}")
        if response.status_code == 404:
            raise HTTPException(status_code=403, detail="Participant is not registered")
        return response.json()


def clean_path(raw: str) -> str:
    """Resolve "." and ".." segments, and refuse any way of writing a path into internal/."""
    decoded = raw
    while (once := unquote(decoded)) != decoded:
        decoded = once
    resolved = posixpath.normpath("/" + decoded.replace("\\", "/")).lstrip("/")
    if resolved.split("/", 1)[0].lower() == "internal":
        raise HTTPException(status_code=404, detail="Not found")
    keep_slash = "/" if raw.endswith("/") and resolved not in {"", "."} else ""
    return "" if resolved == "." else resolved + keep_slash


async def forward(http: httpx.AsyncClient, request: Request, target: str) -> Response:
    headers = {key: value for key, value in request.headers.items() if key.lower() not in NOT_FORWARDED}
    try:
        answer = await http.request(
            request.method,
            target,
            params=request.url.query or None,
            headers=headers,
            content=await request.body(),
            timeout=ADAPTER_TIMEOUT_SECONDS,
        )
    except httpx.TimeoutException as error:
        raise HTTPException(status_code=504, detail="The adapter did not answer in time") from error
    except httpx.HTTPError as error:
        raise HTTPException(status_code=503, detail="The adapter is unavailable") from error
    returned = {key: value for key, value in answer.headers.items() if key.lower() not in NOT_FORWARDED}
    return Response(content=answer.content, status_code=answer.status_code, headers=returned)


def adapter_address(record: dict) -> str:
    address = (record.get("adapter_url") or "").rstrip("/")
    if not address:
        raise HTTPException(status_code=503, detail="The adapter is unavailable")
    return address


def create_app(
    settings: Settings | None = None,
    http: httpx.AsyncClient | None = None,
    clock: Callable[[], float] = time.monotonic,
) -> FastAPI:
    settings = settings or Settings()
    own_client = http is None
    http = http or httpx.AsyncClient(timeout=30)
    tokens = TokenChecker(settings.issuer, http, clock)
    directory = Directory(settings.registry_url, http, clock)

    @asynccontextmanager
    async def lifespan(_: FastAPI) -> AsyncIterator[None]:
        yield
        if own_client:
            await http.aclose()

    application = FastAPI(title="API Gateway", lifespan=lifespan, docs_url=None, redoc_url=None, openapi_url=None)

    async def caller(request: Request) -> tuple[str, dict]:
        """Return the calling participant's id and registry record."""
        claims = await tokens.claims(request.headers.get("Authorization"))
        participant_id = claims.get("participant_id")
        if not participant_id:
            raise HTTPException(status_code=403, detail="The token has no participant_id claim")
        record = await directory.lookup(participant_id)
        if record is None:
            raise HTTPException(status_code=403, detail="Participant is not registered")
        return participant_id, record

    @application.get("/health")
    def health() -> dict[str, str]:
        return {"status": "ok"}

    @application.get("/participants/compatible")
    async def compatible(request: Request) -> JSONResponse:
        participant_id, _ = await caller(request)
        return JSONResponse(await directory.compatible(participant_id))

    @application.post("/peer/{receiver:path}/internal/transfer-request")
    async def peer(receiver: str, request: Request) -> Response:
        # Any valid token will do here. The receiving adapter decides whether it accepts the sender.
        await tokens.claims(request.headers.get("Authorization"))
        record = await directory.lookup(receiver)
        if record is None:
            raise HTTPException(status_code=404, detail="Receiver is not registered")
        return await forward(http, request, f"{adapter_address(record)}/internal/transfer-request")

    @application.api_route("/{path:path}", methods=METHODS)
    async def catch_all(path: str, request: Request) -> Response:
        # Refuse internal paths before anything else, so they look the same with or without a token.
        cleaned = clean_path(request.scope.get("raw_path", path.encode()).decode().lstrip("/"))
        _, record = await caller(request)
        return await forward(http, request, f"{adapter_address(record)}/{quote(cleaned, safe='/:')}")

    return application


app = create_app()
