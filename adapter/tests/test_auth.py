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

from conftest import ISSUER, ME, OTHER_KEY, PEER, auth, token


def bearer(value: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {value}"}


def test_health_needs_no_token(harness):
    assert harness.client.get("/health").status_code == 200


def test_missing_token(harness):
    assert harness.client.get("/inbox/messages").status_code == 401
    assert harness.client.get("/inbox/messages", headers={"Authorization": "Basic abc"}).status_code == 401


def test_garbage_token(harness):
    assert harness.client.get("/inbox/messages", headers=bearer("not.a.token")).status_code == 401


def test_wrong_signature(harness):
    assert harness.client.get("/inbox/messages", headers=bearer(token(key=OTHER_KEY))).status_code == 401


def test_wrong_issuer(harness):
    other = token(issuer="http://other.test/realms/dataspace")
    assert harness.client.get("/inbox/messages", headers=bearer(other)).status_code == 401
    assert ISSUER != "http://other.test/realms/dataspace"


def test_another_participants_token(harness):
    assert harness.client.get("/inbox/messages", headers=auth(PEER)).status_code == 403


def test_claim_without_the_role_is_refused(harness):
    user_token = token(ME, roles=[])
    assert harness.client.get("/inbox/messages", headers=bearer(user_token)).status_code == 403


def test_all_agent_routes_need_a_token(harness):
    client = harness.client
    assert client.post("/outbox/messages", json={}).status_code == 401
    assert client.get("/outbox/messages/x").status_code == 401
    assert client.get("/outbox/messages/x/status").status_code == 401
    assert client.get("/inbox/messages/x").status_code == 401
    assert client.post("/inbox/messages/x/ack").status_code == 401


def test_stated_sender_is_ignored(harness):
    response = harness.send(payload={"a": 1}, sender_participant="urn:test:someone-else")
    read = harness.client.get(f"/outbox/messages/{response.json()['message_id']}", headers=auth())
    assert read.json()["sender_participant"] == ME
