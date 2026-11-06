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

"""Background upkeep: removing old content and rows, and keeping the schema in place."""

import asyncio
import logging
from datetime import timedelta

from sqlalchemy import delete, select

from app.db import Conversation, InboxMessage, OutboxMessage, as_utc, now
from app.delivery import Services

log = logging.getLogger("adapter")

FINAL_OUTBOX = ("notified", "error", "rejected")
FINAL_INBOX = ("acked", "error")


async def purge_expired(services: Services) -> None:
    settings = services.settings
    current = now()
    content_limit = current - timedelta(hours=settings.content_retention_hours)
    row_limit = current - timedelta(hours=settings.control_plane_retention_hours)

    async with services.db.session() as session:
        for model, final in ((OutboxMessage, FINAL_OUTBOX), (InboxMessage, FINAL_INBOX)):
            rows = await session.execute(
                select(model).where(model.status.in_(final), model.payload_ref.is_not(None))
            )
            for row in rows.scalars():
                expires = as_utc(row.expires_at)
                due = expires <= current if expires else as_utc(row.created_at) <= content_limit
                if due:
                    await services.storage.delete(row.payload_ref)
                    row.payload_ref = None
            await session.execute(
                delete(model)
                .where(model.status.in_(final), model.created_at <= row_limit)
                .execution_options(synchronize_session=False)
            )
        await session.execute(
            delete(Conversation)
            .where(Conversation.last_message_at <= row_limit)
            .execution_options(synchronize_session=False)
        )
        await session.commit()


async def _forever(what: str, interval: float, work) -> None:
    while True:
        try:
            await work()
        except Exception as error:  # upkeep must outlive a failure, such as a database outage
            log.warning("%s failed, will try again: %s", what, error)
        await asyncio.sleep(interval)


async def schema_loop(services: Services) -> None:
    async def check() -> None:
        missing = await services.db.ensure_schema()
        if missing:
            log.warning("Recreated missing tables: %s", ", ".join(missing))
        await services.storage.ensure_ready()

    await _forever("The schema check", services.settings.schema_check_seconds, check)


async def retention_loop(services: Services) -> None:
    await _forever("Retention", services.settings.retention_interval_seconds, lambda: purge_expired(services))

