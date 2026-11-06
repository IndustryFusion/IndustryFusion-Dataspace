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
"""What a participant offers, and who may access it. This is advisory: nothing in the message path reads it."""

import uuid
from dataclasses import dataclass

from fastapi import HTTPException
from sqlalchemy import delete, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import CapabilityApproval, CapabilityPolicy, insert_for, iso, now

AUTO, ON_REQUEST = "auto", "on-request"
PENDING, APPROVED, DENIED = "pending", "approved", "denied"
FACTORY_OWNER, MACHINE_BUILDER = "factory_owner", "machine_builder"
ATTEMPTS_AT_A_REQUEST = 5


@dataclass(frozen=True)
class Capability:
    provider_role: str
    default_policy: str
    label: str
    what_it_covers: str
    data_classification: str

    def describe(self, default_policy: str) -> str:
        """Follows the effective default, as a default can be changed."""
        return f"{self.what_it_covers} {AVAILABILITY[default_policy]}"


AVAILABILITY = {AUTO: "Available by default.", ON_REQUEST: "Available once approved."}

CATALOGUE = {
    "twin:direct": Capability(
        FACTORY_OWNER,
        AUTO,
        "Machine twin",
        "Current state and sensor values of the machine in question.",
        "operational",
    ),
    "twin:adjacents": Capability(
        FACTORY_OWNER,
        ON_REQUEST,
        "Neighbouring machines",
        "State of machines connected to the one in question, for looking at a whole line.",
        "operational",
    ),
    "twin:history": Capability(
        FACTORY_OWNER,
        ON_REQUEST,
        "Machine history",
        "Past values and events of the machine, for comparing runs over time.",
        "operational",
    ),
    "mb:confidential": Capability(
        MACHINE_BUILDER,
        AUTO,
        "Machine builder documents",
        "Service bulletins and maintenance procedures not published elsewhere.",
        "confidential",
    ),
}


def role_name(participant_type: str) -> str:
    """The bare role, from a bare name, a prefixed name or a full IRI."""
    return participant_type.rsplit("#", 1)[-1].removeprefix("ds:")


def offered_by(participant_type: str) -> dict[str, Capability]:
    role = role_name(participant_type)
    return {name: capability for name, capability in CATALOGUE.items() if capability.provider_role == role}


def require_offered(participant_type: str, capability: str) -> Capability:
    offered = offered_by(participant_type).get(capability)
    if offered is None:
        raise HTTPException(status_code=404, detail=f"This participant does not offer {capability}")
    return offered


def approval_view(row: CapabilityApproval) -> dict:
    return {
        "id": row.id,
        "consumer_id": row.consumer_id,
        "capability": row.capability,
        "status": row.status,
        "conversation_id": row.conversation_id,
        "purpose": row.purpose,
        "note": row.note,
        "decision_note": row.decision_note,
        "requested_at": iso(row.requested_at),
        "resolved_at": iso(row.resolved_at),
    }


async def defaults(session: AsyncSession, participant_type: str) -> dict[str, str]:
    """Each offered capability's default, with any change this participant has made."""
    rows = (await session.execute(select(CapabilityPolicy))).scalars()
    changed = {row.capability: row.default_policy for row in rows}
    offered = offered_by(participant_type)
    return {name: changed.get(name, capability.default_policy) for name, capability in offered.items()}


def offered_view(name: str, capability: Capability, default: str) -> dict:
    return {
        "capability": name,
        "label": capability.label,
        "description": capability.describe(default),
        "data_classification": capability.data_classification,
        "default_policy": default,
    }


def access_entry(offered: dict, approval: dict | None) -> dict:
    """One capability's effective status for one consumer."""
    default = offered["default_policy"]
    return {
        "capability": offered["capability"],
        "label": offered["label"],
        "description": offered["description"],
        "data_classification": offered["data_classification"],
        "status": approval["status"] if approval else default,
        "source": "explicit" if approval else "default",
        "decision_note": approval["decision_note"] if approval else None,
    }


async def approval_for(session: AsyncSession, consumer: str, capability: str) -> CapabilityApproval | None:
    query = (
        select(CapabilityApproval)
        .where(CapabilityApproval.consumer_id == consumer, CapabilityApproval.capability == capability)
        .execution_options(populate_existing=True)
    )
    return (await session.execute(query)).scalars().first()


