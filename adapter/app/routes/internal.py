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

"""Routes for peers and the connector. The gateway never forwards agents to these."""

import asyncio
import tempfile
from datetime import datetime
from typing import Annotated

from fastapi import APIRouter, HTTPException, Request, Response
from fastapi.responses import JSONResponse, StreamingResponse
from pydantic import BaseModel, Field
from sqlalchemy import update

from app.auth import DELIVER_CONTENT, READ_PAYLOAD, bearer_token, holds_role, require_transfer_token
from app.conversations import (
    apply,
    invalid_answer,
    is_refused,
    locked_decision,
    locked_for_unapplied,
    refusal_text,
    refused_answer,
    settle_simultaneous,
)
from app.db import InboxMessage, OutboxMessage, add_inbox_row, mark_replied, now
from app.delivery import fetch, note_transfer, set_inbox_in_transfer
from app.limits import BodyTooLarge, arrival_limit, over_limit
from app.protocol import NO_CHANGE, check_validity

router = APIRouter(prefix="/internal")

Identifier = Annotated[str, Field(max_length=512)]


class TransferRequest(BaseModel):
    # A peer chooses this id, and it becomes part of addresses and storage keys here.
    message_id: str = Field(pattern=r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,199}$")
    conversation_id: Identifier
    performative: Identifier = "inform"
    capability: Identifier | None = None
    in_reply_to: Identifier | None = None
    authorization: dict | None = None
    outcome: Identifier | None = None
    sender_participant: Identifier
    receiver_participant: Identifier
    reply_expected: bool = False
    expires_at: datetime | None = None
    response_due_at: datetime | None = None
    asset_id: str = Field(max_length=512)
    provider_dsp_url: str = Field(max_length=2048)
    has_files: bool = False
    sender_applied: bool = True


@router.post("/transfer-request", status_code=202)
async def transfer_request(body: TransferRequest, request: Request):
    services = request.app.state.services
    claims = await services.verifier.claims(bearer_token(request))
    if not holds_role(claims, body.sender_participant):
        raise HTTPException(status_code=403, detail="The token does not belong to the stated sender")
    if body.receiver_participant != services.settings.participant_id:
        raise HTTPException(status_code=403, detail="This message is for a different receiver")
    try:
        await services.registry.receiver(services.settings.participant_id, body.sender_participant)
    except HTTPException as error:
        if error.status_code == 404:
            raise HTTPException(status_code=403, detail="The sender is not registered") from error
        raise

    row = {
        "message_id": body.message_id,
        "conversation_id": body.conversation_id,
        "performative": body.performative,
        "capability": body.capability,
        "in_reply_to": body.in_reply_to,
        "authorization": body.authorization,
        "outcome": body.outcome,
        "sender_participant": body.sender_participant,
        "receiver_participant": body.receiver_participant,
        "reply_expected": body.reply_expected,
        # This adapter's own clock: retention and order must not depend on what a peer states.
        "created_at": now(),
        "expires_at": body.expires_at,
        "response_due_at": body.response_due_at,
        "asset_id": body.asset_id,
        "provider_dsp_url": body.provider_dsp_url,
        "has_files": body.has_files,
    }
    duplicate = {"message_id": body.message_id, "status": "duplicate"}

    invalid = check_validity(body.performative, body.capability, body.in_reply_to, body.authorization, body.outcome)
    if invalid:
        reason = refusal_text(invalid.reason, invalid.detail)
        async with services.db.session() as session:
            added = await add_inbox_row(session, **row, status="error", applied=False, error_message=reason)
            await session.commit()
        return invalid_answer(invalid, body.performative) if added else duplicate

    kept_step = None
    async with services.db.session() as session:
        if body.sender_applied:
            conversation, decision = await locked_decision(
                session,
                body.conversation_id,
                body.sender_participant,
                body.performative,
                body.sender_participant,
                body.outcome,
            )
            if conversation is not None and decision.reason != "counterpart_mismatch":
                settled = await settle_simultaneous(session, conversation, body.message_id, body.performative)
                decision = settled or decision
                kept_step = conversation.state_message_id if settled is NO_CHANGE else None
        else:
            conversation, decision = await locked_for_unapplied(
                session,
                body.conversation_id,
                body.sender_participant,
                body.performative,
                body.sender_participant,
                body.outcome,
            )

        if decision.refused:
            reason = refusal_text(decision.reason, decision.detail)
            added = await add_inbox_row(session, **row, status="error", applied=False, error_message=reason)
            await session.commit()
            return refused_answer(decision, conversation, body.conversation_id, body.message_id) if added else duplicate

        added = await add_inbox_row(session, **row, status="transferring", applied=decision.applied)
        if not added:
            # The same message was notified before. There's nothing more to do, and nothing may change.
            await session.rollback()
            return duplicate
        if conversation is not None:
            apply(conversation, decision, body.message_id, body.sender_participant, body.outcome)
        await mark_replied(
            session, body.in_reply_to, body.conversation_id, (body.sender_participant, body.receiver_participant)
        )
        await session.commit()

    services.spawn(fetch(services, body.message_id, body.sender_participant, body.asset_id, body.provider_dsp_url))
    return {"message_id": body.message_id, "status": "transferring", "kept_step": kept_step}


