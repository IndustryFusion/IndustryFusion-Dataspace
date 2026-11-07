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
from app.db import Conversation, InboxMessage, OutboxMessage, insert_for, iso, now
from app.protocol import Decision, Invalid

REFUSED = "Refused: "
# Only these settle when both sides send one before seeing the other's.
SIMULTANEOUS = {"close", "escalate"}
# A step of this side is on its way only while its notification hasn't been answered. One that failed isn't.
ON_ITS_WAY = {"pending", "registered"}


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
    session: AsyncSession, conversation_id: str, counterpart: str, performative: str, sender: str, outcome: str | None
) -> tuple[Conversation | None, Decision]:
    """A message its sender didn't apply never moves this copy. It doesn't get past the rules either."""
    conversation = await _lock(session, conversation_id)
    if conversation is None:
        return None, protocol.refuse("conversation_not_found", "This participant has no such conversation")
    decision = _decide(conversation, counterpart, performative, sender, outcome)
    return conversation, decision if decision.refused else protocol.NO_CHANGE


def _other_counterpart() -> Decision:
    return protocol.refuse("counterpart_mismatch", "This conversation is with another participant")


def _decide(
    conversation: Conversation, counterpart: str, performative: str, sender: str, outcome: str | None
) -> Decision:
    if conversation.counterpart_participant != counterpart:
        return _other_counterpart()
    return protocol.decide(conversation.state, conversation.escalated_by, performative, sender, outcome)


async def repeats_a_failed_step(
    session: AsyncSession, conversation: Conversation | None, performative: str, outcome: str | None
) -> bool:
    """Whether this message sends again a step of this side that never reached the other side's copy."""
    if conversation is None or performative not in protocol.STEPS or not conversation.state_message_id:
        return False
    latest = await session.get(OutboxMessage, conversation.state_message_id)
    return (
        latest is not None
        and latest.performative == performative
        and latest.outcome == outcome
        and latest.status in ("error", "rejected")
    )


async def settle_simultaneous(
    session: AsyncSession, conversation: Conversation, message_id: str, performative: str
) -> Decision | None:
    """Both sides sent the same step before seeing the other's. Both must reach the same answer, with no more messages.

    The lower message id wins, on both sides. It can only happen while this side's step is on its way, or for the one
    step the other side named in answering it. After that, nothing a peer states changes the state, and the ordinary
    rules decide.
    """
    if performative not in SIMULTANEOUS or not conversation.state_message_id:
        return None
    ours = await session.get(OutboxMessage, conversation.state_message_id)
    if ours is None or ours.performative != performative:
        return None
    if conversation.awaited_step == message_id:
        ours.applied = False
        return Decision(transition=performative)
    if ours.status not in ON_ITS_WAY:
        return None
    if message_id < ours.message_id:
        ours.applied = False
        return Decision(transition=performative)
    return protocol.NO_CHANGE


async def note_the_answer(session: AsyncSession, message: dict, answer: object) -> None:
    """The other side says it kept a lower id of its own, which is on its way here.

    It is only a claim, so nothing changes yet. That one id, when it arrives, can take this side's step, once.
    """
    kept = answer.get("kept_step") if isinstance(answer, dict) else None
    if not isinstance(kept, str) or kept >= message["message_id"]:
        return
    conversation = await _lock(session, message["conversation_id"])
    if conversation is not None and conversation.state_message_id == message["message_id"]:
        conversation.awaited_step = kept
        await session.commit()


def is_refused(row: InboxMessage) -> bool:
    """A received message the rules refused, as opposed to one whose transfer failed."""
    return row.status == "error" and not row.applied and (row.error_message or "").startswith(REFUSED)


def apply(conversation: Conversation, decision: Decision, message_id: str, sender: str, outcome: str | None) -> None:
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
    conversation.awaited_step = None


def invalid_answer(invalid: Invalid, performative: str) -> JSONResponse:
    return JSONResponse(
        status_code=422,
        content={
            "error": "invalid_message",
            "reason": invalid.reason,
            "detail": invalid.detail,
            "performative": performative[:100],
        },
    )


def refused_answer(
    decision: Decision, conversation: Conversation | None, conversation_id: str, message_id: str
) -> JSONResponse:
    # A probe with someone else's conversation id learns nothing about that conversation.
    if decision.reason == "counterpart_mismatch":
        conversation = None
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
    return f"{REFUSED}{reason}. {detail}"
