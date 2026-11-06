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
"""One adapter's conversation rules, refusals and routes. test_two_sided.py covers two adapters together."""

import asyncio

import pytest
from conftest import ME, PEER, auth
from sqlalchemy import text

from app.db import Conversation, Database, InboxMessage, OutboxMessage

AUTHORIZATION = {"scope": "conversation", "expires_at": "2026-12-01T10:00:00+00:00", "constraints": {"line": 3}}


def read(harness, conversation_id: str = "c1") -> dict:
    response = harness.client.get(f"/conversations/{conversation_id}", headers=auth())
    assert response.status_code == 200, response.text
    return response.json()


def state(harness, conversation_id: str = "c1") -> str:
    return read(harness, conversation_id)["state"]


def start(harness) -> str:
    response = harness.send(payload={}, conversation_id="c1", performative="request")
    assert response.status_code == 202
    return response.json()["message_id"]


def close(harness, outcome: str = "resolved", conversation_id: str = "c1"):
    return harness.send(performative="close", outcome=outcome, conversation_id=conversation_id, payload={})


def test_close_moves_to_its_state(harness):
    start(harness)
    response = close(harness, "withdrawn")
    assert response.status_code == 202
    assert response.json()["applied"] is True
    assert response.json()["conversation_state"] == "CLOSED_WITHDRAWN"
    conversation = read(harness)
    assert (conversation["state"], conversation["outcome"]) == ("CLOSED_WITHDRAWN", "withdrawn")
    assert conversation["closed_at"] is not None


def test_close_as_escalated_needs_an_escalate(harness):
    start(harness)
    response = close(harness, "escalated")
    assert response.status_code == 409
    assert response.json()["reason"] == "escalation_required"
    assert state(harness) == "OPEN"


def test_escalate_records_who(harness):
    start(harness)
    response = harness.send(performative="escalate", conversation_id="c1", payload={})
    assert response.json()["conversation_state"] == "ESCALATING"
    assert read(harness)["escalated_by"] == ME


def test_escalator_can_deescalate(harness):
    start(harness)
    harness.send(performative="escalate", conversation_id="c1", payload={})
    response = harness.send(performative="deescalate", conversation_id="c1", payload={})
    assert (response.status_code, response.json()["conversation_state"]) == (202, "OPEN")
    assert read(harness)["escalated_by"] is None


def test_escalator_can_close_as_escalated(harness):
    start(harness)
    harness.send(performative="escalate", conversation_id="c1", payload={})
    assert close(harness, "escalated").json()["conversation_state"] == "CLOSED_ESCALATED"
    assert read(harness)["escalated_by"] == ME


@pytest.mark.parametrize("performative, fields", [("close", {"outcome": "resolved"}), ("deescalate", {})])
def test_only_the_escalator(harness, performative, fields):
    assert harness.notify("m1", conversation_id="c1", performative="escalate").status_code == 202
    response = harness.send(performative=performative, conversation_id="c1", payload={}, **fields)
    assert response.status_code == 409
    assert response.json()["reason"] == "not_escalator"
    assert state(harness) == "ESCALATING"


@pytest.mark.parametrize(
    "fields",
    [
        {"performative": "request"},
        {"performative": "inform"},
        {"performative": "cancel", "in_reply_to": "m0"},
        {"performative": "deny", "capability": "twin:direct", "in_reply_to": "m0"},
        {"performative": "grant", "capability": "twin:direct", "in_reply_to": "m0", "authorization": AUTHORIZATION},
    ],
)
def test_ordinary_messages_while_escalating(harness, fields):
    assert harness.notify("m1", conversation_id="c1", performative="escalate").status_code == 202
    response = harness.send(conversation_id="c1", payload={}, **fields)
    assert (response.status_code, response.json()["applied"]) == (202, True)
    assert state(harness) == "ESCALATING"


