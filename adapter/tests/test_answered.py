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

"""A request stays answered after retention removes its reply, and conversations outlive their messages."""

import asyncio
from datetime import timedelta

import httpx
from conftest import PEER, auth
from sqlalchemy import delete, inspect, text, update
from test_retention import age, purge

from app.db import Conversation, InboxMessage, OutboxMessage, now

OLD = now() - timedelta(days=31)


def view(harness, conversation_id: str = "c1") -> dict:
    answer = harness.client.get(f"/conversations/{conversation_id}", headers=auth())
    assert answer.status_code == 200, answer.text
    return answer.json()


def stored(harness, model, message_id: str):
    async def get():
        async with harness.services.db.session() as session:
            row = await session.get(model, message_id)
            return row.replied_at if row else "no row"

    return harness.run(get)


def remove_row(harness, model, message_id: str) -> None:
    """As retention does once a row is past its period, without waiting for the request's row to age too."""
    final = {"status": "acked"} if model is InboxMessage else {}
    age(harness, model, message_id, created_at=OLD, payload_ref=None, **final)
    purge(harness)
    assert stored(harness, model, message_id) == "no row"


def sent_request(harness) -> str:
    message_id = harness.send(conversation_id="c1", performative="request", payload={"q": 1}).json()["message_id"]
    assert harness.client.get(f"/outbox/messages/{message_id}/status", headers=auth()).json()["status"] == "notified"
    return message_id


def received_request(harness, message_id: str = "r1") -> str:
    assert harness.notify(message_id, performative="request").status_code == 202
    harness.settle()
    return message_id


def test_a_received_reply_is_stored_and_outlives_its_row(harness):
    request = sent_request(harness)
    assert harness.notify("reply", in_reply_to=request).status_code == 202
    harness.settle()
    when = stored(harness, OutboxMessage, request)
    assert when is not None
    remove_row(harness, InboxMessage, "reply")
    shown = view(harness)
    assert [m["message_id"] for m in shown["messages"]] == [request]
    assert shown["messages"][0]["replied_at"] is not None
    assert shown["outstanding_requests"] == []


def test_a_sent_reply_is_stored_once_the_receiver_accepts_it_and_outlives_its_row(harness):
    request = received_request(harness)
    assert stored(harness, InboxMessage, request) is None
    reply = harness.send(conversation_id="c1", in_reply_to=request, payload={"a": 1}).json()["message_id"]
    assert stored(harness, InboxMessage, request) is not None
    remove_row(harness, OutboxMessage, reply)
    shown = view(harness)
    assert [m["message_id"] for m in shown["messages"]] == [request]
    assert shown["messages"][0]["replied_at"] is not None
    assert shown["outstanding_requests"] == []


def test_without_a_stored_time_a_removed_reply_would_leave_the_request_outstanding(harness):
    """Shows the stored time is what keeps it answered: clearing it brings the old behaviour back."""
    request = received_request(harness)
    reply = harness.send(conversation_id="c1", in_reply_to=request, payload={}).json()["message_id"]
    remove_row(harness, OutboxMessage, reply)
    age(harness, InboxMessage, request, replied_at=None)
    assert [m["message_id"] for m in view(harness)["outstanding_requests"]] == [request]


def test_a_reply_the_receiver_refuses_stores_nothing(harness):
    request = received_request(harness)
    harness.world.peer_status = 409
    reply = harness.send(conversation_id="c1", in_reply_to=request, payload={}).json()["message_id"]
    assert harness.client.get(f"/outbox/messages/{reply}/status", headers=auth()).json()["status"] == "rejected"
    assert stored(harness, InboxMessage, request) is None
    assert [m["message_id"] for m in view(harness)["outstanding_requests"]] == [request]


def test_a_reply_the_receivers_server_fails_stores_nothing(harness):
    request = received_request(harness)
    harness.world.peer_status = 503
    harness.send(conversation_id="c1", in_reply_to=request, payload={})
    assert stored(harness, InboxMessage, request) is None


def test_a_received_reply_refused_by_the_rules_stores_nothing(harness):
    request = sent_request(harness)
    refused = harness.notify("bad", in_reply_to=request, performative="close", outcome="not-an-outcome")
    assert refused.status_code == 422
    assert stored(harness, OutboxMessage, request) is None
    harness.run(close_conversation, harness)
    after_close = harness.notify("late", in_reply_to=request)
    assert after_close.status_code == 409
    assert stored(harness, OutboxMessage, request) is None


async def close_conversation(harness) -> None:
    async with harness.services.db.session() as session:
        (await session.get(Conversation, "c1")).state = "CLOSED_RESOLVED"
        await session.commit()


def test_a_later_reply_does_not_move_the_time(harness):
    request = sent_request(harness)
    harness.notify("first", in_reply_to=request)
    harness.settle()
    first = stored(harness, OutboxMessage, request)
    harness.notify("second", in_reply_to=request)
    harness.settle()
    assert stored(harness, OutboxMessage, request) == first


def test_a_reply_in_another_conversation_or_for_an_unknown_id_marks_nothing(harness):
    request = sent_request(harness)
    assert harness.notify("elsewhere", conversation_id="c2", in_reply_to=request).status_code == 202
    assert harness.notify("unknown", in_reply_to="no-such-message").status_code == 202
    harness.settle()
    assert stored(harness, OutboxMessage, request) is None


