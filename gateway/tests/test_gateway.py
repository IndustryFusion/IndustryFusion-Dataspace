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
import time

import httpx
import jwt
import pytest
from cryptography.hazmat.primitives.asymmetric import rsa
from fastapi.testclient import TestClient

from app.main import Settings, clean_path, create_app

ISSUER = "http://keycloak.test/realms/dataspace"
KEY = rsa.generate_private_key(public_exponent=65537, key_size=2048)
NEW_KEY = rsa.generate_private_key(public_exponent=65537, key_size=2048)
OWNER, BUILDER = "urn:test:fo", "urn:test:mb"


def token(participant: str | None = OWNER, issuer: str = ISSUER, key=KEY, kid: str = "k1") -> str:
    claims = {"iss": issuer, "exp": int(time.time()) + 300}
    if participant:
        claims["participant_id"] = participant
    return jwt.encode(claims, key, algorithm="RS256", headers={"kid": kid})


def auth(participant: str | None = OWNER, **kwargs) -> dict[str, str]:
    return {"Authorization": f"Bearer {token(participant, **kwargs)}"}


def jwk(key, kid: str) -> dict:
    return {**json.loads(jwt.algorithms.RSAAlgorithm.to_jwk(key.public_key())), "kid": kid, "use": "sig"}


class World:
    def __init__(self) -> None:
        self.jwks = [jwk(KEY, "k1")]
        self.jwks_up = True
        self.jwks_fetches = 0
        self.registry_up = True
        self.registry_calls: list[str] = []
        self.participants = {
            OWNER: {"participant_id": OWNER, "adapter_url": "http://owner.test"},
            BUILDER: {"participant_id": BUILDER, "adapter_url": "http://builder.test/"},
        }
        self.adapter_error: Exception | None = None
        self.jwks_answer: httpx.Response | None = None
        self.registry_list_for: set[str] = set()
        self.forwarded: list[httpx.Request] = []
        self.time = 1000.0

    def handle(self, request: httpx.Request) -> httpx.Response:
        url = str(request.url)
        if url.endswith("/protocol/openid-connect/certs"):
            self.jwks_fetches += 1
            if not self.jwks_up:
                raise httpx.ConnectError("down")
            return self.jwks_answer or httpx.Response(200, json={"keys": self.jwks})
        if url.startswith("http://registry.test"):
            self.registry_calls.append(request.url.path)
            if not self.registry_up:
                raise httpx.ConnectError("down")
            if request.url.path.startswith("/participants/compatible/") and not self.registry_list_for:
                who = request.url.path.removeprefix("/participants/compatible/")
                if who not in self.participants:
                    return httpx.Response(404, json={})
                return httpx.Response(200, json=[{"participant_id": "peer-of-" + who}])
            wanted = request.url.path.removeprefix("/participants/")
            if wanted in self.registry_list_for:
                return httpx.Response(200, json=[{"participant_id": "someone"}])
            record = self.participants.get(wanted)
            return httpx.Response(200, json=record) if record else httpx.Response(404, json={})
        if self.adapter_error:
            raise self.adapter_error
        self.forwarded.append(request)
        return httpx.Response(201, json={"from": request.url.host}, headers={"X-From-Adapter": "yes"})


@pytest.fixture
def world():
    return World()


@pytest.fixture
def client(world):
    settings = Settings(keycloak_url="http://keycloak.test", keycloak_realm="dataspace", registry_url="http://registry.test")
    http = httpx.AsyncClient(transport=httpx.MockTransport(world.handle))
    with TestClient(create_app(settings, http, clock=lambda: world.time)) as test_client:
        yield test_client


def test_health_needs_no_token(client):
    assert client.get("/health").json() == {"status": "ok"}


@pytest.mark.parametrize("headers", [{}, {"Authorization": "Basic abc"}, {"Authorization": "Bearer not.a.token"}])
def test_missing_or_garbage_token(client, world, headers):
    assert client.get("/inbox/messages", headers=headers).status_code == 401
    assert world.forwarded == []


def test_wrong_signature(client, world):
    assert client.get("/inbox/messages", headers=auth(key=NEW_KEY)).status_code == 401
    assert world.forwarded == []


def test_wrong_issuer(client, world):
    assert client.get("/inbox/messages", headers=auth(issuer="http://other/realms/dataspace")).status_code == 401
    assert world.forwarded == []


