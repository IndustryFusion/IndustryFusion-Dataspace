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

"""Management API: onboarding participants, and administering their capabilities."""

import asyncio
import pathlib
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import dataclass
from typing import Literal

import httpx
from fastapi import Depends, FastAPI, Header, HTTPException, Query, Request, Response
from fastapi.exceptions import RequestValidationError
from fastapi.responses import FileResponse, JSONResponse
from pydantic import BaseModel, field_validator

from app import roles
from app.adapters import Adapters, policy_entries
from app.config import Settings
from app.databases import Databases
from app.health import component_health
from app.ifric import CompanyDirectory
from app.keycloak import KeycloakAdmin
from app.kubernetes import Kubernetes, in_cluster_client
from app.provisioning import Provisioner, Registration
from app.registry import Registry
from app.storage import Buckets
from app.tokens import AdminTokens, fetch_admin_token


class TokenRequest(BaseModel):
    client_id: str
    client_secret: str


class ParticipantRequest(BaseModel):
    participant_id: str
    participant_type: str
    hosted: bool = True
    externally_reachable: bool = False
    adapter_url: str | None = None
    dsp_url: str | None = None
    peer_notify_url: str | None = None

    @field_validator("participant_id")
    @classmethod
    def id_is_safe(cls, value: str) -> str:
        if not roles.id_is_safe(value):
            raise ValueError(
                "participant_id must be up to 200 ASCII letters, digits, '.', '_', ':' or '-', from a letter or digit"
            )
        return value

    @field_validator("participant_type")
    @classmethod
    def type_is_known(cls, value: str) -> str:
        if not roles.is_known(value):
            raise ValueError("unknown participant_type")
        return value


class DefaultChange(BaseModel):
    default_policy: Literal["auto", "on-request"]


class ApprovalRequest(BaseModel):
    consumer_id: str
    capability: str
    action: Literal["approve", "deny", "request"]
    conversation_id: str | None = None
    purpose: str | None = None
    note: str | None = None


class ApprovalChange(BaseModel):
    action: Literal["approve", "deny", "reset"]
    note: str | None = None


@dataclass
class Services:
    settings: Settings
    http: httpx.AsyncClient
    tokens: AdminTokens
    registry: Registry
    adapters: Adapters
    databases: Databases
    provisioner: Provisioner
    companies: CompanyDirectory

    def keycloak(self, token: str) -> KeycloakAdmin:
        return KeycloakAdmin(self.http, self.settings.keycloak_url, self.settings.keycloak_realm, token)


def build_services(settings: Settings, http: httpx.AsyncClient, kubernetes: Kubernetes) -> Services:
    registry = Registry(http, settings.registry_url)
    databases = Databases(settings)
    return Services(
        settings=settings,
        http=http,
        tokens=AdminTokens(settings.issuer, http),
        registry=registry,
        adapters=Adapters(http, settings.adapter_internal_key, settings.participants_namespace),
        databases=databases,
        provisioner=Provisioner(settings, databases, kubernetes, registry, Buckets(settings)),
        companies=CompanyDirectory(settings, http),
    )


@asynccontextmanager
async def lifespan(application: FastAPI) -> AsyncIterator[None]:
    if getattr(application.state, "services", None) is not None:
        yield
        return
    settings = Settings()
    http = httpx.AsyncClient(timeout=30)
    kube_http, kube_token = in_cluster_client()
    kubernetes = Kubernetes(kube_http, kube_token, settings.participants_namespace, settings.poll_seconds)
    application.state.services = build_services(settings, http, kubernetes)
    yield
    await http.aclose()
    await kube_http.aclose()


app = FastAPI(title="Management API", lifespan=lifespan)


@app.exception_handler(RequestValidationError)
async def invalid_request(_: Request, error: RequestValidationError) -> JSONResponse:
    """Without what was sent, as that can be a client secret."""
    detail = [{"loc": entry["loc"], "msg": entry["msg"], "type": entry["type"]} for entry in error.errors()]
    return JSONResponse(status_code=422, content={"detail": detail})


def services_of(request: Request) -> Services:
    return request.app.state.services


async def admin_token(
    services: Services = Depends(services_of), authorization: str | None = Header(default=None)
) -> str:
    return await services.tokens.require_admin(authorization)


async def participant_or_404(services: Services, participant_id: str) -> dict:
    record = await services.registry.get(participant_id) if roles.id_is_safe(participant_id) else None
    if record is None:
        raise HTTPException(status_code=404, detail="Participant not found")
    return record


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/api/health")
async def api_health(services: Services = Depends(services_of)) -> dict:
    return await component_health(services.settings, services.http, services.databases)


@app.post("/api/admin/token")
async def admin_token_route(body: TokenRequest, services: Services = Depends(services_of)) -> dict:
    return await fetch_admin_token(services.http, services.settings.issuer, body.client_id, body.client_secret)


@app.post("/api/participants")
async def register_participant(
    body: ParticipantRequest, services: Services = Depends(services_of), token: str = Depends(admin_token)
) -> dict:
    if not body.hosted and not (body.adapter_url and body.dsp_url):
        raise HTTPException(status_code=422, detail="An external participant needs adapter_url and dsp_url")
    return await services.provisioner.register(Registration(**body.model_dump()), services.keycloak(token))


