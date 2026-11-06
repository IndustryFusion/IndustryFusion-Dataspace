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

import json

import httpx
import pytest
from botocore.exceptions import EndpointConnectionError
from conftest import ME, PEER, ConnectorError, auth
from sqlalchemy import text
from sqlalchemy.exc import OperationalError

from app import delivery
from app.db import OutboxMessage


def status_of(harness, message_id: str) -> dict:
    return harness.client.get(f"/outbox/messages/{message_id}/status", headers=auth()).json()


def test_accepted_answer_has_the_documented_fields(harness):
    response = harness.send(payload={"a": 1})
    assert response.status_code == 202
    body = response.json()
    assert set(body) == {"message_id", "status", "applied", "conversation_state"}
    assert body["status"] == "pending"
    assert body["applied"] is True
    assert body["conversation_state"] == "OPEN"


def test_payload_goes_to_storage_not_the_row(harness):
    message_id = harness.send(payload={"secret": "value"}).json()["message_id"]
    read = harness.client.get(f"/outbox/messages/{message_id}", headers=auth()).json()
    assert read["payload_ref"].endswith(f"messages/{message_id}.json")
    assert "payload" not in read
    assert json.loads(harness.storage.objects[read["payload_ref"]]) == {"secret": "value"}


def test_message_read_has_the_documented_fields(harness):
    message_id = harness.send(payload={}, performative="request", reply_expected=True).json()["message_id"]
    read = harness.client.get(f"/outbox/messages/{message_id}", headers=auth()).json()
    assert set(read) == {
        "message_id", "conversation_id", "performative", "capability", "in_reply_to", "outcome",
        "sender_participant", "receiver_participant", "created_at", "payload_ref", "content_ref",
        "reply_expected", "status", "applied",
    }  # fmt: skip
    assert read["performative"] == "request"
    assert read["reply_expected"] is True


def test_default_performative(harness):
    message_id = harness.send(payload={}).json()["message_id"]
    assert harness.client.get(f"/outbox/messages/{message_id}", headers=auth()).json()["performative"] == "inform"


def test_conversation_id_is_assigned_or_kept(harness):
    first = harness.send(payload={}).json()["message_id"]
    assigned = harness.client.get(f"/outbox/messages/{first}", headers=auth()).json()["conversation_id"]
    assert assigned
    second = harness.send(payload={}, conversation_id=assigned).json()["message_id"]
    assert harness.client.get(f"/outbox/messages/{second}", headers=auth()).json()["conversation_id"] == assigned


def test_notified_after_offer_and_notification(harness):
    message_id = harness.send(payload={"a": 1}, capability="twin:direct").json()["message_id"]
    assert harness.connector.offered == [(message_id, f"http://me.test/internal/payload/{message_id}")]
    notification = harness.world.notifications[0]
    assert notification["url"] == "http://peer.test/internal/transfer-request"
    assert notification["auth"].startswith("Bearer ")
    body = notification["body"]
    assert body["message_id"] == message_id
    assert body["sender_participant"] == ME
    assert body["receiver_participant"] == PEER
    assert body["capability"] == "twin:direct"
    assert body["asset_id"] == message_id
    assert body["provider_dsp_url"] == "http://me-connector.test/dsp"
    assert "payload" not in body
    assert status_of(harness, message_id)["status"] == "notified"


def test_status_has_the_documented_fields(harness):
    message_id = harness.send(payload={}).json()["message_id"]
    assert set(status_of(harness, message_id)) == {
        "message_id", "status", "edc_transfer_id", "error_message", "updated_at", "applied", "conversation_state",
    }  # fmt: skip


def test_peer_notify_url_wins_over_adapter_url(harness):
    harness.world.registered[PEER]["peer_notify_url"] = "http://peer.test/peer/route"
    harness.send(payload={})
    assert harness.world.notifications[0]["url"] == "http://peer.test/peer/route/internal/transfer-request"


def test_refused_by_receiver_is_rejected(harness):
    harness.world.peer_status = 403
    message_id = harness.send(payload={}).json()["message_id"]
    status = status_of(harness, message_id)
    assert status["status"] == "rejected"
    assert "403" in status["error_message"]


