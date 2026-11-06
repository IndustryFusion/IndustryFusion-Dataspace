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

from datetime import timedelta

from conftest import auth
from sqlalchemy import text, update
from test_inbox import arrive, read

from app.db import InboxMessage, OutboxMessage, now
from app.retention import purge_expired


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
