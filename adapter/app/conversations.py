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

# A step with one of these never reached the other side's copy, as far as this side knows.
FAILED = ("error", "rejected")
REFUSED = "Refused: "


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


async def _locked(
    session: AsyncSession, conversation_id: str, counterpart: str, performative: str
) -> tuple[Conversation | None, Decision | None]:
    """Lock the conversation, opening it if this message can. A decision here is a refusal."""
    conversation = await _lock(session, conversation_id)
    if conversation is None:
        if performative in protocol.NEEDS_CONVERSATION:
            return None, protocol.refuse("conversation_not_found", "This participant has no such conversation")
        conversation = await _open_and_lock(session, conversation_id, counterpart)
    if conversation.counterpart_participant != counterpart:
        return conversation, _other_counterpart()
    return conversation, None


def _other_counterpart() -> Decision:
    return protocol.refuse("counterpart_mismatch", "This conversation is with another participant")


async def _step_row(session: AsyncSession, message_id: str) -> OutboxMessage | InboxMessage | None:
    return await session.get(OutboxMessage, message_id) or await session.get(InboxMessage, message_id)


async def _undelivered_step(
    session: AsyncSession, conversation: Conversation, performative: str
) -> OutboxMessage | None:
    """This side's latest step, if the other side refused it or never answered, and this message repeats it."""
    if not conversation.state_message_id:
        return None
    latest = await session.get(OutboxMessage, conversation.state_message_id)
    if latest is not None and latest.performative == performative and latest.status in FAILED:
        return latest
    return None


async def decide_to_send(
    session: AsyncSession, conversation_id: str, counterpart: str, performative: str, sender: str, outcome: str | None
) -> tuple[Conversation | None, Decision, str | None]:
    """What this side's message does to its copy, and which step it is based on. The transaction holds the lock."""
    conversation, refusal = await _locked(session, conversation_id, counterpart, performative)
    if refusal:
        return conversation, refusal, None
    failed = await _undelivered_step(session, conversation, performative)
    if failed is not None:
        failed.applied = False
        return conversation, Decision(transition=performative), failed.based_on
    decision = protocol.decide(conversation.state, conversation.escalated_by, performative, sender, outcome)
    return conversation, decision, conversation.state_message_id if decision.transition else None


async def refresh_before_delivery(session: AsyncSession, message: dict) -> dict:
    """Bring a step up to date when its turn comes. Earlier deliveries and the other side may have changed things."""
    conversation = await _lock(session, message["conversation_id"])
    row = await session.get(OutboxMessage, message["message_id"])
    if conversation is None or row is None:
        return message
    if not row.applied:
        failed = await _undelivered_step(session, conversation, row.performative)
        if failed is not None and failed.message_id != row.message_id:
            failed.applied = False
            row.applied = True
            row.based_on = failed.based_on
            decision = Decision(transition=row.performative)
            apply(conversation, decision, row.message_id, row.sender_participant, row.outcome)
            await session.commit()
    return {**message, "sender_applied": row.applied, "based_on": row.based_on}


async def decide_unapplied(
    session: AsyncSession, conversation_id: str, counterpart: str, performative: str, sender: str, outcome: str | None
) -> tuple[Conversation | None, Decision]:
    """A message its sender didn't apply never moves this copy. It doesn't get past the rules either."""
    conversation = await _lock(session, conversation_id)
    if conversation is None:
        return None, protocol.refuse("conversation_not_found", "This participant has no such conversation")
    if conversation.counterpart_participant != counterpart:
        return conversation, _other_counterpart()
    decision = protocol.decide(conversation.state, conversation.escalated_by, performative, sender, outcome)
    return conversation, decision if decision.refused else protocol.NO_CHANGE


async def decide_incoming(
    session: AsyncSession,
    conversation_id: str,
    sender: str,
    message_id: str,
    performative: str,
    outcome: str | None,
    based_on: str | None,
    names_a_base: bool,
) -> tuple[Conversation | None, Decision]:
    """What the other side's message does to this copy. The transaction holds the lock."""
    conversation, refusal = await _locked(session, conversation_id, sender, performative)
    if refusal:
        return conversation, refusal
    rules = protocol.decide(conversation.state, conversation.escalated_by, performative, sender, outcome)
    if performative not in protocol.STEPS or not names_a_base:
        return conversation, rules
    head = conversation.state_message_id
    if message_id == head:
        return conversation, Decision()  # This side took it from the sender's earlier answer.
    if based_on == head:
        return conversation, rules
    base = await _step_row(session, based_on) if based_on else None
    if isinstance(base, InboxMessage) and not base.applied:
        return conversation, protocol.NO_CHANGE  # It continues a branch that lost.

    steps = await _steps_since(session, conversation, based_on, message_id)
    if steps is ALREADY_ON_THE_CHAIN:
        return conversation, Decision()
    if steps is None:
        return conversation, rules  # The base isn't known here, as its notification failed.
    first = steps[-1]
    if isinstance(first, InboxMessage) or first.status == "notified":
        # The sender had this step already, or has answered for it. So this can't be crossing it.
        return conversation, protocol.NO_CHANGE
    if first.status in FAILED or message_id < first.message_id:
        for step in steps:
            step.applied = False
        conversation.escalated_by = await _escalator_at(session, based_on)
        return conversation, Decision(transition=performative)
    return conversation, protocol.NO_CHANGE


