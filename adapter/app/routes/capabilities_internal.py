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
"""Capability routes for peers and management. The gateway never forwards agents to these."""

import hmac
from typing import Literal

from fastapi import APIRouter, Depends, Header, HTTPException, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel
from sqlalchemy import select

from app import capabilities as store
from app.auth import bearer_token, holds_role
from app.db import CapabilityApproval

router = APIRouter(prefix="/internal/capabilities")


class ApprovalAction(BaseModel):
    consumer_id: str
    capability: str
    action: Literal["request", "approve", "deny"]
    conversation_id: str | None = None
    purpose: str | None = None
    note: str | None = None


class ApprovalChange(BaseModel):
    action: Literal["approve", "deny", "reset"]
    note: str | None = None


class DefaultChange(BaseModel):
    default_policy: Literal["auto", "on-request"]


STATUS_FOR = {"approve": store.APPROVED, "deny": store.DENIED}


def _key_matches(request: Request, given: str) -> bool:
    configured = request.app.state.services.settings.adapter_internal_key
    return bool(configured) and hmac.compare_digest(configured.encode(), given.encode())


async def _caller(request: Request, x_internal_key: str | None = Header(default=None)) -> str | None:
    """None for management, which holds the key. Otherwise the compatible peer that the token belongs to."""
    if x_internal_key is not None:
        if not _key_matches(request, x_internal_key):
            raise HTTPException(status_code=401, detail="Wrong internal key")
        return None
    services = request.app.state.services
    claims = await services.verifier.claims(bearer_token(request))
    peer = claims.get("participant_id")
    if not peer or not holds_role(claims, peer):
        raise HTTPException(status_code=403, detail="The token does not belong to a participant")
    try:
        await services.registry.receiver(services.settings.participant_id, peer)
    except HTTPException as error:
        if error.status_code == 404:
            raise HTTPException(status_code=403, detail="This participant is not registered") from error
        raise
    return peer


async def _management(request: Request, x_internal_key: str | None = Header(default=None)) -> None:
    if x_internal_key is None:
        if request.headers.get("Authorization"):
            raise HTTPException(status_code=403, detail="This needs the internal key")
        raise HTTPException(status_code=401, detail="This needs the internal key")
    if not _key_matches(request, x_internal_key):
        raise HTTPException(status_code=401, detail="Wrong internal key")


@router.get("")
async def read_state(request: Request, peer: str | None = Depends(_caller)) -> dict:
    services = request.app.state.services
    participant_type = services.settings.participant_type
    query = select(CapabilityApproval)
    if peer is not None:
        query = query.where(CapabilityApproval.consumer_id == peer)
    async with services.db.session() as session:
        defaults = await store.defaults(session, participant_type)
        approvals = [store.approval_view(row) for row in (await session.execute(query)).scalars()]
    return {
        "capabilities": [
            {
                "capability": name,
                "label": capability.label,
                "description": capability.description,
                "data_classification": capability.data_classification,
                "default_policy": defaults[name],
            }
            for name, capability in store.offered_by(participant_type).items()
        ],
        "approvals": approvals,
    }


@router.post("/approvals")
async def record_approval(body: ApprovalAction, request: Request, peer: str | None = Depends(_caller)) -> JSONResponse:
    services = request.app.state.services
    participant_type = services.settings.participant_type
    if peer is not None and (body.action != "request" or body.consumer_id != peer):
        raise HTTPException(status_code=403, detail="A peer may only ask for access for itself")
    store.require_offered(participant_type, body.capability)
    async with services.db.session() as session:
        if body.action == "request":
            answer = await store.record_request(
                session,
                participant_type,
                body.consumer_id,
                body.capability,
                body.conversation_id,
                body.purpose,
                body.note,
            )
            return JSONResponse(status_code=202, content=answer)
        answer = await store.set_access(
            session, body.consumer_id, body.capability, STATUS_FOR[body.action], body.note
        )
    return JSONResponse(status_code=200, content=answer)


@router.patch("/approvals/{approval_id}", dependencies=[Depends(_management)])
async def change_approval(approval_id: str, body: ApprovalChange, request: Request) -> dict:
    services = request.app.state.services
    async with services.db.session() as session:
        if body.action != "reset":
            return await store.resolve(session, approval_id, STATUS_FOR[body.action], body.note)
        row = await session.get(CapabilityApproval, approval_id)
        if row is None:
            raise HTTPException(status_code=404, detail="Request not found")
        return await store.reset(session, services.settings.participant_type, row.consumer_id, row.capability)


@router.patch("/{capability}", dependencies=[Depends(_management)])
async def change_default(capability: str, body: DefaultChange, request: Request) -> dict:
    services = request.app.state.services
    store.require_offered(services.settings.participant_type, capability)
    async with services.db.session() as session:
        await store.change_default(session, capability, body.default_policy)
    return {"capability": capability, "default_policy": body.default_policy}
