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
"""One participant's copy of a conversation's state, changed only while holding its row."""

from fastapi.responses import JSONResponse
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app import protocol
from app.db import Conversation, OutboxMessage, insert_for, iso, now
from app.protocol import Decision, Invalid


async def _lock(session: AsyncSession, conversation_id: str) -> Conversation | None:
    query = (
        select(Conversation)
        .where(Conversation.conversation_id == conversation_id)
        .with_for_update()
        .execution_options(populate_existing=True)
    )
    return (await session.execute(query)).scalars().first()


async def _open_and_lock(session: AsyncSession, conversation_id: str, counterpart: str) -> Conversation:
    """Create the conversation unless another message just did, then wait for its row."""
    await session.execute(
        insert_for(session)(Conversation)
        .values(conversation_id=conversation_id, counterpart_participant=counterpart, last_message_at=now())
        .on_conflict_do_nothing(index_elements=["conversation_id"])
    )
    return await _lock(session, conversation_id)


async def locked_decision(
    session: AsyncSession, conversation_id: str, counterpart: str, performative: str, sender: str, outcome: str | None
) -> tuple[Conversation | None, Decision]:
    """Lock the conversation, and decide what this message does to it. The caller's transaction holds the lock."""
    conversation = await _lock(session, conversation_id)
    if conversation is None:
        if performative in protocol.NEEDS_CONVERSATION:
            return None, protocol.refuse("conversation_not_found", "This participant has no such conversation")
        conversation = await _open_and_lock(session, conversation_id, counterpart)
    return conversation, _decide(conversation, counterpart, performative, sender, outcome)


async def locked_for_unapplied(
    session: AsyncSession, conversation_id: str, counterpart: str
) -> tuple[Conversation | None, Decision]:
    """A message its sender didn't apply never moves this copy. It only has to come from the counterpart."""
    conversation = await _lock(session, conversation_id)
    if conversation is not None and conversation.counterpart_participant != counterpart:
        return conversation, _other_counterpart()
    return conversation, protocol.NO_CHANGE


def _other_counterpart() -> Decision:
    return protocol.refuse("counterpart_mismatch", "This conversation is with another participant")


def _decide(
    conversation: Conversation, counterpart: str, performative: str, sender: str, outcome: str | None
) -> Decision:
    if conversation.counterpart_participant != counterpart:
        return _other_counterpart()
    return protocol.decide(conversation.state, conversation.escalated_by, performative, sender, outcome)


async def settle_simultaneous(
    session: AsyncSession, conversation: Conversation, message_id: str, performative: str
) -> Decision | None:
    """Both sides sent the same step before seeing the other's. Both must reach the same answer, with no more messages.

    The sender applied its message, so it had not seen ours. The lower message id wins, on both sides, unless the
    receiver refused ours, in which case the other side never took our step into account.
    """
    closing_a_closed = performative == "close" and conversation.state.startswith(protocol.CLOSED_PREFIX)
    escalating_an_escalated = performative == "escalate" and conversation.state == protocol.ESCALATING
    if not (closing_a_closed or escalating_an_escalated):
        return None
    if conversation.state_message_id is None:
        return None
    ours = await session.get(OutboxMessage, conversation.state_message_id)
    if ours is None or ours.performative != performative:
        return None
    if ours.status == "rejected" or message_id < ours.message_id:
        ours.applied = False
        return Decision(transition=performative)
    return protocol.NO_CHANGE


def apply(
    conversation: Conversation, decision: Decision, message_id: str, sender: str, outcome: str | None
) -> None:
    """Make the decided change on this copy. Only called while holding the row."""
    stamp = now()
    conversation.last_message_at = stamp
    match decision.transition:
        case "close":
            conversation.state = protocol.closed_state(outcome)
            conversation.outcome = outcome
            conversation.closed_at = conversation.closed_at or stamp
        case "escalate":
            conversation.state = protocol.ESCALATING
            conversation.escalated_by = sender
        case "deescalate":
            conversation.state = protocol.OPEN
            conversation.escalated_by = None
        case "reopen":
            conversation.state = protocol.OPEN
            conversation.outcome = None
            conversation.closed_at = None
            conversation.escalated_by = None
        case _:
            return
    conversation.state_message_id = message_id


def invalid_answer(invalid: Invalid, performative: str) -> JSONResponse:
    return JSONResponse(
        status_code=422,
        content={
            "error": "invalid_message",
            "reason": invalid.reason,
            "detail": invalid.detail,
            "performative": performative,
        },
    )


def refused_answer(
    decision: Decision, conversation: Conversation | None, conversation_id: str, message_id: str
) -> JSONResponse:
    return JSONResponse(
        status_code=409,
        content={
            "error": "conversation_state_violation",
            "reason": decision.reason,
            "detail": decision.detail,
            "conversation_id": conversation_id,
            "conversation_state": conversation.state if conversation else None,
            "closed_at": iso(conversation.closed_at) if conversation else None,
            "message_id": message_id,
        },
    )


def refusal_text(reason: str, detail: str) -> str:
    return f"Refused: {reason}. {detail}"