def test_reopen_clears_what_closing_set(harness):
    start(harness)
    close(harness)
    response = harness.send(performative="reopen", conversation_id="c1", payload={})
    assert response.json()["conversation_state"] == "OPEN"
    conversation = read(harness)
    assert (conversation["outcome"], conversation["closed_at"]) == (None, None)


@pytest.mark.parametrize("outcome", ["superseded"])
def test_reopen_refused(harness, outcome):
    start(harness)
    close(harness, outcome)
    response = harness.send(performative="reopen", conversation_id="c1", payload={})
    assert response.status_code == 409
    assert response.json()["reason"] == "reopen_not_allowed"
    assert state(harness) == f"CLOSED_{outcome.upper()}"


def test_reopen_refused_after_escalated(harness):
    start(harness)
    harness.send(performative="escalate", conversation_id="c1", payload={})
    close(harness, "escalated")
    assert harness.send(performative="reopen", conversation_id="c1", payload={}).status_code == 409


def test_repeats_that_change_nothing(harness):
    start(harness)
    reopen = harness.send(performative="reopen", conversation_id="c1", payload={})
    assert (reopen.status_code, reopen.json()["applied"], reopen.json()["conversation_state"]) == (202, False, "OPEN")

    harness.send(performative="escalate", conversation_id="c1", payload={})
    again = harness.send(performative="escalate", conversation_id="c1", payload={})
    assert (again.status_code, again.json()["applied"]) == (202, False)

    close(harness)
    for outcome in ("resolved", "failed"):
        repeat = close(harness, outcome)
        assert (repeat.status_code, repeat.json()["applied"]) == (202, False)
        assert repeat.json()["conversation_state"] == "CLOSED_RESOLVED"
    assert read(harness)["outcome"] == "resolved"


def test_a_repeat_is_still_delivered_and_says_it_was_not_applied(harness):
    start(harness)
    close(harness)
    close(harness)
    assert harness.world.notifications[-2]["body"]["sender_applied"] is True
    assert harness.world.notifications[-1]["body"]["sender_applied"] is False


@pytest.mark.parametrize(
    "fields",
    [
        {"performative": "inform"},
        {"performative": "request"},
        {"performative": "escalate"},
        {"performative": "deescalate"},
        {"performative": "cancel", "in_reply_to": "m0"},
        {"performative": "deny", "capability": "twin:direct", "in_reply_to": "m0"},
    ],
)
def test_other_messages_on_a_closed_conversation(harness, fields):
    start(harness)
    close(harness)
    response = harness.send(conversation_id="c1", payload={}, **fields)
    assert response.status_code == 409
    body = response.json()
    assert set(body) == {
        "error", "reason", "detail", "conversation_id", "conversation_state", "closed_at", "message_id",
    }  # fmt: skip
    assert body["error"] == "conversation_state_violation"
    assert body["reason"] == "conversation_closed"
    assert body["conversation_state"] == "CLOSED_RESOLVED"
    assert body["closed_at"] is not None


@pytest.mark.parametrize(
    "fields",
    [{"performative": "close", "outcome": "resolved"}, {"performative": "reopen"}, {"performative": "deescalate"}],
)
def test_unknown_conversation(harness, fields):
    response = harness.send(conversation_id="nothing", payload={"a": 1}, **fields)
    assert response.status_code == 409
    body = response.json()
    assert (body["reason"], body["conversation_state"]) == ("conversation_not_found", None)
    assert harness.client.get("/conversations/nothing", headers=auth()).status_code == 404
    # The audit row can still be read.
    stored = harness.client.get(f"/outbox/messages/{body['message_id']}", headers=auth()).json()
    assert (stored["status"], stored["applied"]) == ("rejected", False)
    status = harness.client.get(f"/outbox/messages/{body['message_id']}/status", headers=auth()).json()
    assert status["conversation_state"] is None


def test_no_conversation_id_with_a_close_is_refused(harness):
    assert harness.send(performative="close", outcome="resolved", payload={}).status_code == 409


