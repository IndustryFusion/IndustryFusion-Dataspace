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

import asyncio
import time
from dataclasses import replace
from datetime import timedelta

from conftest import auth
from sqlalchemy import inspect, text, update
from test_inbox import arrive, read

from app.db import Conversation, InboxMessage, OutboxMessage, now
from app.retention import purge_expired, retention_loop, schema_loop


def age(harness, model, message_id: str, **values) -> None:
    async def change() -> None:
        async with harness.services.db.session() as session:
            await session.execute(
                update(model)
                .where(model.message_id == message_id)
                .values(**values)
                .execution_options(synchronize_session=False)
            )
            await session.commit()

    harness.run(change)


def purge(harness) -> None:
    harness.run(purge_expired, harness.services)


def outbox_row(harness, message_id: str) -> OutboxMessage | None:
    async def get():
        async with harness.services.db.session() as session:
            return await session.get(OutboxMessage, message_id)

    return harness.run(get)


def test_inbox_content_is_purged_after_the_period(harness):
    arrive(harness)
    harness.client.post("/inbox/messages/m1/ack", headers=auth())
    age(harness, InboxMessage, "m1", created_at=now() - timedelta(hours=25))
    purge(harness)
    message = read(harness)
    assert message["payload"] is None
    assert message["status"] == "acked"
    assert harness.storage.objects == {}


def test_inbox_content_inside_the_period_is_kept(harness):
    arrive(harness)
    harness.client.post("/inbox/messages/m1/ack", headers=auth())
    age(harness, InboxMessage, "m1", created_at=now() - timedelta(hours=23))
    purge(harness)
    assert read(harness)["payload"] == {"a": 1}


def test_senders_expiry_comes_first(harness):
    arrive(harness)
    harness.client.post("/inbox/messages/m1/ack", headers=auth())
    age(harness, InboxMessage, "m1", expires_at=now() - timedelta(minutes=1))
    purge(harness)
    assert read(harness)["payload"] is None


def test_later_expiry_keeps_content_past_the_period(harness):
    arrive(harness)
    harness.client.post("/inbox/messages/m1/ack", headers=auth())
    age(harness, InboxMessage, "m1", expires_at=now() + timedelta(hours=1), created_at=now() - timedelta(hours=48))
    purge(harness)
    assert read(harness)["payload"] == {"a": 1}


def test_received_and_not_acknowledged_is_kept_past_every_limit(harness):
    arrive(harness)
    old = now() - timedelta(days=400)
    age(harness, InboxMessage, "m1", created_at=old, expires_at=old)
    purge(harness)
    message = read(harness)
    assert message["status"] == "received"
    assert message["payload"] == {"a": 1}


def test_message_in_transfer_is_kept(harness):
    harness.notify()
    harness.settle()
    age(harness, InboxMessage, "m1", created_at=now() - timedelta(days=400))
    purge(harness)
    assert read(harness)["status"] == "transferring"


def test_rows_are_deleted_after_the_row_period(harness):
    arrive(harness)
    harness.client.post("/inbox/messages/m1/ack", headers=auth())
    age(harness, InboxMessage, "m1", created_at=now() - timedelta(days=31))
    purge(harness)
    assert harness.client.get("/inbox/messages/m1", headers=auth()).status_code == 404


def test_rows_inside_the_row_period_are_kept(harness):
    arrive(harness)
    harness.client.post("/inbox/messages/m1/ack", headers=auth())
    age(harness, InboxMessage, "m1", created_at=now() - timedelta(days=29))
    purge(harness)
    assert harness.client.get("/inbox/messages/m1", headers=auth()).status_code == 200


def test_outbox_final_messages_are_purged(harness):
    message_id = harness.send(payload={"a": 1}).json()["message_id"]
    age(harness, OutboxMessage, message_id, created_at=now() - timedelta(hours=25))
    purge(harness)
    assert harness.storage.objects == {}
    assert outbox_row(harness, message_id).payload_ref is None
    assert harness.client.get(f"/internal/payload/{message_id}").status_code == 404


def test_outbox_pending_messages_are_kept(harness):
    message_id = harness.send(payload={"a": 1}).json()["message_id"]
    age(harness, OutboxMessage, message_id, status="pending", created_at=now() - timedelta(days=400))
    purge(harness)
    assert outbox_row(harness, message_id) is not None
    assert len(harness.storage.objects) == 1


def test_outbox_rows_are_deleted_after_the_row_period(harness):
    message_id = harness.send(payload={"a": 1}).json()["message_id"]
    age(harness, OutboxMessage, message_id, created_at=now() - timedelta(days=31))
    purge(harness)
    assert outbox_row(harness, message_id) is None


