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
"""Reading conversations."""

import json
import logging

from botocore.exceptions import ClientError
from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy import select

from app.auth import require_participant
from app.conversations import is_refused
from app.db import Conversation, InboxMessage, OutboxMessage, as_utc, iso

log = logging.getLogger("adapter")

router = APIRouter(dependencies=[Depends(require_participant)])


def _summary(conversation: Conversation) -> dict:
    return {
        "conversation_id": conversation.conversation_id,
        "state": conversation.state,
        "outcome": conversation.outcome,
        "counterpart_participant": conversation.counterpart_participant,
        "opened_at": iso(conversation.opened_at),
        "closed_at": iso(conversation.closed_at),
        "last_message_at": iso(conversation.last_message_at),
        "escalated_by": conversation.escalated_by,
    }


async def _payload(services, ref: str | None) -> dict | None:
    if not ref:
        return None
    if ref.endswith(".zip"):
        return {"_bundle": True}
    try:
        content = await services.storage.get(ref)
    except ClientError as error:
        log.warning("Could not read %s: %s", ref, error)
        return None
    if content is None:
        return None
    try:
        return json.loads(content)
    except ValueError:
        return None


def _refused(direction: str, row) -> bool:
    return row.status == "rejected" if direction == "sent" else is_refused(row)


async def _messages(services, conversation_id: str) -> list[tuple[str, OutboxMessage | InboxMessage]]:
    async with services.db.session() as session:
        sent = await session.execute(select(OutboxMessage).where(OutboxMessage.conversation_id == conversation_id))
        received = await session.execute(select(InboxMessage).where(InboxMessage.conversation_id == conversation_id))
        rows = [("sent", row) for row in sent.scalars()] + [("received", row) for row in received.scalars()]
    return sorted(rows, key=lambda item: as_utc(item[1].created_at))


@router.get("/conversations")
async def list_conversations(request: Request, state: str | None = None) -> list[dict]:
    query = select(Conversation).order_by(Conversation.last_message_at.desc())
    if state is not None:
        query = query.where(Conversation.state == state.upper())
    async with request.app.state.services.db.session() as session:
        return [_summary(row) for row in (await session.execute(query)).scalars()]


@router.get("/conversations/{conversation_id}")
async def read_conversation(conversation_id: str, request: Request) -> dict:
    services = request.app.state.services
    async with services.db.session() as session:
        conversation = await session.get(Conversation, conversation_id)
    if conversation is None:
        raise HTTPException(status_code=404, detail="Conversation not found")

    rows = await _messages(services, conversation_id)
    replied: dict[str, str] = {}
    for direction, row in rows:
        if row.in_reply_to and not _refused(direction, row):
            replied.setdefault(row.in_reply_to, iso(row.created_at))

    messages = []
    outstanding = []
    for direction, row in rows:
        ref = row.payload_ref
        view = {
            "message_id": row.message_id,
            "direction": direction,
            "performative": row.performative,
            "capability": row.capability,
            "in_reply_to": row.in_reply_to,
            "outcome": row.outcome,
            "sender_participant": row.sender_participant,
            "receiver_participant": row.receiver_participant,
            "created_at": iso(row.created_at),
            "applied": row.applied,
            "status": row.status,
            "error_message": row.error_message,
            "has_files": getattr(row, "has_files", bool(ref and ref.endswith(".zip"))),
            "replied_at": replied.get(row.message_id),
            "payload": await _payload(services, ref),
        }
        messages.append(view)
        if row.performative == "request" and not _refused(direction, row) and row.message_id not in replied:
            outstanding.append(view)
    return {**_summary(conversation), "messages": messages, "outstanding_requests": outstanding}