def allow_a_third_participant(harness) -> str:
    third = "urn:test:third"
    harness.world.registered[third] = {"participant_id": third, "adapter_url": "http://third.test"}
    harness.world.compatible = [PEER, third]
    return third


def test_another_counterpart_at_the_sender(harness):
    third = allow_a_third_participant(harness)
    assert harness.notify("m1", conversation_id="c1", sender=third).status_code == 202
    response = harness.send(payload={}, conversation_id="c1")
    assert response.status_code == 409
    assert response.json()["reason"] == "counterpart_mismatch"


def test_cancel_changes_nothing(harness):
    first = start(harness)
    response = harness.send(performative="cancel", conversation_id="c1", in_reply_to=first, payload={})
    assert (response.status_code, response.json()["conversation_state"]) == (202, "OPEN")


def test_refusal_is_kept_for_audit_without_content(harness):
    start(harness)
    close(harness)
    before = dict(harness.storage.objects)
    delivered = len(harness.world.notifications)
    response = harness.send(payload={"secret": 1}, conversation_id="c1")
    assert response.status_code == 409
    message_id = response.json()["message_id"]
    assert harness.storage.objects == before
    assert len(harness.world.notifications) == delivered

    stored = harness.client.get(f"/outbox/messages/{message_id}", headers=auth()).json()
    assert (stored["status"], stored["applied"], stored["payload_ref"]) == ("rejected", False, None)
    status = harness.client.get(f"/outbox/messages/{message_id}/status", headers=auth()).json()
    assert "conversation_closed" in status["error_message"]
    audit = [item for item in read(harness)["messages"] if item["message_id"] == message_id]
    assert audit[0]["status"] == "rejected"
    assert audit[0]["applied"] is False


def test_refused_file_upload_removes_its_content(harness):
    start(harness)
    close(harness)
    before = set(harness.storage.objects)
    response = harness.client.post(
        "/outbox/files",
        data={"receiver_participant": PEER, "conversation_id": "c1"},
        files=[("files", ("a", b"x"))],
        headers=auth(),
    )
    assert response.status_code == 409
    assert set(harness.storage.objects) == before


def test_receiver_refuses_on_its_own_copy(harness):
    assert harness.notify("m1", conversation_id="c1").status_code == 202
    assert harness.notify("m2", conversation_id="c1", performative="close", outcome="resolved").status_code == 202
    harness.settle()
    response = harness.notify("m3", conversation_id="c1", performative="inform")
    assert response.status_code == 409
    assert response.json()["reason"] == "conversation_closed"
    assert response.json()["message_id"] == "m3"
    harness.settle()

    async def row():
        async with harness.services.db.session() as session:
            return await session.get(InboxMessage, "m3")

    stored = harness.run(row)
    assert (stored.status, stored.applied) == ("error", False)
    assert "conversation_closed" in stored.error_message
    assert stored.payload_ref is None


def test_receiver_starts_no_transfer_for_a_refusal(harness):
    pushes = []

    async def push(destination: str) -> None:
        pushes.append(destination)

    harness.connector.on_push = push
    assert harness.notify("m1", conversation_id="c1", performative="close", outcome="resolved").status_code == 409
    harness.settle()
    assert pushes == []


def test_different_counterpart_at_the_receiver(harness):
    third = allow_a_third_participant(harness)
    assert harness.notify("m1", conversation_id="c1").status_code == 202
    response = harness.notify("m2", conversation_id="c1", sender=third)
    assert response.status_code == 409
    assert response.json()["reason"] == "counterpart_mismatch"
    fields = {"conversation_id": "c1", "sender": third}
    closing = harness.notify("m3", performative="close", outcome="failed", **fields)
    assert closing.status_code == 409
    not_applied = harness.notify("m4", sender_applied=False, **fields)
    assert not_applied.status_code == 409
    conversation = read(harness)
    assert (conversation["state"], conversation["counterpart_participant"]) == ("OPEN", PEER)