def test_schema_check_recreates_a_dropped_table(harness):
    arrive(harness)

    async def drop() -> None:
        async with harness.services.db.engine.begin() as connection:
            await connection.execute(text("DROP TABLE inbox_messages"))

    harness.run(drop)
    assert harness.run(harness.services.db.ensure_schema) == ["inbox_messages"]
    assert harness.client.get("/inbox/messages", headers=auth()).json() == []
    assert harness.run(harness.services.db.ensure_schema) == []


def test_row_with_later_content_expiry_keeps_row_and_object(harness):
    arrive(harness)
    harness.client.post("/inbox/messages/m1/ack", headers=auth())
    far = now() + timedelta(days=3650)
    age(harness, InboxMessage, "m1", expires_at=far, created_at=now() - timedelta(days=31))
    purge(harness)
    assert read(harness)["payload"] == {"a": 1}
    assert len(harness.storage.objects) == 1

    age(harness, InboxMessage, "m1", expires_at=now() - timedelta(minutes=1))
    purge(harness)
    assert harness.client.get("/inbox/messages/m1", headers=auth()).status_code == 404
    assert harness.storage.objects == {}


def test_outbox_row_with_later_content_expiry_is_kept(harness):
    message_id = harness.send(payload={"a": 1}).json()["message_id"]
    age(
        harness,
        OutboxMessage,
        message_id,
        expires_at=now() + timedelta(days=3650),
        created_at=now() - timedelta(days=31),
    )
    purge(harness)
    assert outbox_row(harness, message_id) is not None
    assert len(harness.storage.objects) == 1


def conversation(harness, conversation_id: str) -> Conversation | None:
    async def get():
        async with harness.services.db.session() as session:
            return await session.get(Conversation, conversation_id)

    return harness.run(get)


def test_conversations_are_not_purged(harness):
    assert harness.notify("old", conversation_id="old-conversation").status_code == 202
    harness.settle()

    async def age_conversation() -> None:
        async with harness.services.db.session() as session:
            (await session.get(Conversation, "old-conversation")).last_message_at = now() - timedelta(days=365)
            await session.commit()

    harness.run(age_conversation)
    purge(harness)
    assert conversation(harness, "old-conversation") is not None


def faster(harness, **values) -> None:
    harness.services.settings = replace(harness.services.settings, **values)


async def until(check, seconds: float = 5.0) -> None:
    deadline = time.monotonic() + seconds
    while not await check():
        assert time.monotonic() < deadline, "The loop did not do its work in time"
        await asyncio.sleep(0.01)


def test_schema_loop_recreates_a_dropped_table_and_outlives_a_failure(harness, monkeypatch):
    arrive(harness)
    faster(harness, schema_check_seconds=0.01)
    services = harness.services
    real_ready = services.storage.ensure_ready
    outage = []

    async def fails_once() -> None:
        if not outage:
            outage.append(True)
            raise OSError("storage is starting")
        await real_ready()

    monkeypatch.setattr(services.storage, "ensure_ready", fails_once)

    async def scenario() -> None:
        async with services.db.engine.begin() as connection:
            await connection.execute(text("DROP TABLE inbox_messages"))

        async def table_is_back() -> bool:
            async with services.db.engine.begin() as connection:
                names = await connection.run_sync(lambda sync: inspect(sync).get_table_names())
            return "inbox_messages" in names

        loop = asyncio.create_task(schema_loop(services))
        try:
            await until(table_is_back)
            await until(lambda: asyncio.sleep(0, bool(outage)))
            await asyncio.sleep(0.05)
        finally:
            loop.cancel()

    harness.run(scenario)
    assert outage == [True]
    assert harness.client.get("/inbox/messages", headers=auth()).json() == []


def test_retention_loop_purges_and_outlives_a_failure(harness, monkeypatch):
    arrive(harness)
    harness.client.post("/inbox/messages/m1/ack", headers=auth())
    age(harness, InboxMessage, "m1", created_at=now() - timedelta(hours=25))
    faster(harness, retention_interval_seconds=0.01)
    services = harness.services
    real_delete = services.storage.delete
    outage = []

    async def fails_once(ref: str) -> None:
        if not outage:
            outage.append(True)
            raise OSError("storage is unavailable")
        await real_delete(ref)

    monkeypatch.setattr(services.storage, "delete", fails_once)

    async def scenario() -> None:
        async def purged() -> bool:
            return harness.storage.objects == {}

        loop = asyncio.create_task(retention_loop(services))
        try:
            await until(purged)
        finally:
            loop.cancel()

    harness.run(scenario)
    assert outage == [True]
    assert read(harness)["payload"] is None