def test_receiver_server_error_is_error(harness):
    harness.world.peer_status = 500
    status = status_of(harness, harness.send(payload={}).json()["message_id"])
    assert status["status"] == "error"
    assert "500" in status["error_message"]


def test_unreachable_receiver_is_error(harness):
    harness.world.peer_error = httpx.ConnectError("no route")
    status = status_of(harness, harness.send(payload={}).json()["message_id"])
    assert status["status"] == "error"
    assert "no route" in status["error_message"]


def test_connector_failure_is_error_and_does_not_notify(harness):
    harness.connector.offer_error = ConnectorError("connector said no")
    status = status_of(harness, harness.send(payload={}).json()["message_id"])
    assert status["status"] == "error"
    assert "connector said no" in status["error_message"]
    assert harness.world.notifications == []


def test_unregistered_receiver_is_not_found_and_stores_nothing(harness):
    response = harness.send(payload={"a": 1}, receiver_participant="urn:test:nobody")
    assert response.status_code == 404
    assert harness.storage.objects == {}


def test_incompatible_receiver_is_forbidden_and_stores_nothing(harness):
    harness.world.compatible = []
    assert harness.send(payload={"a": 1}).status_code == 403
    assert harness.storage.objects == {}


def test_registry_down_is_unavailable(harness):
    harness.world.registry_up = False
    assert harness.send(payload={}).status_code == 503


def test_payload_and_content_ref_is_refused(harness):
    response = harness.send(payload={"a": 1}, content_ref={"asset_id": "a", "dsp_url": "http://d"})
    assert response.status_code == 422
    body = response.json()
    assert body["error"] == "invalid_message"
    assert set(body) == {"error", "reason", "detail", "performative"}


def test_content_ref_uses_the_existing_asset(harness):
    message_id = harness.send(content_ref={"asset_id": "existing", "dsp_url": "http://other/dsp"}).json()["message_id"]
    assert harness.connector.offered == []
    assert harness.storage.objects == {}
    body = harness.world.notifications[0]["body"]
    assert body["asset_id"] == "existing"
    assert body["provider_dsp_url"] == "http://other/dsp"
    assert status_of(harness, message_id)["status"] == "notified"


def test_missing_receiver_is_a_schema_error(harness):
    response = harness.client.post("/outbox/messages", json={"payload": {}}, headers=auth())
    assert response.status_code == 422
    assert "detail" in response.json()


def test_unknown_message_is_not_found(harness):
    assert harness.client.get("/outbox/messages/none", headers=auth()).status_code == 404
    assert harness.client.get("/outbox/messages/none/status", headers=auth()).status_code == 404


def test_payload_route_serves_stored_content(harness):
    message_id = harness.send(payload={"a": 1}).json()["message_id"]
    response = harness.client.get(f"/internal/payload/{message_id}")
    assert response.status_code == 200
    assert response.json() == {"a": 1}
    assert harness.client.get("/internal/payload/none").status_code == 404


def test_empty_payload_is_stored_so_the_data_plane_finds_it(harness):
    message_id = harness.send(payload={}).json()["message_id"]
    response = harness.client.get(f"/internal/payload/{message_id}")
    assert response.status_code == 200
    assert response.json() == {}


def test_missing_payload_is_stored_as_null(harness):
    message_id = harness.send().json()["message_id"]
    response = harness.client.get(f"/internal/payload/{message_id}")
    assert response.status_code == 200
    assert response.json() is None


def test_row_starts_as_pending(harness):
    seen = []

    async def look(asset_id: str) -> None:
        async with harness.services.db.session() as session:
            seen.append((await session.get(OutboxMessage, asset_id)).status)

    harness.connector.on_offer = look
    answer = harness.send(payload={"a": 1}).json()
    assert answer["status"] == "pending"
    assert seen == ["pending"]