def test_a_message_its_sender_did_not_apply_moves_nothing_here(harness):
    assert harness.notify("m1", conversation_id="c1").status_code == 202
    answer = harness.notify("m2", conversation_id="c1", performative="close", outcome="failed", sender_applied=False)
    assert answer.status_code == 202
    harness.settle()
    assert state(harness) == "OPEN"
    message = harness.client.get("/inbox/messages/m2", headers=auth()).json()
    assert message["applied"] is False
    assert message["status"] != "error"


def test_repeated_notification_changes_state_once(harness):
    assert harness.notify("m1", conversation_id="c1").status_code == 202
    close_fields = {"conversation_id": "c1", "performative": "close", "outcome": "resolved"}
    assert harness.notify("m2", **close_fields).status_code == 202
    assert harness.notify("m3", conversation_id="c1", performative="close", outcome="failed").status_code == 202
    assert harness.notify("m4", conversation_id="c1", performative="reopen").status_code == 202
    assert state(harness) == "OPEN"
    # An old close, delivered again, must not close it again.
    answer = harness.notify("m2", **close_fields)
    assert (answer.status_code, answer.json()["status"]) == (202, "duplicate")
    assert state(harness) == "OPEN"


def test_list_filters_by_state_in_any_case(harness):
    start(harness)
    harness.send(payload={}, conversation_id="c2")
    close(harness, conversation_id="c2")
    everything = harness.client.get("/conversations", headers=auth()).json()
    assert {item["conversation_id"] for item in everything} == {"c1", "c2"}
    assert set(everything[0]) == {
        "conversation_id", "state", "outcome", "counterpart_participant", "opened_at", "closed_at",
        "last_message_at", "escalated_by",
    }  # fmt: skip
    for spelling in ("open", "OPEN", "oPeN"):
        found = harness.client.get(f"/conversations?state={spelling}", headers=auth()).json()
        assert [item["conversation_id"] for item in found] == ["c1"]
    found = harness.client.get("/conversations?state=closed_resolved", headers=auth()).json()
    assert [item["conversation_id"] for item in found] == ["c2"]
    assert harness.client.get("/conversations?state=nonsense", headers=auth()).json() == []


def test_routes_need_this_participants_token(harness):
    start(harness)
    assert harness.client.get("/conversations").status_code == 401
    assert harness.client.get("/conversations/c1").status_code == 401
    assert harness.client.get("/conversations", headers=auth(PEER)).status_code == 403


def test_unknown_conversation_is_not_found(harness):
    assert harness.client.get("/conversations/nothing", headers=auth()).status_code == 404


def test_detail_has_messages_in_both_directions(harness):
    first = harness.send(payload={"question": 1}, conversation_id="c1", performative="request").json()["message_id"]
    assert harness.notify("answer", conversation_id="c1", in_reply_to=first).status_code == 202
    harness.settle()
    assert harness.client.post("/internal/inbox-receive/answer", json={"reply": 2}).status_code == 200
    conversation = read(harness)
    assert set(conversation) >= {"messages", "outstanding_requests", "outcome", "escalated_by"}
    assert [item["direction"] for item in conversation["messages"]] == ["sent", "received"]
    sent, received = conversation["messages"]
    assert set(sent) == {
        "message_id", "direction", "performative", "capability", "in_reply_to", "outcome", "sender_participant",
        "receiver_participant", "created_at", "applied", "status", "has_files", "replied_at", "payload",
    }  # fmt: skip
    assert sent["payload"] == {"question": 1}
    assert received["payload"] == {"reply": 2}
    assert sent["replied_at"] is not None
    assert received["replied_at"] is None


def test_outstanding_until_answered(harness):
    first = start(harness)
    assert [item["message_id"] for item in read(harness)["outstanding_requests"]] == [first]
    assert harness.notify("incoming", conversation_id="c1", performative="request").status_code == 202
    assert {item["message_id"] for item in read(harness)["outstanding_requests"]} == {first, "incoming"}
    assert harness.notify("answer", conversation_id="c1", in_reply_to=first).status_code == 202
    assert [item["message_id"] for item in read(harness)["outstanding_requests"]] == ["incoming"]
    harness.send(conversation_id="c1", in_reply_to="incoming", payload={})
    assert read(harness)["outstanding_requests"] == []