def test_another_participant_cannot_mark_a_request(harness):
    other = "urn:test:other-mb"
    harness.world.registered[other] = {"participant_id": other, "adapter_url": "http://other.test"}
    harness.world.compatible.append(other)
    request = sent_request(harness)
    harness.notify("intruder", sender=other, in_reply_to=request)
    harness.settle()
    assert stored(harness, OutboxMessage, request) is None


def test_concurrent_replies_store_one_time(harness):
    request = sent_request(harness)

    async def many() -> list[int]:
        transport = httpx.ASGITransport(app=harness.client.app)
        async with httpx.AsyncClient(transport=transport, base_url="http://me.test") as client:
            calls = [
                client.post(
                    "/internal/transfer-request",
                    json={
                        "message_id": f"reply-{number}",
                        "conversation_id": "c1",
                        "sender_participant": PEER,
                        "receiver_participant": harness.services.settings.participant_id,
                        "in_reply_to": request,
                        "asset_id": f"reply-{number}",
                        "provider_dsp_url": "http://peer-connector.test/dsp",
                    },
                    headers=auth(PEER),
                )
                for number in range(12)
            ]
            return [answer.status_code for answer in await asyncio.gather(*calls)]

    assert harness.run(many) == [202] * 12
    harness.settle()
    first = stored(harness, OutboxMessage, request)
    assert first is not None
    harness.notify("later", in_reply_to=request)
    harness.settle()
    assert stored(harness, OutboxMessage, request) == first


def test_an_old_conversation_whose_messages_are_gone_can_be_read_and_continued(harness):
    request = sent_request(harness)
    harness.notify("reply", in_reply_to=request)
    harness.settle()
    age(harness, OutboxMessage, request, created_at=OLD, payload_ref=None)
    age(harness, InboxMessage, "reply", created_at=OLD, payload_ref=None, status="acked")

    async def idle() -> None:
        async with harness.services.db.session() as session:
            (await session.get(Conversation, "c1")).last_message_at = OLD
            await session.commit()

    harness.run(idle)
    purge(harness)
    shown = view(harness)
    assert shown["state"] == "OPEN" and shown["messages"] == [] and shown["outstanding_requests"] == []
    assert shown["last_message_at"] == OLD.isoformat()

    assert harness.send(conversation_id="c1", payload={"again": True}).status_code == 202
    again = view(harness)
    assert again["last_message_at"] > OLD.isoformat()
    assert [m["direction"] for m in again["messages"]] == ["sent"]
    assert harness.world.notifications[-1]["body"]["conversation_id"] == "c1"


def test_the_column_is_added_to_an_existing_table(harness):
    async def drop_and_check() -> tuple[list[str], set[str], set[str]]:
        async with harness.services.db.engine.begin() as connection:
            for table in ("outbox_messages", "inbox_messages"):
                await connection.execute(text(f'ALTER TABLE "{table}" DROP COLUMN "replied_at"'))
        missing = await harness.services.db.ensure_schema()
        async with harness.services.db.engine.connect() as connection:
            columns = await connection.run_sync(
                lambda sync: [
                    {c["name"] for c in inspect(sync).get_columns(table)}
                    for table in ("outbox_messages", "inbox_messages")
                ]
            )
        return missing, *columns

    missing, outbox_columns, inbox_columns = harness.run(drop_and_check)
    assert missing == []
    assert "replied_at" in outbox_columns and "replied_at" in inbox_columns
    request = sent_request(harness)
    harness.notify("reply", in_reply_to=request)
    harness.settle()
    assert stored(harness, OutboxMessage, request) is not None


def test_retention_keeps_conversations_and_removes_messages_on_time(harness):
    harness.notify("old", conversation_id="old-conversation")
    harness.notify("new", conversation_id="new-conversation")
    harness.settle()
    for message_id in ("old", "new"):
        harness.client.post(f"/internal/inbox-receive/{message_id}", content=b"{}")
        harness.client.post(f"/inbox/messages/{message_id}/ack", headers=auth())
    age(harness, InboxMessage, "old", created_at=OLD)

    async def idle() -> None:
        async with harness.services.db.session() as session:
            (await session.get(Conversation, "old-conversation")).last_message_at = OLD
            await session.commit()

    harness.run(idle)
    purge(harness)
    assert stored(harness, InboxMessage, "old") == "no row"
    assert stored(harness, InboxMessage, "new") is None
    assert view(harness, "old-conversation")["state"] == "OPEN"
    assert view(harness, "new-conversation")["messages"][0]["message_id"] == "new"


def test_a_closed_conversation_stays_closed_after_retention(harness):
    harness.notify("m1", conversation_id="closed")
    harness.settle()
    assert harness.notify("bye", conversation_id="closed", performative="close", outcome="resolved").status_code == 202
    harness.settle()

    async def idle() -> None:
        async with harness.services.db.session() as session:
            await session.execute(update(Conversation).values(last_message_at=OLD, closed_at=OLD))
            await session.execute(delete(InboxMessage))
            await session.commit()

    harness.run(idle)
    purge(harness)
    late = harness.notify("late", conversation_id="closed")
    assert late.status_code == 409
    assert late.json()["conversation_state"] == "CLOSED_RESOLVED"
    assert view(harness, "closed")["state"] == "CLOSED_RESOLVED"
