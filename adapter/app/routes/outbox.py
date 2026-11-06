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

import asyncio
import json
import logging
import os
import tempfile
import uuid
from datetime import datetime
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field, ValidationError
from starlette.datastructures import UploadFile
from starlette.exceptions import HTTPException as StarletteHTTPException
from starlette.formparsers import MultiPartParser

from app.auth import require_participant
from app.bundle import write_bundle
from app.conversations import apply, invalid_answer, locked_decision, refusal_text, refused_answer
from app.db import Conversation, OutboxMessage, iso
from app.delivery import deliver
from app.protocol import check_validity

log = logging.getLogger("adapter")

router = APIRouter(dependencies=[Depends(require_participant)])

MOST_FILES = 256
MOST_FIELDS = 16
LONGEST_FIELD_BYTES = 64 * 1024
# A file part leaves memory for disk after this. There is no setting for it on the form reader.
MultiPartParser.spool_max_size = 64 * 1024

Identifier = Annotated[str, Field(max_length=512)]


class ContentRef(BaseModel):
    asset_id: str
    dsp_url: str


class OutgoingMessage(BaseModel):
    receiver_participant: Identifier
    performative: Identifier = "inform"
    capability: Identifier | None = None
    in_reply_to: Identifier | None = None
    authorization: dict | None = None
    outcome: Identifier | None = None
    conversation_id: Identifier | None = None
    payload: dict | None = None
    content_ref: ContentRef | None = None
    reply_expected: bool = False
    expires_at: datetime | None = None
    response_due_at: datetime | None = None


async def conversation_state(session, conversation_id: str) -> str | None:
    conversation = await session.get(Conversation, conversation_id)
    return conversation.state if conversation else None


def _invalid(body: "OutgoingMessage") -> JSONResponse | None:
    invalid = check_validity(body.performative, body.capability, body.in_reply_to, body.authorization, body.outcome)
    return invalid_answer(invalid, body.performative) if invalid else None


def _stored_json(payload: dict | None) -> bytes:
    """Never larger than the body that carried it. A lone surrogate is written back as the escape it came as."""
    return json.dumps(payload, ensure_ascii=False).encode("utf-8", "backslashreplace")


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

    refusal = _invalid(body)
    if refusal:
        return refusal

    peer = await services.registry.receiver(own_id, body.receiver_participant)

    message_id = str(uuid.uuid4())
    payload_ref = None
    if body.content_ref is None:
        try:
            payload_ref = await services.storage.put(f"messages/{message_id}.json", _stored_json(body.payload))
        except Exception as error:
            raise HTTPException(status_code=503, detail="Object storage is unavailable") from error
    return await _accept(services, body, message_id, payload_ref, peer, has_files=False)


def _read_form_fields(form) -> tuple[OutgoingMessage, list[UploadFile]]:
    """The fields of a file upload. They aren't declared on the route, so that the token is checked first."""
    uploads = form.getlist("files")
    if not uploads or not all(isinstance(upload, UploadFile) for upload in uploads):
        raise HTTPException(status_code=422, detail="At least one file is required, as the form field files")
    fields = {}
    for name in ("receiver_participant", "performative", "capability", "in_reply_to", "conversation_id"):
        value = form.get(name)
        if isinstance(value, str) and value:
            fields[name] = value
    try:
        return OutgoingMessage(**fields), uploads
    except ValidationError as error:
        raise HTTPException(status_code=422, detail="receiver_participant is required") from error


@router.post("/outbox/files", status_code=202)
async def send_files(request: Request):
    services = request.app.state.services
    own_id = services.settings.participant_id
    try:
        form = await request.form(max_files=MOST_FILES, max_fields=MOST_FIELDS, max_part_size=LONGEST_FIELD_BYTES)
    except StarletteHTTPException as error:
        raise HTTPException(status_code=422, detail=f"The form can't be read: {error.detail}") from error
    try:
        body, uploads = _read_form_fields(form)
        refusal = _invalid(body)
        if refusal:
            return refusal
        peer = await services.registry.receiver(own_id, body.receiver_participant)
        message_id = str(uuid.uuid4())
        with tempfile.TemporaryDirectory(prefix="bundle-") as folder:
            path = os.path.join(folder, "bundle.zip")
            parts = [(upload.filename or "", upload.file) for upload in uploads]
            await asyncio.to_thread(write_bundle, parts, path)
            try:
                payload_ref = await services.storage.put_file(f"files/{message_id}.zip", path)
            except Exception as error:
                raise HTTPException(status_code=503, detail="Object storage is unavailable") from error
    finally:
        await form.close()
    return await _accept(services, body, message_id, payload_ref, peer, has_files=True)


async def _accept(
    services, body: OutgoingMessage, message_id: str, payload_ref: str | None, peer: dict, has_files: bool
):
    """Decide what a message does to its conversation, record that, and start delivering it."""
    own_id = services.settings.participant_id
    conversation_id = body.conversation_id or str(uuid.uuid4())
    fields = {
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
    }
    content_ref = body.content_ref.model_dump() if body.content_ref else None
    gate = None
    try:
        async with services.db.session() as session:
            conversation, decision = await locked_decision(
                session, conversation_id, body.receiver_participant, body.performative, own_id, body.outcome
            )
            if decision.refused:
                session.add(
                    OutboxMessage(
                        **fields,
                        content_ref=content_ref,
                        expires_at=body.expires_at,
                        response_due_at=body.response_due_at,
                        status="rejected",
                        applied=False,
                        error_message=refusal_text(decision.reason, decision.detail),
                    )
                )
                await session.commit()
                await _remove_content(services, payload_ref, message_id)
                return refused_answer(decision, conversation, conversation_id, message_id)

            apply(conversation, decision, message_id, own_id, body.outcome)
            session.add(
                OutboxMessage(
                    **fields,
                    payload_ref=payload_ref,
                    content_ref=content_ref,
                    expires_at=body.expires_at,
                    response_due_at=body.response_due_at,
                    status="pending",
                    applied=decision.applied,
                )
            )
            state = conversation.state
            notification = {
                **fields,
                "expires_at": iso(body.expires_at),
                "response_due_at": iso(body.response_due_at),
                "content_ref": content_ref,
                "has_files": has_files,
                "sender_applied": decision.applied,
            }
            gate = services.deliver_in_order(conversation_id, deliver(services, notification, peer))
            await session.commit()
    except Exception:
        if gate is not None:
            gate.set_result(False)
        # Without a row, retention could never remove what was just uploaded.
        await _remove_content(services, payload_ref, message_id)
        raise
    gate.set_result(True)
    return {"message_id": message_id, "status": "pending", "applied": decision.applied, "conversation_state": state}


async def _remove_content(services, payload_ref: str | None, message_id: str) -> None:
    if payload_ref:
        try:
            await services.storage.delete(payload_ref)
        except Exception as error:
            log.warning("Could not remove the content of message %s: %s", message_id, error)


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