def test_unknown_key_is_refused(client):
    assert client.get("/inbox/messages", headers=auth(kid="other")).status_code == 401


def test_rotated_key_under_a_new_id_is_picked_up(client, world):
    assert client.get("/inbox/messages", headers=auth()).status_code == 201
    world.jwks = [jwk(NEW_KEY, "k2")]
    world.time += 11
    assert client.get("/inbox/messages", headers=auth(key=NEW_KEY, kid="k2")).status_code == 201


def test_rotated_key_under_the_same_id_is_picked_up(client, world):
    assert client.get("/inbox/messages", headers=auth()).status_code == 201
    world.jwks = [jwk(NEW_KEY, "k1")]
    world.time += 11
    assert client.get("/inbox/messages", headers=auth(key=NEW_KEY)).status_code == 201


def test_bad_tokens_cannot_force_a_fetch_each(client, world):
    client.get("/inbox/messages", headers=auth())
    fetches = world.jwks_fetches
    for _ in range(5):
        assert client.get("/inbox/messages", headers=auth(key=NEW_KEY)).status_code == 401
        assert client.get("/inbox/messages", headers=auth(kid="other")).status_code == 401
    assert world.jwks_fetches == fetches


def test_keys_unreachable_gives_bad_gateway(client, world):
    world.jwks_up = False
    response = client.get("/inbox/messages", headers=auth())
    assert response.status_code == 502
    assert set(response.json()) == {"detail"}


def test_cached_keys_survive_an_outage(client, world):
    assert client.get("/inbox/messages", headers=auth()).status_code == 201
    world.jwks_up = False
    assert client.get("/inbox/messages", headers=auth()).status_code == 201


def test_request_reaches_own_adapter_unchanged(client, world):
    headers = {**auth(), "X-Custom": "kept", "Content-Type": "application/json"}
    response = client.post("/outbox/messages?a=1&b=2", content=b'{"x": 1}', headers=headers)
    assert response.status_code == 201
    assert response.headers["X-From-Adapter"] == "yes"
    assert response.json() == {"from": "owner.test"}
    sent = world.forwarded[0]
    assert sent.method == "POST"
    assert str(sent.url) == "http://owner.test/outbox/messages?a=1&b=2"
    assert sent.content == b'{"x": 1}'
    assert sent.headers["Authorization"] == headers["Authorization"]
    assert sent.headers["X-Custom"] == "kept"
    assert sent.headers["Host"] == "owner.test"


@pytest.mark.parametrize("method", ["GET", "POST", "PUT", "DELETE", "PATCH"])
def test_all_methods_are_forwarded(client, world, method):
    assert client.request(method, "/thing", headers=auth()).status_code == 201
    assert world.forwarded[0].method == method


def test_two_participants_reach_only_their_own_adapters(client, world):
    client.get("/inbox/messages", headers=auth(OWNER))
    client.get("/inbox/messages", headers=auth(BUILDER))
    assert [request.url.host for request in world.forwarded] == ["owner.test", "builder.test"]
    assert str(world.forwarded[1].url) == "http://builder.test/inbox/messages"


def test_participant_in_the_path_or_query_changes_nothing(client, world):
    client.get(f"/inbox/messages?participant_id={BUILDER}", headers=auth(OWNER))
    assert world.forwarded[0].url.host == "owner.test"


def test_no_claim_is_forbidden(client, world):
    assert client.get("/inbox/messages", headers=auth(None)).status_code == 403
    assert world.forwarded == []


def test_unregistered_is_forbidden(client, world):
    assert client.get("/inbox/messages", headers=auth("urn:test:nobody")).status_code == 403
    assert world.forwarded == []


INTERNAL_PATHS = [
    "/internal/payload/1",
    "/internal",
    "/internal/",
    "/INTERNAL/payload/1",
    "/Internal/payload/1",
    "/%69nternal/payload/1",
    "/%2569nternal/payload/1",
    "/inbox/../internal/payload/1",
    "/inbox/%2e%2e/internal/payload/1",
    "/./internal/payload/1",
    "//internal/payload/1",
    "/inbox/..%2finternal/payload/1",
    "/%5Cinternal/payload/1",
]