def test_a_refused_reply_does_not_answer_a_request(harness):
    first = start(harness)
    close(harness)
    assert harness.send(conversation_id="c1", in_reply_to=first, payload={}).status_code == 409
    response = harness.notify("late", conversation_id="c1", in_reply_to=first)
    assert response.status_code == 409
    assert [item["message_id"] for item in read(harness)["outstanding_requests"]] == [first]


def test_a_reply_the_receiver_rejects_does_not_answer_a_request(harness):
    assert harness.notify("incoming", conversation_id="c1", performative="request").status_code == 202
    harness.world.peer_status = 409
    harness.send(conversation_id="c1", in_reply_to="incoming", payload={})
    assert [item["message_id"] for item in read(harness)["outstanding_requests"]] == ["incoming"]


def test_a_refused_request_is_not_outstanding(harness):
    start(harness)
    close(harness)
    harness.send(performative="request", conversation_id="c1", payload={})
    assert len(read(harness)["outstanding_requests"]) == 1


def test_file_message_reads_as_a_bundle_in_a_conversation(harness):
    response = harness.client.post(
        "/outbox/files",
        data={"receiver_participant": PEER, "conversation_id": "c1"},
        files=[("files", ("a", b"x"))],
        headers=auth(),
    )
    assert response.status_code == 202
    harness.settle()
    sent = read(harness)["messages"][0]
    assert (sent["has_files"], sent["payload"]) == (True, {"_bundle": True})


def test_inbox_message_has_the_conversation_fields(harness):
    arguments = {
        "conversation_id": "c1",
        "performative": "grant",
        "capability": "twin:history",
        "in_reply_to": "m0",
        "authorization": AUTHORIZATION,
        "expires_at": "2026-12-02T10:00:00+00:00",
        "response_due_at": "2026-12-03T10:00:00+00:00",
    }
    assert harness.notify("m1", **arguments).status_code == 202
    harness.settle()
    assert harness.client.post("/internal/inbox-receive/m1", json={}).status_code == 200
    for message in (
        harness.client.get("/inbox/messages/m1", headers=auth()).json(),
        harness.client.get("/inbox/messages", headers=auth()).json()[0],
    ):
        assert message["authorization"] == AUTHORIZATION
        assert message["applied"] is True
        assert message["outcome"] is None
        for name in ("conversation_id", "performative", "capability", "in_reply_to"):
            assert message[name] == arguments[name]
        assert message["expires_at"].startswith("2026-12-02")
        assert message["response_due_at"].startswith("2026-12-03")


def test_later_messages_wait_for_the_first_delivery(harness):
    release_holder: list[asyncio.Event] = []

    async def make_event() -> None:
        release_holder.append(asyncio.Event())

    harness.run(make_event)
    release = release_holder[0]
    first_seen = []

    async def hold_the_first(asset_id: str) -> None:
        if not first_seen:
            first_seen.append(asset_id)
            await release.wait()

    harness.connector.on_offer = hold_the_first
    ids = []
    for fields in (
        {"performative": "request"},
        {"performative": "close", "outcome": "resolved"},
        {"performative": "reopen"},
        {"performative": "close", "outcome": "failed"},
    ):
        response = harness.client.post(
            "/outbox/messages",
            json={"receiver_participant": PEER, "conversation_id": "c1", "payload": {}, **fields},
            headers=auth(),
        )
        assert response.status_code == 202, response.text
        ids.append(response.json()["message_id"])
    # Another conversation isn't held up.
    other = harness.client.post(
        "/outbox/messages", json={"receiver_participant": PEER, "conversation_id": "c2", "payload": {}}, headers=auth()
    ).json()["message_id"]

    async def wait_for_other() -> None:
        for _ in range(200):
            if harness.world.notifications:
                return
            await asyncio.sleep(0.01)

    async def go() -> None:
        release.set()

    try:
        harness.run(wait_for_other)
        assert [item["body"]["message_id"] for item in harness.world.notifications] == [other]
    finally:
        harness.run(go)
    harness.settle()
    delivered = [item["body"]["message_id"] for item in harness.world.notifications][1:]
    assert delivered == ids


