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

"""The policy view's conversation of each decision, external providers read through the gateway, and health timing."""

import logging
from datetime import datetime

import httpx
import jwt
import pytest
from conftest import World, json_response, make_token

from app.main import app

FO, MB = "urn:test:fo", "urn:test:mb"
EXT_FO, EXT_MB = "urn:test:ext-fo", "urn:test:ext-mb"


@pytest.fixture
def world():
    instance = World()
    yield instance
    app.state.services = None


def external(world, participant_id: str, kind: str) -> dict:
    answer = world.register(
        participant_id, kind, hosted=False, adapter_url=f"http://{kind}.example:1", dsp_url="http://dsp.example"
    )
    assert answer.status_code == 200
    return answer.json()


def policy(world, fo: str, mb: str, headers: dict | None = None) -> httpx.Response:
    sent = world.admin if headers is None else headers
    return world.client.get("/api/policy", params={"fo": fo, "mb": mb}, headers=sent)


def approval(consumer: str, capability: str, conversation: str | None, status: str = "approved") -> dict:
    return {
        "id": f"{consumer}-{capability}",
        "consumer_id": consumer,
        "capability": capability,
        "status": status,
        "conversation_id": conversation,
        "decision_note": None,
    }


def by_provider(answer: httpx.Response) -> dict[str, list[dict]]:
    found: dict[str, list[dict]] = {}
    for entry in answer.json()["capabilities"]:
        found.setdefault(entry["provider"], []).append(entry)
    return found


def test_a_hosted_pair_shows_classification_and_the_conversation_of_a_decision(world):
    world.register(FO, "factory_owner")
    world.register(MB, "machine_builder")
    world.adapters.state["approvals"] = [approval(MB, "twin:history", "conv-1")]
    answer = policy(world, FO, MB)
    assert answer.status_code == 200
    owner = by_provider(answer)[FO][0]
    assert owner["consumer"] == MB and owner["data_classification"] == "operational"
    assert owner["status"] == "approved" and owner["source"] == "explicit" and owner["conversation_id"] == "conv-1"
    builder = by_provider(answer)[MB][0]
    assert builder["source"] == "default" and builder["conversation_id"] is None


def test_an_external_provider_is_read_through_the_gateway_with_the_consumers_token(world):
    made = world.register(FO, "factory_owner").json()
    external(world, EXT_MB, "machine_builder")
    world.gateway.approvals = [approval(FO, "mb:confidential", "conv-9", "denied")]
    answer = policy(world, FO, EXT_MB)
    assert answer.status_code == 200
    body = answer.json()
    assert body["unavailable"] == [] and body["unavailable_reasons"] == {}
    entry = by_provider(answer)[EXT_MB][0]
    assert entry["consumer"] == FO and entry["status"] == "denied" and entry["source"] == "explicit"
    assert entry["conversation_id"] == "conv-9" and entry["data_classification"] == "confidential"
    assert FO in by_provider(answer)
    [call] = world.gateway.calls
    assert call["method"] == "GET" and call["path"] == f"/peer/{EXT_MB}/internal/capabilities"
    assert call["internal_key"] is None
    claims = jwt.decode(call["authorization"].removeprefix("Bearer "), options={"verify_signature": False})
    assert claims["participant_id"] == FO
    assert made["client_secret"] not in answer.text
    assert call["authorization"].removeprefix("Bearer ") not in answer.text
    # Nothing went to the external adapter's own address, and no internal key went anywhere outside the hub.
    assert all("example" not in url for _, url, _, _ in world.adapters.calls)


def test_two_external_sides(world):
    external(world, EXT_FO, "factory_owner")
    external(world, EXT_MB, "machine_builder")
    answer = policy(world, EXT_FO, EXT_MB)
    assert answer.status_code == 200 and answer.json()["unavailable"] == []
    assert set(by_provider(answer)) == {EXT_FO, EXT_MB}
    readers = {
        call["path"]: jwt.decode(call["authorization"].removeprefix("Bearer "), options={"verify_signature": False})[
            "participant_id"
        ]
        for call in world.gateway.calls
    }
    assert readers == {
        f"/peer/{EXT_FO}/internal/capabilities": EXT_MB,
        f"/peer/{EXT_MB}/internal/capabilities": EXT_FO,
    }
    assert world.adapters.calls == []


def test_only_the_consumers_approvals_are_shown_even_if_the_adapter_sends_more(world):
    world.register(FO, "factory_owner")
    external(world, EXT_MB, "machine_builder")
    world.gateway.leaky = True
    world.gateway.approvals = [approval("urn:test:someone-else", "mb:confidential", "secret-conv")]
    answer = policy(world, FO, EXT_MB)
    entry = by_provider(answer)[EXT_MB][0]
    assert entry["source"] == "default" and entry["conversation_id"] is None
    assert "someone-else" not in answer.text and "secret-conv" not in answer.text


def failing(world, how: str) -> None:
    if how == "gateway down":
        world.gateway.up = False
    elif how == "no gateway address":
        world.services.external_policies.settings = world.settings.__class__(
            **{**world.settings.__dict__, "gateway_url": ""}
        )
    elif how == "no client":
        client = world.keycloak.client_of(FO)
        world.keycloak.clients = {k: v for k, v in world.keycloak.clients.items() if v is not client}
    elif how == "keycloak admin refuses":
        world.keycloak.refuse_admin = True
    else:
        world.gateway.answer = {
            "adapter refuses": json_response(403, {"detail": "The token does not belong to a participant"}),
            "unauthorized": json_response(401, {"detail": "Invalid token"}),
            "unknown": json_response(404, {"detail": "Receiver is not registered"}),
            "adapter down": json_response(503, {"detail": "The adapter is unavailable"}),
            "server error": json_response(500, {}),
            "not json": httpx.Response(200, text="<html>"),
            "wrong shape": json_response(200, {"capabilities": "x", "approvals": []}),
            "bad entry": json_response(200, {"capabilities": [{"capability": 1}], "approvals": []}),
            "bad approval": json_response(200, {"capabilities": [], "approvals": [{"id": "a"}]}),
            "a list": json_response(200, []),
        }[how]


