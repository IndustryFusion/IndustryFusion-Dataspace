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

from fastapi import APIRouter, HTTPException, Request, Response
from fastapi.responses import JSONResponse, StreamingResponse
from pydantic import BaseModel, Field
from sqlalchemy import update

from app.auth import bearer_token, holds_role
from app.db import InboxMessage, OutboxMessage, add_inbox_row, now, touch_conversation
from app.delivery import fetch, note_transfer, set_inbox_in_transfer
from app.limits import BodyTooLarge, arrival_limit, over_limit

router = APIRouter(prefix="/internal")


class TransferRequest(BaseModel):
    # A peer chooses this id, and it becomes part of addresses and storage keys here.
    message_id: str = Field(pattern=r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,199}$")
    conversation_id: str
    performative: str = "inform"
    capability: str | None = None
    in_reply_to: str | None = None
    authorization: dict | None = None
    outcome: str | None = None
    sender_participant: str
    receiver_participant: str
    reply_expected: bool = False
    expires_at: datetime | None = None
    response_due_at: datetime | None = None
    asset_id: str = Field(max_length=512)
    provider_dsp_url: str = Field(max_length=2048)
    has_files: bool = False


@router.post("/transfer-request", status_code=202)
async def transfer_request(body: TransferRequest, request: Request) -> dict:
    services = request.app.state.services
    claims = await services.verifier.claims(bearer_token(request))
    if not holds_role(claims, body.sender_participant):
        raise HTTPException(status_code=403, detail="The token does not belong to the stated sender")
    if body.receiver_participant != services.settings.participant_id:
        raise HTTPException(status_code=403, detail="This message is for a different receiver")

    async with services.db.session() as session:
        added = await add_inbox_row(
            session,
            message_id=body.message_id,
            conversation_id=body.conversation_id,
            performative=body.performative,
            capability=body.capability,
            in_reply_to=body.in_reply_to,
            authorization=body.authorization,
            outcome=body.outcome,
            sender_participant=body.sender_participant,
            receiver_participant=body.receiver_participant,
            reply_expected=body.reply_expected,
            # This adapter's own clock: retention and order must not depend on what a peer states.
            created_at=now(),
            expires_at=body.expires_at,
            response_due_at=body.response_due_at,
            status="transferring",
            applied=True,
            asset_id=body.asset_id,
            provider_dsp_url=body.provider_dsp_url,
            has_files=body.has_files,
        )
        if not added:
            # The same message was notified before. There's nothing more to do.
            return {"message_id": body.message_id, "status": "duplicate"}
        await touch_conversation(session, body.conversation_id, body.sender_participant)
        await session.commit()

    services.spawn(fetch(services, body.message_id, body.sender_participant, body.asset_id, body.provider_dsp_url))
    return {"message_id": body.message_id, "status": "transferring"}


@router.get("/payload/{message_id}")
async def payload(message_id: str, request: Request) -> Response:
    services = request.app.state.services
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
    async with services.db.session() as session:
        row = await session.get(InboxMessage, message_id)
    if row is None:
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
