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

"""Sending messages."""

import json
import logging
import uuid
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from app.auth import require_participant
from app.db import Conversation, OutboxMessage, iso, touch_conversation
from app.delivery import deliver

log = logging.getLogger("adapter")

router = APIRouter(dependencies=[Depends(require_participant)])


class ContentRef(BaseModel):
    asset_id: str
    dsp_url: str


class OutgoingMessage(BaseModel):
    receiver_participant: str
    performative: str = "inform"
    capability: str | None = None
    in_reply_to: str | None = None
    authorization: dict | None = None
    outcome: str | None = None
    conversation_id: str | None = None
    payload: dict | None = None
    content_ref: ContentRef | None = None
    reply_expected: bool = False
    expires_at: datetime | None = None
    response_due_at: datetime | None = None


async def conversation_state(session, conversation_id: str) -> str:
    conversation = await session.get(Conversation, conversation_id)
    return conversation.state if conversation else "OPEN"


@router.post("/outbox/messages", status_code=202)
async def send_message(body: OutgoingMessage, request: Request):
    services = request.app.state.services
    own_id = services.settings.participant_id

    if body.payload is not None and body.content_ref is not None:
        return JSONResponse(
            status_code=422,
            content={
                "error": "invalid_message",
                "reason": "payload_and_content_ref",
                "detail": "A message can have a payload or a content reference, not both",
                "performative": body.performative,
            },
        )

    peer = await services.registry.receiver(own_id, body.receiver_participant)

    message_id = str(uuid.uuid4())
    conversation_id = body.conversation_id or str(uuid.uuid4())
    payload_ref = None
    if body.content_ref is None:
        try:
            payload_ref = await services.storage.put(f"messages/{message_id}.json", json.dumps(body.payload).encode())
        except Exception as error:
            raise HTTPException(status_code=503, detail="Object storage is unavailable") from error

    row = OutboxMessage(
        message_id=message_id,
        conversation_id=conversation_id,
        performative=body.performative,
        capability=body.capability,
        in_reply_to=body.in_reply_to,
        authorization=body.authorization,
        outcome=body.outcome,
        sender_participant=own_id,
        receiver_participant=body.receiver_participant,
        payload_ref=payload_ref,
        content_ref=body.content_ref.model_dump() if body.content_ref else None,
        reply_expected=body.reply_expected,
        expires_at=body.expires_at,
        response_due_at=body.response_due_at,
        status="pending",
        applied=True,
    )
    try:
        async with services.db.session() as session:
            session.add(row)
            await touch_conversation(session, conversation_id, body.receiver_participant)
            await session.commit()
    except Exception:
        # Without a row, retention could never remove what was just uploaded.
        if payload_ref:
            try:
                await services.storage.delete(payload_ref)
            except Exception as error:
                log.warning("Could not remove the content of unsaved message %s: %s", message_id, error)
        raise
    async with services.db.session() as session:
        state = await conversation_state(session, conversation_id)

    notification = {
        "message_id": message_id,
        "conversation_id": conversation_id,
        "performative": body.performative,
        "capability": body.capability,
        "in_reply_to": body.in_reply_to,
        "authorization": body.authorization,
        "outcome": body.outcome,
        "sender_participant": own_id,
        "receiver_participant": body.receiver_participant,
        "reply_expected": body.reply_expected,
        "expires_at": iso(body.expires_at),
        "response_due_at": iso(body.response_due_at),
        "content_ref": row.content_ref,
    }
    services.spawn(deliver(services, notification, peer))
    return {"message_id": message_id, "status": "pending", "applied": True, "conversation_state": state}


async def _get_row(request: Request, message_id: str) -> OutboxMessage:
    async with request.app.state.services.db.session() as session:
        row = await session.get(OutboxMessage, message_id)
    if row is None:
        raise HTTPException(status_code=404, detail="Message not found")
    return row


@router.get("/outbox/messages/{message_id}")
async def read_message(message_id: str, request: Request) -> dict:
    row = await _get_row(request, message_id)
    return {
        "message_id": row.message_id,
        "conversation_id": row.conversation_id,
        "performative": row.performative,
        "capability": row.capability,
        "in_reply_to": row.in_reply_to,
        "outcome": row.outcome,
        "sender_participant": row.sender_participant,
        "receiver_participant": row.receiver_participant,
        "created_at": iso(row.created_at),
        "payload_ref": row.payload_ref,
        "content_ref": row.content_ref,
        "reply_expected": row.reply_expected,
        "status": row.status,
        "applied": row.applied,
    }


@router.get("/outbox/messages/{message_id}/status")
async def read_status(message_id: str, request: Request) -> dict:
    row = await _get_row(request, message_id)
    async with request.app.state.services.db.session() as session:
        state = await conversation_state(session, row.conversation_id)
    return {
        "message_id": row.message_id,
        "status": row.status,
        "edc_transfer_id": row.edc_transfer_id,
        "error_message": row.error_message,
        "updated_at": iso(row.updated_at),
        "applied": row.applied,
        "conversation_state": state,
    }
