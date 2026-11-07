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

"""Database tables. Rows hold metadata and a payload reference, never the content."""

from datetime import UTC, datetime

from sqlalchemy import JSON, Boolean, DateTime, String, Text, UniqueConstraint, inspect, text
from sqlalchemy.dialects.postgresql import insert as postgres_insert
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


def now() -> datetime:
    return datetime.now(UTC)


def as_utc(value: datetime | None) -> datetime | None:
    if value is None:
        return None
    return value if value.tzinfo else value.replace(tzinfo=UTC)


def iso(value: datetime | None) -> str | None:
    value = as_utc(value)
    return value.isoformat() if value else None


class Base(DeclarativeBase):
    pass


class MessageColumns:
    message_id: Mapped[str] = mapped_column(String, primary_key=True)
    conversation_id: Mapped[str] = mapped_column(String, index=True)
    performative: Mapped[str] = mapped_column(String)
    capability: Mapped[str | None] = mapped_column(String)
    in_reply_to: Mapped[str | None] = mapped_column(String)
    authorization: Mapped[dict | None] = mapped_column(JSON)
    outcome: Mapped[str | None] = mapped_column(String)
    sender_participant: Mapped[str] = mapped_column(String)
    receiver_participant: Mapped[str] = mapped_column(String)
    payload_ref: Mapped[str | None] = mapped_column(String)
    reply_expected: Mapped[bool] = mapped_column(Boolean, default=False)
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    response_due_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    status: Mapped[str] = mapped_column(String, index=True)
    applied: Mapped[bool] = mapped_column(Boolean, default=True)
    error_message: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)


class OutboxMessage(MessageColumns, Base):
    __tablename__ = "outbox_messages"

    content_ref: Mapped[dict | None] = mapped_column(JSON)
    edc_transfer_id: Mapped[str | None] = mapped_column(String)


class InboxMessage(MessageColumns, Base):
    __tablename__ = "inbox_messages"

    received_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    has_files: Mapped[bool] = mapped_column(Boolean, default=False)
    asset_id: Mapped[str | None] = mapped_column(String)
    provider_dsp_url: Mapped[str | None] = mapped_column(String)


class Conversation(Base):
    __tablename__ = "conversations"

    conversation_id: Mapped[str] = mapped_column(String, primary_key=True)
    state: Mapped[str] = mapped_column(String, default="OPEN")
    outcome: Mapped[str | None] = mapped_column(String)
    counterpart_participant: Mapped[str] = mapped_column(String)
    opened_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)
    closed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_message_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)
    escalated_by: Mapped[str | None] = mapped_column(String)
    # The message that made the state what it is. Used to settle simultaneous steps.
    state_message_id: Mapped[str | None] = mapped_column(String)
    # The one lower id that the other side said it kept, in answer to this side's step. It can take that step, once.
    awaited_step: Mapped[str | None] = mapped_column(String)


class CapabilityPolicy(Base):
    """A default a participant has changed. Capabilities without a row keep the catalogue's default."""

    __tablename__ = "capability_policies"

    capability: Mapped[str] = mapped_column(String, primary_key=True)
    default_policy: Mapped[str] = mapped_column(String)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)


class CapabilityApproval(Base):
    """One consumer's request or decision for one capability."""

    __tablename__ = "capability_approvals"
    __table_args__ = (UniqueConstraint("consumer_id", "capability", name="one_approval_per_consumer"),)

    id: Mapped[str] = mapped_column(String, primary_key=True)
    consumer_id: Mapped[str] = mapped_column(String, index=True)
    capability: Mapped[str] = mapped_column(String)
    status: Mapped[str] = mapped_column(String, index=True)
    conversation_id: Mapped[str | None] = mapped_column(String)
    purpose: Mapped[str | None] = mapped_column(Text)
    note: Mapped[str | None] = mapped_column(Text)
    decision_note: Mapped[str | None] = mapped_column(Text)
    requested_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


def insert_for(session: AsyncSession):
    """The insert that supports ON CONFLICT on this database. Production uses PostgreSQL, unit tests SQLite."""
    return postgres_insert if session.get_bind().dialect.name == "postgresql" else sqlite_insert


async def add_inbox_row(session: AsyncSession, **values) -> bool:
    """Add an inbox row, and return False if this message id already has one."""
    statement = (
        insert_for(session)(InboxMessage)
        .values(**values)
        .on_conflict_do_nothing(index_elements=["message_id"])
        .returning(InboxMessage.message_id)
    )
    return (await session.execute(statement)).first() is not None


class Database:
    def __init__(self, url: str) -> None:
        self.engine: AsyncEngine = create_async_engine(url, pool_pre_ping=True)
        self.session = async_sessionmaker(self.engine, class_=AsyncSession, expire_on_commit=False)

    async def ensure_schema(self) -> list[str]:
        """Create whatever tables are missing, and return their names. Older tables gain newer nullable columns."""

        def create(connection) -> list[str]:
            inspector = inspect(connection)
            existing = set(inspector.get_table_names())
            missing = [name for name in Base.metadata.tables if name not in existing]
            if missing:
                Base.metadata.create_all(connection)
            for name in existing & set(Base.metadata.tables):
                present = {column["name"] for column in inspector.get_columns(name)}
                for column in Base.metadata.tables[name].columns:
                    if column.name not in present and column.nullable:
                        kind = column.type.compile(connection.dialect)
                        connection.execute(text(f'ALTER TABLE "{name}" ADD COLUMN "{column.name}" {kind}'))
            return missing

        async with self.engine.begin() as connection:
            return await connection.run_sync(create)

    async def close(self) -> None:
        await self.engine.dispose()