@app.post("/api/demo")
async def create_demo(services: Services = Depends(services_of), token: str = Depends(admin_token)) -> list[dict]:
    keycloak = services.keycloak(token)
    outcomes = await asyncio.gather(
        *(
            services.provisioner.register(Registration(participant, kind), keycloak)
            for participant, kind in services.settings.demo_participants
        ),
        return_exceptions=True,
    )
    for outcome in outcomes:
        if isinstance(outcome, BaseException):
            raise outcome
    return list(outcomes)


@app.get("/api/participants")
async def list_participants(services: Services = Depends(services_of)) -> list[dict]:
    return await services.companies.add_details(await services.registry.all())


@app.get("/api/participants/compatible/{participant_id:path}")
async def compatible_participants(participant_id: str, services: Services = Depends(services_of)) -> list[dict]:
    found = await services.registry.compatible(participant_id) if roles.id_is_safe(participant_id) else None
    if found is None:
        raise HTTPException(status_code=404, detail="Participant not found")
    return await services.companies.add_details(found)


# Declared before the single-participant route, whose path would match all of these.
@app.get("/api/participants/{participant_id:path}/credentials")
async def participant_credentials(
    participant_id: str, services: Services = Depends(services_of), token: str = Depends(admin_token)
) -> dict:
    await participant_or_404(services, participant_id)
    secret = await services.keycloak(token).owned_client_secret(participant_id)
    if secret is None:
        raise HTTPException(status_code=404, detail="This participant has no client")
    return {"client_id": participant_id, "client_secret": secret}


@app.get("/api/participants/{participant_id:path}/capabilities")
async def read_capabilities(participant_id: str, services: Services = Depends(services_of)) -> dict:
    return await services.adapters.state(await participant_or_404(services, participant_id))


@app.patch("/api/participants/{participant_id:path}/capabilities/{capability}", dependencies=[Depends(admin_token)])
async def change_default(
    participant_id: str, capability: str, body: DefaultChange, services: Services = Depends(services_of)
) -> object:
    record = await participant_or_404(services, participant_id)
    return await services.adapters.set_default(record, capability, body.default_policy)


@app.post("/api/participants/{participant_id:path}/approvals", dependencies=[Depends(admin_token)])
async def record_approval(
    participant_id: str, body: ApprovalRequest, services: Services = Depends(services_of)
) -> JSONResponse:
    record = await participant_or_404(services, participant_id)
    consumer = await services.registry.get(body.consumer_id)
    if consumer is None:
        raise HTTPException(status_code=404, detail="The consumer is not registered")
    if not roles.compatible(record["participant_type"], consumer["participant_type"]):
        raise HTTPException(status_code=403, detail="The consumer's role is not compatible with this participant")
    status, content = await services.adapters.record_decision(record, body.model_dump())
    return JSONResponse(status_code=status, content=content)


@app.patch("/api/participants/{participant_id:path}/approvals/{approval_id}", dependencies=[Depends(admin_token)])
async def change_approval(
    participant_id: str, approval_id: str, body: ApprovalChange, services: Services = Depends(services_of)
) -> object:
    record = await participant_or_404(services, participant_id)
    return await services.adapters.change_decision(record, approval_id, body.model_dump())


@app.get("/api/participants/{participant_id:path}")
async def read_participant(participant_id: str, services: Services = Depends(services_of)) -> dict:
    return (await services.companies.add_details([await participant_or_404(services, participant_id)]))[0]


@app.delete("/api/participants/{participant_id:path}", status_code=204)
async def delete_participant(
    participant_id: str, services: Services = Depends(services_of), token: str = Depends(admin_token)
) -> Response:
    if not roles.id_is_safe(participant_id):
        raise HTTPException(status_code=404, detail="Participant not found")
    await services.provisioner.remove(participant_id, services.keycloak(token))
    return Response(status_code=204)


@app.get("/api/policy")
async def read_policy(
    fo: str = Query(min_length=1),
    mb: str = Query(min_length=1),
    services: Services = Depends(services_of),
    authorization: str | None = Header(default=None),
) -> dict:
    owner = await participant_or_404(services, fo)
    builder = await participant_or_404(services, mb)
    if roles.bare_name(owner["participant_type"]) != roles.FACTORY_OWNER:
        raise HTTPException(status_code=422, detail="fo is not a factory owner")
    if roles.bare_name(builder["participant_type"]) != roles.MACHINE_BUILDER:
        raise HTTPException(status_code=422, detail="mb is not a machine builder")
    if not (owner.get("hosted") and builder.get("hosted")):
        await services.tokens.require_admin(authorization)
    entries: list[dict] = []
    unavailable: list[str] = []
    for provider, consumer in ((owner, builder), (builder, owner)):
        if provider.get("hosted"):
            state = await services.adapters.state(provider)
            entries.extend(policy_entries(provider, consumer["participant_id"], state))
        else:
            unavailable.append(provider["participant_id"])
    return {"factory_owner": fo, "machine_builder": mb, "capabilities": entries, "unavailable": unavailable}


@app.get("/{path:path}", include_in_schema=False)
async def user_interface(path: str, services: Services = Depends(services_of)) -> FileResponse:
    """The built UI. A path it doesn't have gets its page, as the page has the screens. Declared last."""
    if path == "api" or path.startswith("api/") or "\x00" in path:
        raise HTTPException(status_code=404, detail="Not found")
    root = pathlib.Path(services.settings.ui_dir).resolve()
    wanted = (root / path).resolve()
    if wanted.is_relative_to(root) and wanted.is_file():
        return FileResponse(wanted)
    page = root / "index.html"
    if not page.is_file():
        raise HTTPException(status_code=404, detail="The management UI is not part of this installation")
    return FileResponse(page)
