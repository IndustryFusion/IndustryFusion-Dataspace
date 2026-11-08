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

"""What each component's health looks like from here. Details never include addresses or credentials."""

import asyncio
import time
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime

import httpx

from app.config import Settings
from app.databases import Databases

PROBE_SECONDS = 5


async def _http_probe(http: httpx.AsyncClient, url: str, any_answer: bool = False) -> None:
    answer = await http.get(url, timeout=PROBE_SECONDS)
    if not any_answer and answer.status_code >= 300:
        raise RuntimeError(f"It answered {answer.status_code}")


async def _report(name: str, probe: Callable[[], Awaitable[None]] | None) -> dict:
    if probe is None:
        return {"name": name, "status": "not configured", "detail": "No address is configured", "response_ms": None}
    started = time.monotonic()

    def elapsed() -> int:
        return int((time.monotonic() - started) * 1000)

    try:
        async with asyncio.timeout(PROBE_SECONDS):
            await probe()
    except RuntimeError as error:
        return {"name": name, "status": "unhealthy", "detail": str(error), "response_ms": elapsed()}
    except Exception:
        return {"name": name, "status": "unhealthy", "detail": "It could not be reached", "response_ms": elapsed()}
    return {"name": name, "status": "ok", "detail": None, "response_ms": elapsed()}


async def component_health(settings: Settings, http: httpx.AsyncClient, databases: Databases) -> dict:
    def probe_of(url: str, path: str = "/health", any_answer: bool = False):
        return (lambda: _http_probe(http, f"{url}{path}", any_answer)) if url else None

    keycloak = settings.keycloak_health_url or (f"{settings.issuer}" if settings.keycloak_url else "")
    probes = {
        "registry": probe_of(settings.registry_url),
        "gateway": probe_of(settings.gateway_url),
        "dsp-gateway": probe_of(settings.dsp_gateway_url),
        "keycloak": probe_of(keycloak, path=""),
        "postgresql": databases.healthy if settings.postgres_host else None,
        # An unsigned request is refused, and that answer is enough to show it is up.
        "storage": probe_of(settings.s3_endpoint, path="/", any_answer=True),
    }
    checked_at = datetime.now(UTC).isoformat()
    components = await asyncio.gather(*(_report(name, probe) for name, probe in probes.items()))
    status = "ok" if all(c["status"] == "ok" for c in components) else "degraded"
    return {"status": status, "checked_at": checked_at, "components": components}