def test_a_failed_delivery_does_not_stop_the_next(harness):
    harness.world.peer_status = 500
    first = start(harness)
    harness.world.peer_status = 202
    second = harness.send(payload={}, conversation_id="c1").json()["message_id"]
    assert harness.client.get(f"/outbox/messages/{first}/status", headers=auth()).json()["status"] == "error"
    assert harness.client.get(f"/outbox/messages/{second}/status", headers=auth()).json()["status"] == "notified"


def test_rejection_by_the_receiver_is_seen_and_state_stays(harness):
    start(harness)
    harness.world.peer_status = 409
    response = close(harness)
    assert response.json()["applied"] is True
    status = harness.client.get(f"/outbox/messages/{response.json()['message_id']}/status", headers=auth()).json()
    assert status["status"] == "rejected"
    assert "refused" in status["error_message"]
    assert state(harness) == "CLOSED_RESOLVED"


def test_commit_failure_runs_no_delivery_and_removes_content(harness, monkeypatch):
    start(harness)
    delivered = len(harness.world.notifications)
    objects = set(harness.storage.objects)
    real_session = harness.services.db.session

    class FailingCommit:
        """Only the first session's commit fails, so that a delivery that wrongly goes ahead can work."""

        def __init__(self) -> None:
            self.inner = real_session()

        async def __aenter__(self):
            session = await self.inner.__aenter__()
            if harness.services.db.session is FailingCommit:
                harness.services.db.session = real_session

                async def fail() -> None:
                    raise OSError("database went away")

                session.commit = fail
            return session

        async def __aexit__(self, *details):
            return await self.inner.__aexit__(*details)

    monkeypatch.setattr(harness.services.db, "session", FailingCommit)
    response = harness.client.post(
        "/outbox/messages",
        json={"receiver_participant": PEER, "conversation_id": "c1", "payload": {}},
        headers=auth(),
    )
    assert response.status_code == 503
    harness.settle()
    assert len(harness.world.notifications) == delivered
    assert set(harness.storage.objects) == objects
    # The queue carries on after the failed one.
    assert harness.send(payload={}, conversation_id="c1").status_code == 202


def test_settling_lets_finished_tasks_leave(harness):
    class Counting(set):
        checks = 0

        def __bool__(self) -> bool:
            Counting.checks += 1
            assert Counting.checks < 100, "settle is spinning without yielding to the event loop"
            return len(self) > 0

    async def scenario() -> None:
        loop = asyncio.get_running_loop()
        finished = loop.create_future()
        finished.set_result(None)
        harness.services.tasks = Counting({finished})
        loop.call_soon(harness.services.tasks.discard, finished)
        await harness.services.settle()

    harness.run(scenario)
    harness.services.tasks = set()


def test_an_older_table_gains_the_new_column(tmp_path):
    async def scenario() -> None:
        database = Database(f"sqlite+aiosqlite:///{tmp_path}/older.db")
        await database.ensure_schema()
        async with database.engine.begin() as connection:
            await connection.execute(text("ALTER TABLE conversations DROP COLUMN state_message_id"))
        assert await database.ensure_schema() == []
        async with database.session() as session:
            session.add(Conversation(conversation_id="c", counterpart_participant="p", state_message_id="m"))
            await session.commit()
            assert (await session.get(Conversation, "c")).state_message_id == "m"
            assert await session.get(OutboxMessage, "nothing") is None
        await database.close()

    asyncio.run(scenario())
