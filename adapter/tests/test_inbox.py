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

from functools import partial

from conftest import ME, PEER, ConnectorError, auth
from sqlalchemy import update

from app.db import InboxMessage
from app.delivery import set_inbox_in_transfer


def read(harness, message_id: str = "m1") -> dict:
    return harness.client.get(f"/inbox/messages/{message_id}", headers=auth()).json()


def arrive(harness, message_id: str = "m1", content: bytes = b'{"a": 1}', **fields) -> None:
    assert harness.notify(message_id, **fields).status_code == 202
    harness.settle()
    assert harness.client.post(f"/internal/inbox-receive/{message_id}", content=content).status_code == 200


def test_notification_starts_the_flow_and_pushes_to_this_adapter(harness):
    assert harness.notify().status_code == 202
    harness.settle()
    assert harness.pushed_to == "http://me.test/internal/inbox-receive/m1"


def test_entry_shows_as_in_transfer_until_content_arrives(harness):
    harness.notify()
    harness.settle()
    assert read(harness)["status"] == "transferring"
    assert read(harness)["payload"] is None
    assert [row["message_id"] for row in harness.client.get("/inbox/messages", headers=auth()).json()] == ["m1"]
    assert harness.client.get("/inbox/messages", params={"status": "received"}, headers=auth()).json() == []


def test_received_with_payload(harness):
    arrive(harness)
    message = read(harness)
    assert message["status"] == "received"
    assert message["payload"] == {"a": 1}
    assert message["received_at"]


def test_read_has_the_documented_fields(harness):
    arrive(harness, authorization={"scope": "conversation"}, performative="grant", capability="twin:history")
    message = read(harness)
    assert set(message) == {
        "message_id", "conversation_id", "performative", "capability", "in_reply_to", "outcome",
        "authorization", "expires_at", "response_due_at", "sender_participant", "receiver_participant",
        "created_at", "received_at", "payload", "status", "applied", "error_message", "has_files",
    }  # fmt: skip
    assert message["authorization"] == {"scope": "conversation"}
    assert message["performative"] == "grant"
    assert message["sender_participant"] == PEER
    assert message["receiver_participant"] == ME
    assert message["has_files"] is False


def test_content_is_in_storage_not_the_row(harness):
    arrive(harness, content=b'{"secret": "value"}')
    assert b'{"secret": "value"}' in harness.storage.objects.values()


def test_empty_payload_reaches_received(harness):
    arrive(harness, content=b"{}")
    message = read(harness)
    assert message["status"] == "received"
    assert message["payload"] == {}
    assert message["error_message"] is None


def test_null_payload_reads_as_null(harness):
    arrive(harness, content=b"null")
    assert read(harness)["status"] == "received"
    assert read(harness)["payload"] is None


def test_token_of_another_sender_is_refused(harness):
    body = {
        "message_id": "m1",
        "conversation_id": "c1",
        "sender_participant": PEER,
        "receiver_participant": ME,
        "asset_id": "m1",
        "provider_dsp_url": "http://x",
    }
    response = harness.client.post("/internal/transfer-request", json=body, headers=auth("urn:test:other"))
    assert response.status_code == 403
    assert read_status_code(harness) == 404


def test_no_token_is_refused(harness):
    response = harness.client.post("/internal/transfer-request", json={
        "message_id": "m1", "conversation_id": "c", "sender_participant": PEER,
        "receiver_participant": ME, "asset_id": "m1", "provider_dsp_url": "http://x",
    })  # fmt: skip
    assert response.status_code == 401


def test_wrong_receiver_is_refused(harness):
    assert harness.notify(receiver_participant="urn:test:someone-else").status_code == 403
    assert read_status_code(harness) == 404


def read_status_code(harness) -> int:
    return harness.client.get("/inbox/messages/m1", headers=auth()).status_code


def test_duplicate_is_accepted_and_keeps_one_entry(harness):
    assert harness.notify().status_code == 202
    harness.settle()
    pushes = []

    async def count(destination: str) -> None:
        pushes.append(destination)

    harness.connector.on_push = count
    assert harness.notify().status_code == 202
    harness.settle()
    assert pushes == []
    assert len(harness.client.get("/inbox/messages", headers=auth()).json()) == 1


def test_late_update_does_not_overwrite_received(harness):
    arrive(harness)

    async def late(**values) -> None:
        await set_inbox_in_transfer(harness.services, "m1", **values)

    harness.run(partial(late, status="transferring"))
    assert read(harness)["status"] == "received"
    harness.run(partial(late, status="error", error_message="late"))
    assert read(harness)["status"] == "received"
    assert read(harness)["error_message"] is None


def test_transfer_poll_failure_after_arrival_stays_received(harness):
    async def arrive_during_push(destination: str) -> None:
        async with harness.services.db.session() as session:
            await session.execute(update(InboxMessage).values(status="received"))
            await session.commit()

    harness.connector.on_push = arrive_during_push
    harness.connector.after_push_error = ConnectorError("poll failed")
    harness.notify()
    harness.settle()
    assert read(harness)["status"] == "received"


def test_failed_fetch_is_error_with_the_reason(harness):
    harness.connector.fetch_error = ConnectorError("not in the catalog")
    harness.notify()
    harness.settle()
    message = read(harness)
    assert message["status"] == "error"
    assert "not in the catalog" in message["error_message"]


def test_failed_transfer_is_error(harness):
    harness.connector.after_push_error = ConnectorError("did not finish in time")
    harness.notify()
    harness.settle()
    assert read(harness)["status"] == "error"


def test_late_content_recovers_from_error(harness):
    harness.connector.after_push_error = ConnectorError("poll failed")
    harness.notify()
    harness.settle()
    assert harness.client.post("/internal/inbox-receive/m1", content=b'{"a": 1}').status_code == 200
    assert read(harness)["status"] == "received"
    assert read(harness)["error_message"] is None


def test_content_for_an_unknown_message_is_not_found(harness):
    assert harness.client.post("/internal/inbox-receive/none", content=b"{}").status_code == 404


def test_list_is_newest_first_and_filters(harness):
    arrive(harness, "older", created_at="2026-01-01T00:00:00+00:00")
    arrive(harness, "newer", created_at="2026-06-01T00:00:00+00:00")
    harness.notify("waiting", created_at="2026-03-01T00:00:00+00:00")
    harness.settle()
    every = [row["message_id"] for row in harness.client.get("/inbox/messages", headers=auth()).json()]
    assert every == ["newer", "waiting", "older"]
    received = harness.client.get("/inbox/messages", params={"status": "received"}, headers=auth()).json()
    assert [row["message_id"] for row in received] == ["newer", "older"]


def test_acknowledge_twice(harness):
    arrive(harness)
    for _ in range(2):
        response = harness.client.post("/inbox/messages/m1/ack", headers=auth())
        assert response.status_code == 204
        assert response.content == b""
    assert read(harness)["status"] == "acked"


def test_late_content_does_not_undo_an_acknowledge(harness):
    arrive(harness)
    harness.client.post("/inbox/messages/m1/ack", headers=auth())
    harness.client.post("/internal/inbox-receive/m1", content=b'{"a": 1}')
    assert read(harness)["status"] == "acked"


def test_acknowledging_before_arrival_changes_nothing(harness):
    harness.notify()
    harness.settle()
    assert harness.client.post("/inbox/messages/m1/ack", headers=auth()).status_code == 204
    assert read(harness)["status"] == "transferring"


def test_unknown_message(harness):
    assert harness.client.get("/inbox/messages/none", headers=auth()).status_code == 404
    assert harness.client.post("/inbox/messages/none/ack", headers=auth()).status_code == 404