@pytest.mark.parametrize("error", [KeyError("@id"), ValueError("not JSON")], ids=["KeyError", "ValueError"])
def test_unexpected_failure_while_delivering_is_error(harness, error):
    harness.connector.offer_error = error
    message_id = harness.send(payload={"a": 1}).json()["message_id"]
    state = status_of(harness, message_id)
    assert state["status"] == "error"
    assert type(error).__name__ in state["error_message"]


def test_unreadable_token_answer_while_delivering_is_error(harness, monkeypatch):
    async def broken() -> str:
        raise KeyError("expires_in")

    monkeypatch.setattr(harness.services.own_token, "get", broken)
    message_id = harness.send(payload={"a": 1}).json()["message_id"]
    state = status_of(harness, message_id)
    assert state["status"] == "error"
    assert "expires_in" in state["error_message"]


@pytest.mark.parametrize("failing_status", ["registered", "notified"])
def test_database_failure_while_delivering_is_error(harness, monkeypatch, failing_status):
    real = delivery.set_outbox
    failed = []

    async def fail_once(services, message_id, **values):
        if values.get("status") == failing_status and not failed:
            failed.append(values)
            raise OperationalError("UPDATE", {}, Exception("connection lost"))
        await real(services, message_id, **values)

    monkeypatch.setattr(delivery, "set_outbox", fail_once)
    message_id = harness.send(payload={"a": 1}).json()["message_id"]
    state = status_of(harness, message_id)
    assert failed
    assert state["status"] == "error"
    assert "OperationalError" in state["error_message"]


def test_failing_to_record_a_failure_does_not_escape_the_task(harness, monkeypatch):
    async def always_fails(*_args, **_values):
        raise OperationalError("UPDATE", {}, Exception("connection lost"))

    monkeypatch.setattr(delivery, "set_outbox", always_fails)
    message = {"message_id": "m", "content_ref": None}
    harness.run(delivery.deliver, harness.services, message, {"adapter_url": "http://peer.test"})


def test_failed_save_leaves_no_object_behind(harness):
    async def drop() -> None:
        async with harness.services.db.engine.begin() as connection:
            await connection.execute(text("DROP TABLE outbox_messages"))

    harness.run(drop)
    body = {"receiver_participant": PEER, "payload": {"a": 1}}
    answer = harness.client.post("/outbox/messages", json=body, headers=auth())
    assert answer.status_code == 503
    assert harness.storage.objects == {}


def test_receiver_id_cannot_change_the_registry_address(harness):
    harness.world.registered["urn:test:a"] = {"participant_id": "urn:test:a", "adapter_url": "http://peer.test"}
    harness.world.compatible.append("urn:test:a")
    answer = harness.client.post(
        "/outbox/messages", json={"receiver_participant": "urn:test:a#b", "payload": {}}, headers=auth()
    )
    assert answer.status_code == 404
    assert harness.storage.objects == {}


def test_transfer_id_is_set_when_the_provider_serves_content(harness):
    message_id = harness.send(payload={"a": 1}).json()["message_id"]
    assert status_of(harness, message_id)["edc_transfer_id"] is None
    assert harness.client.get(f"/internal/payload/{message_id}").status_code == 200
    harness.settle()
    assert status_of(harness, message_id)["edc_transfer_id"] == "provider-transfer"
    assert status_of(harness, message_id)["status"] == "notified"


def test_transfer_lookup_failure_changes_nothing_else(harness):
    harness.connector.transfer_lookup_error = KeyError("@id")
    message_id = harness.send(payload={"a": 1}).json()["message_id"]
    assert harness.client.get(f"/internal/payload/{message_id}").status_code == 200
    harness.settle()
    state = status_of(harness, message_id)
    assert state["edc_transfer_id"] is None
    assert state["status"] == "notified"
    assert state["error_message"] is None


def test_storage_outage_on_the_payload_route_is_unavailable(harness, monkeypatch):
    message_id = harness.send(payload={"a": 1}).json()["message_id"]

    async def down(_ref: str) -> None:
        raise EndpointConnectionError(endpoint_url="http://s3.test")

    monkeypatch.setattr(harness.storage, "read_stream", down)
    assert harness.client.get(f"/internal/payload/{message_id}").status_code == 503
