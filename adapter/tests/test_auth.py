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

import time

import httpx
import jwt
from conftest import ISSUER, KEY, ME, OTHER_KEY, PEER, auth, token

from app.config import role_for


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


def claims_for_me(**overrides) -> dict:
    return {
        "iss": ISSUER,
        "exp": int(time.time()) + 300,
        "participant_id": ME,
        "realm_access": {"roles": [role_for(ME)]},
        **overrides,
    }


def test_token_without_expiry_is_refused(harness):
    claims = claims_for_me()
    del claims["exp"]
    signed = jwt.encode(claims, KEY, algorithm="RS256", headers={"kid": "test"})
    assert harness.client.get("/inbox/messages", headers=bearer(signed)).status_code == 401


def test_only_rs256_is_accepted(harness):
    signed = jwt.encode(claims_for_me(), KEY, algorithm="RS512", headers={"kid": "test"})
    assert harness.client.get("/inbox/messages", headers=bearer(signed)).status_code == 401
    good = jwt.encode(claims_for_me(), KEY, algorithm="RS256", headers={"kid": "test"})
    assert harness.client.get("/inbox/messages", headers=bearer(good)).status_code == 200


def test_unreadable_signing_keys_are_a_bad_gateway(harness):
    real = harness.world.handle

    def handle(request: httpx.Request) -> httpx.Response:
        if str(request.url).endswith("/protocol/openid-connect/certs"):
            return httpx.Response(200, text="not JSON")
        return real(request)

    harness.services.verifier.http = httpx.AsyncClient(transport=httpx.MockTransport(handle))
    assert harness.client.get("/inbox/messages", headers=auth()).status_code == 502

