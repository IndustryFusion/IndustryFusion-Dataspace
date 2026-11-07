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

import dataclasses
from datetime import datetime, timedelta
from functools import partial

import pytest
from botocore.exceptions import ClientError, EndpointConnectionError
from conftest import ME, PEER, ConnectorError, auth
from sqlalchemy import update
from sqlalchemy.exc import OperationalError

from app import delivery
from app.auth import TRANSFER_TOKEN_HEADER, transfer_token
from app.db import InboxMessage, now
from app.delivery import fetch, set_inbox_in_transfer
from app.retention import purge_expired


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
    arrive(
        harness,
        authorization={"scope": "conversation"},
        performative="grant",
        capability="twin:history",
        in_reply_to="m0",
    )
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


def test_second_message_on_a_conversation_is_kept(harness):
    assert harness.notify("m1").json()["status"] == "transferring"
    assert harness.notify("m2").json()["status"] == "transferring"
    harness.settle()
    assert len(harness.client.get("/inbox/messages", headers=auth()).json()) == 2


def test_duplicate_is_accepted_and_keeps_one_entry(harness):
    assert harness.notify().json()["status"] == "transferring"
    harness.settle()
    pushes = []

    async def count(destination: str) -> None:
        pushes.append(destination)

    harness.connector.on_push = count
    assert harness.notify().json()["status"] == "duplicate"
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
    arrive(harness, "older")
    arrive(harness, "newer")
    harness.notify("waiting")
    harness.settle()
    every = [row["message_id"] for row in harness.client.get("/inbox/messages", headers=auth()).json()]
    assert every == ["waiting", "newer", "older"]
    received = harness.client.get("/inbox/messages", params={"status": "received"}, headers=auth()).json()
    assert [row["message_id"] for row in received] == ["newer", "older"]


@pytest.mark.parametrize("stated", ["1970-01-01T00:00:00+00:00", "2999-01-01T00:00:00+00:00"])
def test_a_senders_stated_time_does_not_decide_order_or_age(harness, stated):
    arrive(harness, "first")
    arrive(harness, "second", created_at=stated)
    arrive(harness, "third")
    every = [row["message_id"] for row in harness.client.get("/inbox/messages", headers=auth()).json()]
    assert every == ["third", "second", "first"]
    year = datetime.fromisoformat(read(harness, "second")["created_at"]).year
    assert year == now().year


def test_old_stated_time_does_not_shorten_retention(harness):
    arrive(harness, created_at="1970-01-01T00:00:00+00:00")
    harness.client.post("/inbox/messages/m1/ack", headers=auth())
    harness.run(purge_expired, harness.services)
    message = read(harness)
    assert message["status"] == "acked"
    assert message["payload"] == {"a": 1}


def test_future_stated_time_does_not_extend_retention(harness):
    arrive(harness, created_at="2999-01-01T00:00:00+00:00")
    harness.client.post("/inbox/messages/m1/ack", headers=auth())

    async def age() -> None:
        async with harness.services.db.session() as session:
            row = await session.get(InboxMessage, "m1")
            row.created_at = now() - timedelta(hours=25)
            await session.commit()

    harness.run(age)
    harness.run(purge_expired, harness.services)
    assert read(harness)["payload"] is None


def test_files_read_as_a_bundle_marker(harness):
    arrive(harness)

    async def mark() -> None:
        async with harness.services.db.session() as session:
            row = await session.get(InboxMessage, "m1")
            row.has_files = True
            await session.commit()

    harness.run(mark)
    assert read(harness)["payload"] == {"_bundle": True}
    assert read(harness)["has_files"] is True


@pytest.mark.parametrize("bad", ["victim?x", "a/b", "../x", "..", "a b", "a#b", "%2e%2e", ""])
def test_unsafe_message_id_is_refused(harness, bad):
    assert harness.notify(bad, asset_id="asset").status_code == 422
    assert harness.client.get("/inbox/messages", headers=auth()).json() == []


def test_identifier_style_message_id_is_accepted(harness):
    assert harness.notify("urn:test:message-1.2_3").status_code == 202


def test_content_address_is_quoted(harness):
    pushed = []

    async def record(destination: str) -> None:
        pushed.append(destination)

    harness.connector.on_push = record
    harness.run(fetch, harness.services, "a b?x", PEER, "asset", "http://peer-connector.test/dsp")
    assert pushed == ["http://me.test/internal/inbox-receive/a%20b%3Fx"]


def test_late_content_does_not_replace_acknowledged_content(harness):
    arrive(harness)
    harness.client.post("/inbox/messages/m1/ack", headers=auth())
    answer = harness.client.post("/internal/inbox-receive/m1", content=b'{"a": "changed"}')
    assert answer.status_code == 200
    assert read(harness)["payload"] == {"a": 1}


def test_late_content_does_not_bring_back_purged_content(harness):
    arrive(harness)
    harness.client.post("/inbox/messages/m1/ack", headers=auth())

    async def age() -> None:
        async with harness.services.db.session() as session:
            row = await session.get(InboxMessage, "m1")
            row.created_at = now() - timedelta(hours=25)
            await session.commit()

    harness.run(age)
    harness.run(purge_expired, harness.services)
    assert harness.storage.objects == {}
    assert harness.client.post("/internal/inbox-receive/m1", content=b'{"a": 1}').status_code == 200
    assert harness.storage.objects == {}
    assert read(harness)["payload"] is None


