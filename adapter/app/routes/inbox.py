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

"""Reading received messages."""

import json

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from sqlalchemy import select, update

from app.auth import require_participant
from app.db import InboxMessage, iso, now

router = APIRouter(dependencies=[Depends(require_participant)])


async def _payload(services, row: InboxMessage) -> dict | None:
    if row.has_files:
        return {"_bundle": True}
    if not row.payload_ref:
        return None
    content = await services.storage.get(row.payload_ref)
    if content is None:
        return None
    try:
        return json.loads(content)
    except ValueError:
        return None


async def _view(services, row: InboxMessage) -> dict:
    return {
        "message_id": row.message_id,
        "conversation_id": row.conversation_id,
        "performative": row.performative,
        "capability": row.capability,
        "in_reply_to": row.in_reply_to,
        "outcome": row.outcome,
        "authorization": row.authorization,
        "expires_at": iso(row.expires_at),
        "response_due_at": iso(row.response_due_at),
        "sender_participant": row.sender_participant,
        "receiver_participant": row.receiver_participant,
        "created_at": iso(row.created_at),
        "received_at": iso(row.received_at),
        "payload": await _payload(services, row),
        "status": row.status,
        "applied": row.applied,
        "error_message": row.error_message,
        "has_files": row.has_files,
    }


@router.get("/inbox/messages")
async def list_messages(request: Request, status: str | None = None) -> list[dict]:
    services = request.app.state.services
    query = select(InboxMessage).order_by(InboxMessage.created_at.desc())
    if status is not None:
        query = query.where(InboxMessage.status == status)
    async with services.db.session() as session:
        rows = (await session.execute(query)).scalars().all()
    return [await _view(services, row) for row in rows]


@router.get("/inbox/messages/{message_id}")
async def read_message(message_id: str, request: Request) -> dict:
    services = request.app.state.services
    async with services.db.session() as session:
        row = await session.get(InboxMessage, message_id)
    if row is None:
        raise HTTPException(status_code=404, detail="Message not found")
    return await _view(services, row)


@router.post("/inbox/messages/{message_id}/ack", status_code=204)
async def acknowledge(message_id: str, request: Request) -> Response:
    services = request.app.state.services
    async with services.db.session() as session:
        if await session.get(InboxMessage, message_id) is None:
            raise HTTPException(status_code=404, detail="Message not found")
        await session.execute(
            update(InboxMessage)
            .where(InboxMessage.message_id == message_id, InboxMessage.status == "received")
            .values(status="acked", updated_at=now())
            .execution_options(synchronize_session=False)
        )
        await session.commit()
    return Response(status_code=204)