REASONS = {
    "gateway down": "The gateway could not be reached",
    "no gateway address": "no gateway address",
    "no client": "has no client here",
    "keycloak admin refuses": "did not give this service",
    "adapter refuses": "refused the other participant's token (403)",
    "unauthorized": "refused the other participant's token (401)",
    "unknown": "did not find this participant",
    "adapter down": "could not be reached through the gateway",
    "server error": "answered 500",
    "not json": "isn't a capability state",
    "wrong shape": "isn't a capability state",
    "bad entry": "isn't a capability state",
    "bad approval": "isn't a capability state",
    "a list": "isn't a capability state",
}


@pytest.mark.parametrize("how", sorted(REASONS))
def test_an_external_provider_that_cant_be_read_is_listed_with_the_reason(world, how, caplog):
    caplog.set_level(logging.DEBUG)
    made = world.register(FO, "factory_owner").json()
    external(world, EXT_MB, "machine_builder")
    failing(world, how)
    answer = policy(world, FO, EXT_MB)
    assert answer.status_code == 200, answer.text
    body = answer.json()
    assert body["unavailable"] == [EXT_MB]
    assert REASONS[how] in body["unavailable_reasons"][EXT_MB]
    assert set(by_provider(answer)) == {FO}
    shown = answer.text + caplog.text
    assert made["client_secret"] not in shown
    for call in world.gateway.calls:
        assert call["authorization"].removeprefix("Bearer ") not in shown
    assert "http://" not in body["unavailable_reasons"][EXT_MB]


def test_a_token_keycloak_refuses_is_a_reason(world):
    world.register(FO, "factory_owner")
    external(world, EXT_MB, "machine_builder")
    original = world.keycloak.handle

    def refuse_participant_tokens(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/token") and b"client_id=urn" in request.content:
            return json_response(401, {"error": "unauthorized_client"})
        return original(request)

    world.keycloak.handle = refuse_participant_tokens
    answer = policy(world, FO, EXT_MB)
    assert answer.status_code == 200
    assert "did not give a token" in answer.json()["unavailable_reasons"][EXT_MB]
    assert world.gateway.calls == []


@pytest.mark.parametrize(
    ("headers", "status"),
    [
        ({}, 401),
        ({"Authorization": "Bearer not-a-token"}, 401),
        ({"Authorization": f"Bearer {make_token(roles=('someone',))}"}, 403),
    ],
)
def test_policy_stays_admin_only(world, headers, status):
    world.register(FO, "factory_owner")
    external(world, EXT_MB, "machine_builder")
    world.adapters.calls.clear()
    asked_before = list(world.keycloak.token_requests)
    assert policy(world, FO, EXT_MB, headers=headers).status_code == status
    assert world.gateway.calls == [] and world.adapters.calls == []
    assert world.keycloak.token_requests == asked_before


@pytest.mark.parametrize("headers", [{}, {"Authorization": f"Bearer {make_token(roles=('someone',))}"}])
def test_capability_routes_stay_admin_only(world, headers):
    world.register(FO, "factory_owner")
    world.adapters.calls.clear()
    answer = world.client.get(f"/api/participants/{FO}/capabilities", headers=headers)
    assert answer.status_code == (403 if headers else 401)
    assert world.adapters.calls == [] and world.gateway.calls == []


def test_capability_routes_still_refuse_an_external_participant(world):
    external(world, EXT_MB, "machine_builder")
    answer = world.client.get(f"/api/participants/{EXT_MB}/capabilities", headers=world.admin)
    assert answer.status_code == 409
    assert world.gateway.calls == []


def health(world) -> dict:
    answer = world.client.get("/api/health")
    assert answer.status_code == 200
    return answer.json()


def test_health_has_the_time_of_the_check_and_each_response_time(world):
    before = datetime.now().astimezone()
    body = health(world)
    checked = datetime.fromisoformat(body["checked_at"])
    assert checked.tzinfo is not None and abs((checked - before).total_seconds()) < 5
    components = {c["name"]: c for c in body["components"]}
    for name in ("registry", "gateway", "dsp-gateway", "keycloak", "storage"):
        assert isinstance(components[name]["response_ms"], int) and components[name]["response_ms"] >= 0, name


def test_a_slow_component_shows_its_time(world):
    world.gateway.delay = 0.3
    components = {c["name"]: c for c in health(world)["components"]}
    assert components["gateway"]["status"] == "ok"
    assert components["gateway"]["response_ms"] >= 300
    assert components["registry"]["response_ms"] < 300


def test_a_failing_component_has_its_time_too(world):
    world.gateway.up = False
    components = {c["name"]: c for c in health(world)["components"]}
    assert components["gateway"]["status"] == "unhealthy"
    assert isinstance(components["gateway"]["response_ms"], int)


def test_an_unconfigured_component_has_no_time(world):
    world.services.settings = world.settings.__class__(**{**world.settings.__dict__, "dsp_gateway_url": ""})
    components = {c["name"]: c for c in health(world)["components"]}
    assert components["dsp-gateway"]["status"] == "not configured"
    assert components["dsp-gateway"]["response_ms"] is None