OUTAGE = EndpointConnectionError(endpoint_url="http://s3.test")


def test_storage_outage_is_unavailable_when_reading(harness, monkeypatch):
    arrive(harness)

    async def down(_ref: str) -> None:
        raise OUTAGE

    monkeypatch.setattr(harness.storage, "get", down)
    assert harness.client.get("/inbox/messages", headers=auth()).status_code == 503
    assert harness.client.get("/inbox/messages/m1", headers=auth()).status_code == 503


def test_storage_outage_is_unavailable_when_content_arrives(harness, monkeypatch):
    assert harness.notify().status_code == 202
    harness.settle()

    async def down(_key: str, _content: bytes) -> None:
        raise OUTAGE

    monkeypatch.setattr(harness.storage, "put", down)
    assert harness.client.post("/internal/inbox-receive/m1", content=b"{}").status_code == 503


def test_one_unreadable_object_does_not_fail_the_list(harness, monkeypatch):
    arrive(harness, "good")
    arrive(harness, "bad")
    real_get = harness.storage.get

    async def get(ref: str) -> bytes | None:
        if "bad" in ref:
            raise ClientError({"Error": {"Code": "InternalError", "Message": "broken"}}, "GetObject")
        return await real_get(ref)

    monkeypatch.setattr(harness.storage, "get", get)
    answer = harness.client.get("/inbox/messages", headers=auth())
    assert answer.status_code == 200
    payloads = {row["message_id"]: row["payload"] for row in answer.json()}
    assert payloads == {"good": {"a": 1}, "bad": None}
    assert harness.client.get("/inbox/messages/bad", headers=auth()).status_code == 503


@pytest.mark.parametrize("error", [KeyError("agreement"), ValueError("not JSON")], ids=["KeyError", "ValueError"])
def test_unexpected_failure_while_fetching_is_error(harness, error):
    harness.connector.fetch_error = error
    assert harness.notify().status_code == 202
    harness.settle()
    message = read(harness)
    assert message["status"] == "error"
    assert type(error).__name__ in message["error_message"]


def test_database_failure_while_fetching_is_error(harness, monkeypatch):
    real = delivery.set_inbox_in_transfer
    failed = []

    async def fail_once(services, message_id, **values):
        if not failed:
            failed.append(values)
            raise OperationalError("UPDATE", {}, Exception("connection lost"))
        await real(services, message_id, **values)

    monkeypatch.setattr(delivery, "set_inbox_in_transfer", fail_once)
    assert harness.notify().status_code == 202
    harness.settle()
    message = read(harness)
    assert failed
    assert message["status"] == "error"
    assert "OperationalError" in message["error_message"]


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


def test_the_destination_is_this_adapter_with_a_token_for_this_message(harness):
    assert harness.notify().status_code == 202
    harness.settle()
    assert harness.pushed_to == "http://me.test/internal/inbox-receive/m1"
    name, value = harness.connector.push_header
    assert name == TRANSFER_TOKEN_HEADER
    assert value == transfer_token(harness.services.settings, "m1")


def test_with_a_peer_address_the_destination_is_the_peer_route(harness):
    settings = dataclasses.replace(harness.services.settings, peer_notify_url="http://gateway.test/peer/fo")
    harness.services.settings = settings
    assert harness.notify().status_code == 202
    harness.settle()
    assert harness.pushed_to == "http://gateway.test/peer/fo/internal/inbox-receive/m1"


def test_content_with_its_token_is_taken(harness):
    assert harness.notify().status_code == 202
    harness.settle()
    sent = {TRANSFER_TOKEN_HEADER: transfer_token(harness.services.settings, "m1")}
    answer = harness.client.post("/internal/inbox-receive/m1", content=b'{"a": 1}', headers=sent)
    assert answer.status_code == 200
    assert harness.client.get("/inbox/messages/m1", headers=auth()).json()["payload"] == {"a": 1}


@pytest.mark.parametrize("given", ["wrong", "", "another message"])
def test_content_with_a_wrong_token_changes_nothing(harness, given):
    assert harness.notify().status_code == 202
    harness.settle()
    before = harness.client.get("/inbox/messages/m1", headers=auth()).json()
    if given == "another message":
        given = transfer_token(harness.services.settings, "m2")
    answer = harness.client.post(
        "/internal/inbox-receive/m1", content=b'{"a": 1}', headers={TRANSFER_TOKEN_HEADER: given}
    )
    assert answer.status_code == 401
    assert harness.client.get("/inbox/messages/m1", headers=auth()).json() == before


def test_a_wrong_token_looks_the_same_for_a_message_that_does_not_exist(harness):
    answer = harness.client.post("/internal/inbox-receive/none", content=b"x", headers={TRANSFER_TOKEN_HEADER: "wrong"})
    assert answer.status_code == 401


def test_a_token_depends_on_the_participants_own_secret(harness):
    settings = harness.services.settings
    other = dataclasses.replace(settings, keycloak_client_secret="someone else's")
    assert transfer_token(settings, "m1") != transfer_token(other, "m1")