@router.get("/payload/{message_id}")
async def payload(message_id: str, request: Request) -> Response:
    services = request.app.state.services
    require_transfer_token(request, READ_PAYLOAD, message_id)
    async with services.db.session() as session:
        row = await session.get(OutboxMessage, message_id)
    content = await services.storage.read_stream(row.payload_ref) if row and row.payload_ref else None
    if content is None:
        raise HTTPException(status_code=404, detail="No content for this message")
    # The connector's data plane reads this once a transfer has started.
    services.spawn(note_transfer(services, message_id))
    is_bundle = row.payload_ref.endswith(".zip")
    return StreamingResponse(
        content.chunks,
        media_type="application/zip" if is_bundle else "application/json",
        headers={"Content-Length": str(content.size)},
    )


async def _write_body(request: Request, target, limit: int) -> None:
    if over_limit(request.headers.get("content-length"), limit):
        raise BodyTooLarge
    seen = 0
    async for chunk in request.stream():
        seen += len(chunk)
        if seen > limit:
            raise BodyTooLarge
        await asyncio.to_thread(target.write, chunk)
    await asyncio.to_thread(target.flush)


@router.post("/inbox-receive/{message_id}")
async def inbox_receive(message_id: str, request: Request):
    services = request.app.state.services
    require_transfer_token(request, DELIVER_CONTENT, message_id)
    async with services.db.session() as session:
        row = await session.get(InboxMessage, message_id)
    if row is None:
        raise HTTPException(status_code=404, detail="Unknown message")
    if is_refused(row):
        raise HTTPException(status_code=404, detail="Unknown message")
    if row.status == "acked":
        # The agent has finished with it, and its content may already have been purged.
        return {"message_id": message_id, "status": row.status}
    key = f"files/{message_id}.zip" if row.has_files else f"messages/{message_id}.json"
    limit = arrival_limit(row.has_files, services.settings)
    with tempfile.NamedTemporaryFile(prefix="arrival-") as target:
        try:
            await _write_body(request, target, limit)
        except BodyTooLarge:
            reason = f"The content is larger than this participant accepts, {limit} bytes"
            await set_inbox_in_transfer(services, message_id, status="error", error_message=reason)
            return JSONResponse(status_code=413, content={"detail": reason})
        ref = await services.storage.put_file(key, target.name)
    async with services.db.session() as session:
        await session.execute(
            update(InboxMessage)
            .where(InboxMessage.message_id == message_id, InboxMessage.status != "acked")
            .values(payload_ref=ref, status="received", received_at=now(), error_message=None, updated_at=now())
            .execution_options(synchronize_session=False)
        )
        await session.commit()
    return {"message_id": message_id, "status": "received"}