@pytest.mark.parametrize("path", INTERNAL_PATHS)
def test_internal_paths_are_not_found_and_not_forwarded(client, world, path):
    # Sent as raw bytes, so the HTTP client doesn't tidy the path first.
    response = client.request("GET", httpx.URL("http://testserver", raw_path=path.encode()), headers=auth())
    assert response.status_code == 404
    assert world.forwarded == []


def test_internal_path_with_no_token_is_also_not_found(client):
    assert client.get("/internal/payload/1").status_code == 404


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("inbox/messages", "inbox/messages"),
        ("inbox/./messages", "inbox/messages"),
        ("inbox/x/../messages", "inbox/messages"),
        ("../../etc/passwd", "etc/passwd"),
        ("internals/x", "internals/x"),
        ("inbox/internal/x", "inbox/internal/x"),
        ("inbox/", "inbox/"),
        ("", ""),
    ],
)
def test_paths_that_are_allowed(raw, expected):
    assert clean_path(raw) == expected


def test_similar_names_are_not_blocked(client, world):
    assert client.get("/internals/x", headers=auth()).status_code == 201
    assert str(world.forwarded[0].url) == "http://owner.test/internals/x"


def test_peer_route_reaches_the_named_receiver(client, world):
    response = client.post(f"/peer/{BUILDER}/internal/transfer-request", json={"m": 1}, headers=auth(OWNER))
    assert response.status_code == 201
    assert str(world.forwarded[0].url) == "http://builder.test/internal/transfer-request"
    assert json.loads(world.forwarded[0].content) == {"m": 1}


def test_peer_route_accepts_any_valid_token(client, world):
    response = client.post(f"/peer/{BUILDER}/internal/transfer-request", json={}, headers=auth(None))
    assert response.status_code == 201


def test_peer_route_unknown_receiver(client, world):
    assert client.post("/peer/urn:none/internal/transfer-request", json={}, headers=auth()).status_code == 404
    assert world.forwarded == []


def test_peer_route_needs_a_token(client, world):
    assert client.post(f"/peer/{BUILDER}/internal/transfer-request", json={}).status_code == 401
    assert world.forwarded == []


def test_peer_route_only_covers_transfer_requests(client, world):
    response = client.get(f"/peer/{BUILDER}/internal/payload/1", headers=auth(OWNER))
    assert world.forwarded == [] or world.forwarded[0].url.host == "owner.test"
    assert response.status_code in {201, 404}
    assert all(request.url.host != "builder.test" for request in world.forwarded)


def test_compatible_answers_for_the_caller(client, world):
    response = client.get("/participants/compatible", headers=auth(OWNER))
    assert response.status_code == 200
    assert response.json() == [{"participant_id": f"peer-of-{OWNER}"}]
    assert world.forwarded == []


def test_compatible_needs_a_token_and_registration(client):
    assert client.get("/participants/compatible").status_code == 401
    assert client.get("/participants/compatible", headers=auth("urn:test:nobody")).status_code == 403


def lookups(world) -> list[str]:
    return [call for call in world.registry_calls if "compatible" not in call]


def test_lookup_is_cached_for_30_seconds(client, world):
    for _ in range(3):
        client.get("/x", headers=auth())
    assert len(lookups(world)) == 1
    world.time += 29
    client.get("/x", headers=auth())
    assert len(lookups(world)) == 1
    world.time += 2
    client.get("/x", headers=auth())
    assert len(lookups(world)) == 2


def test_failures_are_not_cached(client, world):
    world.registry_up = False
    assert client.get("/x", headers=auth()).status_code == 503
    world.registry_up = True
    assert client.get("/x", headers=auth()).status_code == 201


def test_not_registered_is_not_cached(client, world):
    assert client.get("/x", headers=auth("urn:test:new")).status_code == 403
    world.participants["urn:test:new"] = {"participant_id": "urn:test:new", "adapter_url": "http://new.test"}
    assert client.get("/x", headers=auth("urn:test:new")).status_code == 201


def test_registry_unavailable(client, world):
    world.registry_up = False
    response = client.get("/x", headers=auth())
    assert response.status_code == 503
    assert set(response.json()) == {"detail"}


def test_adapter_unavailable(client, world):
    world.adapter_error = httpx.ConnectError("no route")
    assert client.get("/x", headers=auth()).status_code == 503