async def record_request(
    session: AsyncSession,
    participant_type: str,
    consumer: str,
    capability: str,
    conversation_id: str | None,
    purpose: str | None,
    note: str | None,
) -> dict:
    """Store a request, unless one exists or none is needed. A repeat never changes what is stored."""
    require_offered(participant_type, capability)
    # A reset can remove what a concurrent request stored, between this one's two looks at the row.
    for _ in range(ATTEMPTS_AT_A_REQUEST):
        existing = await approval_for(session, consumer, capability)
        if existing is not None:
            return approval_view(existing)
        if (await defaults(session, participant_type))[capability] == AUTO:
            # A pending row would become the effective status, so asking would reduce the consumer's access.
            return {
                "id": None,
                "consumer_id": consumer,
                "capability": capability,
                "status": AUTO,
                "conversation_id": conversation_id,
                "purpose": purpose,
                "note": note,
                "decision_note": None,
                "requested_at": None,
                "resolved_at": None,
            }
        inserted = await session.execute(
            insert_for(session)(CapabilityApproval)
            .values(
                id=str(uuid.uuid4()),
                consumer_id=consumer,
                capability=capability,
                status=PENDING,
                conversation_id=conversation_id,
                purpose=purpose,
                note=note,
                requested_at=now(),
            )
            .on_conflict_do_nothing(index_elements=["consumer_id", "capability"])
            .returning(CapabilityApproval)
        )
        row = inserted.scalars().first()
        await session.commit()
        if row is not None:
            return approval_view(row)
    raise HTTPException(status_code=503, detail="The request could not be stored. Try again")


async def resolve(session: AsyncSession, approval_id: str, status: str, note: str | None) -> dict:
    """Decide a pending request. Of any number of decisions at once, one changes the row."""
    changed = await session.execute(
        update(CapabilityApproval)
        .where(CapabilityApproval.id == approval_id, CapabilityApproval.status == PENDING)
        .values(status=status, decision_note=note, resolved_at=now())
        .returning(CapabilityApproval.id)
        .execution_options(synchronize_session=False)
    )
    resolved = changed.first() is not None
    await session.commit()
    query = (
        select(CapabilityApproval)
        .where(CapabilityApproval.id == approval_id)
        .execution_options(populate_existing=True)
    )
    row = (await session.execute(query)).scalars().first()
    if row is None:
        raise HTTPException(status_code=404, detail="Request not found")
    if not resolved:
        raise HTTPException(status_code=409, detail=f"This request is already {row.status}")
    return approval_view(row)


async def set_access(session: AsyncSession, consumer: str, capability: str, status: str, note: str | None) -> dict:
    """Record a decision for a consumer, whatever was there before."""
    stamp = now()
    decision = {"status": status, "decision_note": note, "resolved_at": stamp}
    stored = await session.execute(
        insert_for(session)(CapabilityApproval)
        .values(id=str(uuid.uuid4()), consumer_id=consumer, capability=capability, requested_at=stamp, **decision)
        .on_conflict_do_update(index_elements=["consumer_id", "capability"], set_=decision)
        .returning(CapabilityApproval)
        .execution_options(populate_existing=True)
    )
    row = stored.scalars().one()
    await session.commit()
    return approval_view(row)


async def reset(session: AsyncSession, participant_type: str, consumer: str, capability: str) -> dict:
    """Go back to the default. Safe to repeat."""
    await session.execute(
        delete(CapabilityApproval)
        .where(CapabilityApproval.consumer_id == consumer, CapabilityApproval.capability == capability)
        .execution_options(synchronize_session=False)
    )
    await session.commit()
    default = (await defaults(session, participant_type))[capability]
    return {"consumer_id": consumer, "capability": capability, "status": default, "source": "default"}


async def change_default(session: AsyncSession, capability: str, default_policy: str) -> None:
    values = {"default_policy": default_policy, "updated_at": now()}
    await session.execute(
        insert_for(session)(CapabilityPolicy)
        .values(capability=capability, **values)
        .on_conflict_do_update(index_elements=["capability"], set_=values)
    )
    await session.commit()
