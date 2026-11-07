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

"""DSP gateway: a path router from outside the cluster to hosted connectors' DSP and public ports. It keeps no state."""

import re
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from os import environ
from urllib.parse import unquote

import httpx
from fastapi import FastAPI, HTTPException, Request, Response
from fastapi.responses import StreamingResponse

CONNECTOR_TIMEOUT_SECONDS = 120
METHODS = ["GET", "POST", "PUT", "DELETE", "PATCH"]
PORTS = {"dsp": 8082, "public": 8084}
SLUG = re.compile(r"^[0-9a-f]{8}$")
NOT_FORWARDED = {
    "host", "connection", "keep-alive", "proxy-authenticate", "proxy-authorization", "te", "trailer",
    "transfer-encoding", "upgrade", "content-length",
}  # fmt: skip
# The HTTP client decodes answers, so an answer's Content-Encoding would no longer be true.
NOT_RETURNED = NOT_FORWARDED | {"content-encoding"}
NOT_FOUND = HTTPException(status_code=404, detail="Not found")


@dataclass(frozen=True)
class Settings:
    participants_namespace: str = field(
        default_factory=lambda: environ.get("PARTICIPANTS_NAMESPACE", "dataspace-participants")
    )


def target_of(raw_path: str, namespace: str) -> str:
    decoded = raw_path
    while (once := unquote(decoded)) != decoded:
        decoded = once
    # The connector's web server reads "..;x" as "..".
    if any(segment.split(";")[0] == ".." for segment in decoded.replace("\\", "/").split("/")):
        raise NOT_FOUND
    parts = raw_path.split("/", 5)
    # An empty first part, the slug, api, v1, the kind, and what follows it.
    if len(parts) != 6 or parts[0] or parts[2:4] != ["api", "v1"] or not parts[5]:
        raise NOT_FOUND
    slug, kind, rest = parts[1], parts[4], parts[5]
    if not SLUG.match(slug) or kind not in PORTS:
        raise NOT_FOUND
    return f"http://connector-{slug}.{namespace}:{PORTS[kind]}/api/v1/{kind}/{rest}"


def create_app(settings: Settings | None = None, http: httpx.AsyncClient | None = None) -> FastAPI:
    settings = settings or Settings()
    own_client = http is None
    http = http or httpx.AsyncClient(timeout=30)

    @asynccontextmanager
    async def lifespan(_: FastAPI) -> AsyncIterator[None]:
        yield
        if own_client:
            await http.aclose()

    application = FastAPI(title="DSP Gateway", lifespan=lifespan, docs_url=None, redoc_url=None, openapi_url=None)

    @application.get("/health")
    def health() -> dict[str, str]:
        return {"status": "ok"}

    @application.api_route("/{path:path}", methods=METHODS)
    async def route(path: str, request: Request) -> Response:
        target = target_of(request.scope.get("raw_path", path.encode()).decode(), settings.participants_namespace)
        headers = {key: value for key, value in request.headers.items() if key.lower() not in NOT_FORWARDED}
        has_body = "content-length" in request.headers or "transfer-encoding" in request.headers
        if "content-length" in request.headers:
            headers["content-length"] = request.headers["content-length"]
        outgoing = http.build_request(
            request.method,
            target,
            params=request.url.query or None,
            headers=headers,
            content=request.stream() if has_body else None,
            timeout=CONNECTOR_TIMEOUT_SECONDS,
        )
        try:
            answer = await http.send(outgoing, stream=True)
        except httpx.TimeoutException as error:
            raise HTTPException(status_code=504, detail="The connector did not answer in time") from error
        except httpx.HTTPError as error:
            raise HTTPException(status_code=503, detail="The connector is unavailable") from error
        returned = {key: value for key, value in answer.headers.items() if key.lower() not in NOT_RETURNED}
        if "content-encoding" not in answer.headers and "content-length" in answer.headers:
            returned["content-length"] = answer.headers["content-length"]

        async def relay() -> AsyncIterator[bytes]:
            try:
                async for chunk in answer.aiter_bytes():
                    yield chunk
            finally:
                await answer.aclose()

        return StreamingResponse(relay(), status_code=answer.status_code, headers=returned)

    return application


app = create_app()