def test_adapter_too_slow(client, world):
    world.adapter_error = httpx.ReadTimeout("slow")
    response = client.get("/x", headers=auth())
    assert response.status_code == 504
    assert set(response.json()) == {"detail"}


def test_record_with_no_adapter_address(client, world):
    world.participants[OWNER]["adapter_url"] = None
    assert client.get("/x", headers=auth()).status_code == 503


def test_adapter_errors_are_returned_as_they_are(client, world):
    def handler(request):
        return httpx.Response(409, json={"error": "conversation_state_violation"})

    original = world.handle
    world.handle = lambda request: (
        original(request) if "keycloak" in str(request.url) or "registry" in str(request.url) else handler(request)
    )
    settings = Settings(keycloak_url="http://keycloak.test", keycloak_realm="dataspace", registry_url="http://registry.test")
    http = httpx.AsyncClient(transport=httpx.MockTransport(lambda request: world.handle(request)))
    with TestClient(create_app(settings, http, clock=lambda: world.time)) as other:
        response = other.get("/x", headers=auth())
    assert response.status_code == 409
    assert response.json() == {"error": "conversation_state_violation"}


def test_token_without_expiry_is_refused(client, world):
    signed = jwt.encode({"iss": ISSUER, "participant_id": OWNER}, KEY, algorithm="RS256", headers={"kid": "k1"})
    assert client.get("/inbox/messages", headers={"Authorization": f"Bearer {signed}"}).status_code == 401
    assert world.forwarded == []


def test_only_rs256_is_accepted(client, world):
    claims = {"iss": ISSUER, "exp": int(time.time()) + 300, "participant_id": OWNER}
    signed = jwt.encode(claims, KEY, algorithm="RS512", headers={"kid": "k1"})
    assert client.get("/inbox/messages", headers={"Authorization": f"Bearer {signed}"}).status_code == 401
    assert world.forwarded == []


def test_peer_route_cannot_reach_a_registry_listing(client, world):
    path = f"/peer/compatible/{OWNER}/internal/transfer-request"
    world.participants[f"compatible/{OWNER}"] = None
    world.registry_list_for.add(f"compatible/{OWNER}")
    assert client.post(path, json={}, headers=auth()).status_code == 404
    assert world.forwarded == []


def test_record_for_another_participant_is_not_trusted(client, world):
    world.participants["urn:test:alias"] = {"participant_id": BUILDER, "adapter_url": "http://builder.test"}
    path = "/peer/urn:test:alias/internal/transfer-request"
    assert client.post(path, json={}, headers=auth()).status_code == 404
    assert world.forwarded == []


@pytest.mark.parametrize(
    "answer",
    [
        httpx.Response(200, text="not JSON"),
        httpx.Response(200, json={"no": "keys"}),
        httpx.Response(200, json={"keys": [{"kty": "RSA", "use": "sig"}]}),
        httpx.Response(200, json={"keys": [{"kty": "RSA", "use": "sig", "kid": "k1", "n": "!", "e": "!"}]}),
    ],
    ids=["not-json", "no-keys", "no-kid", "bad-key"],
)
def test_unreadable_signing_keys_give_bad_gateway(client, world, answer):
    world.jwks_answer = answer
    assert client.get("/inbox/messages", headers=auth()).status_code == 502
    assert world.forwarded == []


def test_content_encoding_of_a_request_is_kept(client, world):
    headers = {**auth(), "Content-Encoding": "gzip", "Content-Type": "application/json"}
    assert client.post("/outbox/messages", content=b"compressed", headers=headers).status_code == 201
    assert world.forwarded[0].headers["content-encoding"] == "gzip"
    assert world.forwarded[0].content == b"compressed"


def test_only_the_validated_authorization_header_is_forwarded(client, world):
    good = auth()["Authorization"]
    other = auth(BUILDER)["Authorization"]
    answer = client.get("/inbox/messages", headers=[("Authorization", good), ("Authorization", other)])
    assert answer.status_code == 201
    assert world.forwarded[0].url.host == "owner.test"
    assert world.forwarded[0].headers.get_list("authorization") == [good]


def test_adapter_timeout_is_120_seconds(client, world):
    assert client.get("/inbox/messages", headers=auth()).status_code == 201
    assert world.forwarded[0].extensions["timeout"]["read"] == 120

