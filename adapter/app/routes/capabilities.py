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
"""The agent's capability routes. They record and report access, and never block a message."""

from typing import Literal

import httpx
from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel
from sqlalchemy import select

from app import capabilities as store
from app.auth import require_participant
from app.db import CapabilityApproval

router = APIRouter(dependencies=[Depends(require_participant)])


class CapabilityRequest(BaseModel):
    provider_participant: str
    capability: str
    conversation_id: str | None = None
    purpose: str | None = None
    note: str | None = None


class Decision(BaseModel):
    action: Literal["approve", "deny"]
    note: str | None = None


class PolicyAction(BaseModel):
    consumer_id: str
    capability: str
    action: Literal["approve", "deny", "reset"]


STATUS_FOR = {"approve": store.APPROVED, "deny": store.DENIED}


async def _call_provider(services, provider: dict, method: str, path: str, **arguments) -> httpx.Response:
    """Call a provider's adapter directly. Going through the gateway's peer route belongs with #18."""
    address = (provider.get("adapter_url") or "").rstrip("/")
    if not address:
        raise HTTPException(status_code=503, detail="The provider's adapter has no address")
    try:
        token = await services.own_token.get()
        answer = await services.http.request(
            method, f"{address}{path}", headers={"Authorization": f"Bearer {token}"}, **arguments
        )
    except httpx.HTTPError as error:
        raise HTTPException(status_code=503, detail="The provider's adapter is unavailable") from error
    if answer.status_code in {403, 404, 409, 422}:
        try:
            detail = answer.json().get("detail", "The provider refused this")
        except ValueError:
            detail = "The provider refused this"
        raise HTTPException(status_code=answer.status_code, detail=detail)
    if answer.status_code >= 300:
        raise HTTPException(status_code=503, detail="The provider's adapter is unavailable")
    return answer


@router.get("/capabilities/access")
async def access(request: Request, provider: str | None = None, consumer: str | None = None) -> list[dict]:
    services = request.app.state.services
    settings = services.settings
    if (provider is None) == (consumer is None):
        raise HTTPException(status_code=422, detail="Give either provider or consumer")

    if consumer is not None:
        async with services.db.session() as session:
            defaults = await store.defaults(session, settings.participant_type)
            rows = await session.execute(select(CapabilityApproval).where(CapabilityApproval.consumer_id == consumer))
            approvals = {row.capability: store.approval_view(row) for row in rows.scalars()}
        return [
            store.access_entry(name, capability, defaults[name], approvals.get(name))
            for name, capability in store.offered_by(settings.participant_type).items()
        ]

    record = await services.registry.receiver(settings.participant_id, provider)
    state = (await _call_provider(services, record, "GET", "/internal/capabilities")).json()
    approvals = {item["capability"]: item for item in state["approvals"]}
    return [
        store.access_entry(item["capability"], item, item["default_policy"], approvals.get(item["capability"]))
        for item in state["capabilities"]
    ]


@router.post("/capabilities/requests", status_code=202)
async def ask(body: CapabilityRequest, request: Request) -> dict:
    services = request.app.state.services
    own_id = services.settings.participant_id
    record = await services.registry.receiver(own_id, body.provider_participant)
    answer = await _call_provider(
        services,
        record,
        "POST",
        "/internal/capabilities/approvals",
        json={
            "consumer_id": own_id,
            "capability": body.capability,
            "action": "request",
            "conversation_id": body.conversation_id,
            "purpose": body.purpose,
            "note": body.note,
        },
    )
    return answer.json()


@router.get("/capabilities/requests")
async def list_requests(request: Request, status: str | None = None) -> list[dict]:
    query = select(CapabilityApproval).order_by(CapabilityApproval.requested_at.desc())
    if status is not None:
        query = query.where(CapabilityApproval.status == status)
    async with request.app.state.services.db.session() as session:
        return [store.approval_view(row) for row in (await session.execute(query)).scalars()]


@router.patch("/capabilities/requests/{approval_id}")
async def decide(approval_id: str, body: Decision, request: Request) -> dict:
    async with request.app.state.services.db.session() as session:
        return await store.resolve(session, approval_id, STATUS_FOR[body.action], body.note)


@router.post("/capabilities/policy")
async def set_policy(body: PolicyAction, request: Request) -> dict:
    services = request.app.state.services
    settings = services.settings
    store.require_offered(settings.participant_type, body.capability)
    async with services.db.session() as session:
        if body.action == "reset":
            return await store.reset(session, settings.participant_type, body.consumer_id, body.capability)
    await services.registry.receiver(settings.participant_id, body.consumer_id)
    async with services.db.session() as session:
        stored = await store.set_access(session, body.consumer_id, body.capability, STATUS_FOR[body.action], None)
    return {
        "consumer_id": body.consumer_id,
        "capability": body.capability,
        "status": stored["status"],
        "source": "explicit",
    }