ALREADY_ON_THE_CHAIN = object()


async def _steps_since(session: AsyncSession, conversation: Conversation, based_on: str | None, message_id: str):
    """This copy's steps since a base, latest first, or None if the base isn't on this copy's chain."""
    steps = []
    seen = set()
    cursor = conversation.state_message_id
    while cursor != based_on:
        if cursor == message_id:
            return ALREADY_ON_THE_CHAIN
        if cursor is None or cursor in seen:
            return None
        seen.add(cursor)
        step = await _step_row(session, cursor)
        if step is None:
            return None
        steps.append(step)
        cursor = step.based_on
    return steps


async def _escalator_at(session: AsyncSession, step_id: str | None) -> str | None:
    """Who had escalated the conversation as of a step, so a loser's own escalation leaves no trace."""
    seen = set()
    while step_id and step_id not in seen:
        seen.add(step_id)
        step = await _step_row(session, step_id)
        if step is None or step.performative in {"deescalate", "reopen"}:
            return None
        if step.performative == "escalate":
            return step.sender_participant
        step_id = step.based_on
    return None


def is_refused(row: InboxMessage) -> bool:
    """A received message the rules refused, as opposed to one whose transfer failed."""
    return row.status == "error" and not row.applied and (row.error_message or "").startswith(REFUSED)


def copy_for_the_sender(conversation: Conversation | None, applied: bool) -> dict:
    """Added to the answer to a notification, so that the sender can compare, and doesn't depend on a later message."""
    return {
        "applied": applied,
        "conversation_state": conversation.state if conversation else None,
        "outcome": conversation.outcome if conversation else None,
        "escalated_by": conversation.escalated_by if conversation else None,
        "state_message_id": conversation.state_message_id if conversation else None,
    }


def _valid_copy(answer: dict) -> bool:
    state, outcome = answer.get("conversation_state"), answer.get("outcome")
    if state == protocol.OPEN:
        return outcome is None
    if state == protocol.ESCALATING:
        return outcome is None and isinstance(answer.get("escalated_by"), str)
    return outcome in protocol.OUTCOMES and state == protocol.closed_state(outcome)


async def compare_with_answer(session: AsyncSession, message: dict, answer: dict) -> None:
    """After a step's notification is answered, take the other side's copy if it voided this side's step."""
    if message["performative"] not in protocol.STEPS or not answer.get("state_message_id"):
        return
    conversation = await _lock(session, message["conversation_id"])
    row = await session.get(OutboxMessage, message["message_id"])
    if conversation is None or row is None or not _valid_copy(answer):
        return
    theirs = answer["state_message_id"]
    if not message.get("sender_applied", True):
        if answer["conversation_state"] != conversation.state:
            row.error_message = f"The receiver's copy of the conversation is {answer['conversation_state']}"
            await session.commit()
        return
    voided_here = theirs == row.message_id and not row.applied
    voided_there = theirs != row.message_id and answer.get("applied") is False
    if theirs == conversation.state_message_id or not (voided_here or voided_there):
        return

    cursor, seen = conversation.state_message_id, set()
    while cursor and cursor not in seen:
        seen.add(cursor)
        step = await session.get(OutboxMessage, cursor)
        if step is None:
            break
        step.applied = False
        cursor = step.based_on if cursor != row.message_id else None
    taken = await _step_row(session, theirs)
    if taken is not None:
        taken.applied = True
        if isinstance(taken, OutboxMessage) and taken.status in FAILED:
            taken.status, taken.error_message = "notified", None
    is_closed = answer["conversation_state"].startswith(protocol.CLOSED_PREFIX)
    conversation.state = answer["conversation_state"]
    conversation.outcome = answer.get("outcome")
    conversation.escalated_by = answer.get("escalated_by")
    conversation.closed_at = (conversation.closed_at or now()) if is_closed else None
    conversation.state_message_id = theirs
    conversation.last_message_at = now()
    await session.commit()


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
            # Winning over a crossing close can make this follow a closed state, so nothing of that stays.
            conversation.state = protocol.ESCALATING
            conversation.outcome = None
            conversation.closed_at = None
            conversation.escalated_by = sender
        case "deescalate" | "reopen":
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
