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
"""Capability policy between two real adapters on PostgreSQL, and on one adapter where one is enough."""

import asyncio
from dataclasses import replace

import httpx
import pytest
from conftest import ME, PEER, auth, token
from test_two_sided import AUTHORIZATION, FO, HOST, INTERNAL_KEY, MB, OTHER_FO, Mesh, Side, assert_same, settle
from test_two_sided import two_sided as two_sided_on_postgres

from app.capabilities import CATALOGUE, offered_by, role_name

KEY_HEADER = {"X-Internal-Key": INTERNAL_KEY}


def two_sided(scenario) -> None:
    if not HOST:
        pytest.skip("TEST_POSTGRES_HOST is not set")
    two_sided_on_postgres(scenario)


async def access_to(consumer: Side, provider: Side) -> dict[str, dict]:
    answer = await consumer.client.get(
        "/capabilities/access", params={"provider": provider.participant}, headers=auth(consumer.participant)
    )
    assert answer.status_code == 200, answer.text
    return {item["capability"]: item for item in answer.json()}


async def view_of(provider: Side, consumer: str) -> dict[str, dict]:
    answer = await provider.client.get(
        "/capabilities/access", params={"consumer": consumer}, headers=auth(provider.participant)
    )
    assert answer.status_code == 200, answer.text
    return {item["capability"]: item for item in answer.json()}


async def ask(consumer: Side, provider: str, capability: str = "twin:history", **fields) -> httpx.Response:
    body = {"provider_participant": provider, "capability": capability, **fields}
    return await consumer.client.post("/capabilities/requests", json=body, headers=auth(consumer.participant))


async def requests_on(provider: Side, status: str | None = None) -> list[dict]:
    params = {"status": status} if status else {}
    answer = await provider.client.get("/capabilities/requests", params=params, headers=auth(provider.participant))
    assert answer.status_code == 200, answer.text
    return answer.json()


async def decide(provider: Side, approval_id: str, action: str, note: str | None = None) -> httpx.Response:
    return await provider.client.patch(
        f"/capabilities/requests/{approval_id}",
        json={"action": action, "note": note},
        headers=auth(provider.participant),
    )


async def policy(provider: Side, consumer: str, capability: str, action: str) -> httpx.Response:
    body = {"consumer_id": consumer, "capability": capability, "action": action}
    return await provider.client.post("/capabilities/policy", json=body, headers=auth(provider.participant))


@pytest.mark.parametrize(
    "role, expected",
    [
        ("factory_owner", {"twin:direct": "auto", "twin:adjacents": "on-request", "twin:history": "on-request"}),
        ("machine_builder", {"mb:confidential": "auto"}),
        (
            "https://industryfusion.github.io/contexts/ontology/v0/dataspace#machine_builder",
            {"mb:confidential": "auto"},
        ),
        ("ds:factory_owner", {"twin:direct": "auto", "twin:adjacents": "on-request", "twin:history": "on-request"}),
        ("", {}),
    ],
)
def test_catalogue_for_each_role(role, expected):
    assert {name: item.default_policy for name, item in offered_by(role).items()} == expected


@pytest.mark.parametrize("name", list(CATALOGUE))
def test_every_description_matches_its_default(name):
    capability = CATALOGUE[name]
    if capability.default_policy == "auto":
        assert "by default" in capability.describe("auto")
        assert "approv" not in capability.describe("auto").lower()
    else:
        assert "once approved" in capability.describe("on-request")
    assert capability.label and capability.data_classification in {"operational", "confidential"}


def test_role_name():
    assert role_name("ds:machine_builder") == "machine_builder"


def test_view_of_a_peer_includes_own_defaults(harness):
    answer = harness.client.get("/capabilities/access", params={"consumer": PEER}, headers=auth())
    assert answer.status_code == 200
    items = {item["capability"]: item for item in answer.json()}
    assert set(items) == {"twin:direct", "twin:adjacents", "twin:history"}
    assert (items["twin:direct"]["status"], items["twin:direct"]["source"]) == ("auto", "default")
    assert (items["twin:history"]["status"], items["twin:history"]["source"]) == ("on-request", "default")
    assert set(items["twin:direct"]) >= {
        "capability", "label", "description", "data_classification", "status", "source",
    }  # fmt: skip


@pytest.mark.parametrize("params", [{}, {"provider": PEER, "consumer": ME}])
def test_access_needs_exactly_one_of_the_two(harness, params):
    assert harness.client.get("/capabilities/access", params=params, headers=auth()).status_code == 422


@pytest.mark.parametrize(
    "method, path, body",
    [
        ("get", "/capabilities/access?consumer=x", None),
        ("post", "/capabilities/requests", {"provider_participant": PEER, "capability": "mb:confidential"}),
        ("get", "/capabilities/requests", None),
        ("patch", "/capabilities/requests/x", {"action": "approve"}),
        ("post", "/capabilities/policy", {"consumer_id": PEER, "capability": "twin:direct", "action": "reset"}),
    ],
)
def test_agent_routes_need_this_participants_token(harness, method, path, body):
    call = getattr(harness.client, method)
    arguments = {"json": body} if body else {}
    assert call(path, **arguments).status_code == 401
    assert call(path, headers=auth(PEER), **arguments).status_code == 403


def test_unregistered_provider(harness):
    answer = harness.client.get("/capabilities/access", params={"provider": "urn:test:nobody"}, headers=auth())
    assert answer.status_code == 404
    body = {"provider_participant": "urn:test:nobody", "capability": "mb:confidential"}
    assert harness.client.post("/capabilities/requests", json=body, headers=auth()).status_code == 404


def test_incompatible_provider(harness):
    harness.world.compatible = []
    answer = harness.client.get("/capabilities/access", params={"provider": PEER}, headers=auth())
    assert answer.status_code == 403
    body = {"provider_participant": PEER, "capability": "mb:confidential"}
    assert harness.client.post("/capabilities/requests", json=body, headers=auth()).status_code == 403
    assert harness.world.notifications == []


def test_unreachable_provider(harness):
    harness.world.peer_error = httpx.ConnectError("down")
    answer = harness.client.get("/capabilities/access", params={"provider": PEER}, headers=auth())
    assert answer.status_code == 503
    body = {"provider_participant": PEER, "capability": "mb:confidential"}
    assert harness.client.post("/capabilities/requests", json=body, headers=auth()).status_code == 503


def test_provider_answering_with_a_failure_is_unavailable(harness):
    harness.world.peer_status = 500
    answer = harness.client.get("/capabilities/access", params={"provider": PEER}, headers=auth())
    assert answer.status_code == 503


def test_provider_with_no_address_is_unavailable(harness):
    harness.world.registered[PEER] = {"participant_id": PEER}
    answer = harness.client.get("/capabilities/access", params={"provider": PEER}, headers=auth())
    assert answer.status_code == 503


def test_provider_with_only_a_peer_address_is_called_there(harness):
    harness.world.registered[PEER] = {"participant_id": PEER, "peer_notify_url": "http://peer.test/peer/mb"}
    harness.world.peer_status = 200
    harness.world.peer_body = {"capabilities": [], "approvals": []}
    answer = harness.client.get("/capabilities/access", params={"provider": PEER}, headers=auth())
    assert answer.status_code == 200
    assert harness.world.calls_to_peer[0].url.path == "/peer/mb/internal/capabilities"


def test_a_peer_address_comes_before_the_adapter_address(harness):
    harness.world.registered[PEER] = {
        "participant_id": PEER,
        "adapter_url": "http://nowhere.test",
        "peer_notify_url": "http://peer.test/peer/mb/",
    }
    harness.world.peer_status = 202
    harness.world.peer_body = {"id": "r1", "status": "pending"}
    body = {"provider_participant": PEER, "capability": "twin:history"}
    answer = harness.client.post("/capabilities/requests", json=body, headers=auth())
    assert answer.status_code == 202
    call = harness.world.calls_to_peer[0]
    assert call.url.path == "/peer/mb/internal/capabilities/approvals"
    assert call.headers["Authorization"].startswith("Bearer ")
    assert "X-Internal-Key" not in call.headers


def test_policy_on_this_adapter(harness):
    approve = {"consumer_id": PEER, "capability": "twin:history", "action": "approve"}
    answer = harness.client.post("/capabilities/policy", json=approve, headers=auth())
    assert answer.status_code == 200
    assert (answer.json()["status"], answer.json()["source"]) == ("approved", "explicit")

    reset = {**approve, "action": "reset"}
    for _ in range(2):
        answer = harness.client.post("/capabilities/policy", json=reset, headers=auth())
        assert answer.status_code == 200
        assert (answer.json()["status"], answer.json()["source"]) == ("on-request", "default")


def test_reset_works_for_a_consumer_no_longer_registered(harness):
    body = {"consumer_id": "urn:test:gone", "capability": "twin:history", "action": "reset"}
    assert harness.client.post("/capabilities/policy", json=body, headers=auth()).status_code == 200


def test_policy_for_a_consumer_not_allowed(harness):
    body = {"consumer_id": "urn:test:nobody", "capability": "twin:history", "action": "approve"}
    assert harness.client.post("/capabilities/policy", json=body, headers=auth()).status_code == 404
    harness.world.compatible = []
    body["consumer_id"] = PEER
    assert harness.client.post("/capabilities/policy", json=body, headers=auth()).status_code == 403


@pytest.mark.parametrize(
    "body, status",
    [
        ({"consumer_id": PEER, "capability": "mb:confidential", "action": "approve"}, 404),
        ({"consumer_id": PEER, "capability": "unknown", "action": "reset"}, 404),
        ({"consumer_id": PEER, "capability": "twin:history", "action": "maybe"}, 422),
    ],
)
def test_policy_with_a_wrong_capability_or_action(harness, body, status):
    assert harness.client.post("/capabilities/policy", json=body, headers=auth()).status_code == status


def test_unknown_request(harness):
    answer = harness.client.patch("/capabilities/requests/nothing", json={"action": "approve"}, headers=auth())
    assert answer.status_code == 404
    answer = harness.client.patch(
        "/internal/capabilities/approvals/nothing", json={"action": "reset"}, headers=KEY_HEADER
    )
    assert answer.status_code == 404


def test_action_on_a_request_must_be_known(harness):
    answer = harness.client.patch("/capabilities/requests/x", json={"action": "reset"}, headers=auth())
    assert answer.status_code == 422


def test_internal_routes_with_neither_credential_or_a_wrong_key(harness):
    bad_key = {"X-Internal-Key": "wrong"}
    assert harness.client.get("/internal/capabilities").status_code == 401
    assert harness.client.get("/internal/capabilities", headers=bad_key).status_code == 401
    approval = {"consumer_id": PEER, "capability": "twin:history", "action": "request"}
    assert harness.client.post("/internal/capabilities/approvals", json=approval).status_code == 401
    change = {"default_policy": "auto"}
    assert harness.client.patch("/internal/capabilities/twin:history", json=change).status_code == 401
    assert harness.client.patch("/internal/capabilities/twin:history", json=change, headers=bad_key).status_code == 401


def test_no_configured_key_allows_nothing(harness):
    harness.services.settings = replace(harness.services.settings, adapter_internal_key="")
    assert harness.client.get("/internal/capabilities", headers={"X-Internal-Key": ""}).status_code == 401


def test_management_default_change_lasts_and_applies(harness):
    change = {"default_policy": "auto"}
    answer = harness.client.patch("/internal/capabilities/twin:history", json=change, headers=KEY_HEADER)
    assert answer.status_code == 200
    state = harness.client.get("/internal/capabilities", headers=KEY_HEADER).json()
    defaults = {item["capability"]: item["default_policy"] for item in state["capabilities"]}
    assert defaults["twin:history"] == "auto"
    assert defaults["twin:adjacents"] == "on-request"
    answer = harness.client.get("/capabilities/access", params={"consumer": PEER}, headers=auth())
    assert {item["capability"]: item["status"] for item in answer.json()}["twin:history"] == "auto"
    answer = harness.client.patch(
        "/internal/capabilities/twin:history", json={"default_policy": "on-request"}, headers=KEY_HEADER
    )
    assert answer.status_code == 200
    assert (
        harness.client.patch("/internal/capabilities/mb:confidential", json=change, headers=KEY_HEADER).status_code
        == 404
    )
    bad = {"default_policy": "disabled"}
    assert harness.client.patch("/internal/capabilities/twin:direct", json=bad, headers=KEY_HEADER).status_code == 422


def test_request_end_to_end_with_approval():
    async def scenario(fo: Side, mb: Side, _: Mesh) -> None:
        before = await access_to(mb, fo)
        assert set(before) == {"twin:direct", "twin:adjacents", "twin:history"}
        assert (before["twin:history"]["status"], before["twin:history"]["source"]) == ("on-request", "default")
        assert before["twin:history"]["label"]
        assert (before["twin:direct"]["status"], before["twin:direct"]["source"]) == ("auto", "default")

        answer = await ask(mb, FO, conversation_id="c", purpose="Compare runs", note="Line 3 only")
        assert answer.status_code == 202, answer.text
        request = answer.json()
        assert (request["status"], request["consumer_id"]) == ("pending", MB)
        assert (request["conversation_id"], request["purpose"], request["note"]) == ("c", "Compare runs", "Line 3 only")

        status = (await access_to(mb, fo))["twin:history"]
        assert (status["status"], status["source"]) == ("pending", "explicit")
        assert [item["id"] for item in await requests_on(fo, "pending")] == [request["id"]]
        assert await requests_on(fo, "approved") == []
        assert await requests_on(mb) == []

        answer = await decide(fo, request["id"], "approve", "For this quarter")
        assert answer.status_code == 200, answer.text
        decided = answer.json()
        assert (decided["status"], decided["decision_note"], decided["note"]) == (
            "approved",
            "For this quarter",
            "Line 3 only",
        )
        assert decided["resolved_at"] is not None

        for view in (await access_to(mb, fo), await view_of(fo, MB)):
            assert (view["twin:history"]["status"], view["twin:history"]["source"]) == ("approved", "explicit")
        assert (await access_to(mb, fo))["twin:history"]["decision_note"] == "For this quarter"
        assert [item["id"] for item in await requests_on(fo, "approved")] == [request["id"]]

    two_sided(scenario)


def test_denial_with_a_note_is_returned_everywhere_and_repeats_are_refused():
    async def scenario(fo: Side, mb: Side, _: Mesh) -> None:
        request = (await ask(mb, FO, note="Please")).json()
        answer = await decide(fo, request["id"], "deny", "Not this year")
        assert answer.status_code == 200
        assert (answer.json()["status"], answer.json()["decision_note"]) == ("denied", "Not this year")

        assert (await requests_on(fo, "denied"))[0]["decision_note"] == "Not this year"
        repeated = (await ask(mb, FO, note="Again")).json()
        assert repeated["id"] == request["id"]
        assert (repeated["status"], repeated["decision_note"], repeated["note"]) == (
            "denied",
            "Not this year",
            "Please",
        )
        entry = (await access_to(mb, fo))["twin:history"]
        assert (entry["status"], entry["source"], entry["decision_note"]) == ("denied", "explicit", "Not this year")

        for action in ("approve", "deny"):
            again = await decide(fo, request["id"], action, "Changed my mind")
            assert again.status_code == 409
        answer = await fo.client.patch(
            f"/internal/capabilities/approvals/{request['id']}", json={"action": "approve"}, headers=KEY_HEADER
        )
        assert answer.status_code == 409
        assert (await requests_on(fo, "denied"))[0]["decision_note"] == "Not this year"

    two_sided(scenario)


@pytest.mark.parametrize("route", ["agent", "management"])
def test_reset_through_each_route_lets_the_consumer_ask_again(route):
    async def scenario(fo: Side, mb: Side, _: Mesh) -> None:
        first = (await ask(mb, FO)).json()
        assert (await decide(fo, first["id"], "deny", "No")).status_code == 200
        if route == "agent":
            answer = await policy(fo, MB, "twin:history", "reset")
        else:
            answer = await fo.client.patch(
                f"/internal/capabilities/approvals/{first['id']}", json={"action": "reset"}, headers=KEY_HEADER
            )
        assert answer.status_code == 200, answer.text
        assert (answer.json()["status"], answer.json()["source"]) == ("on-request", "default")
        entry = (await access_to(mb, fo))["twin:history"]
        assert (entry["status"], entry["source"], entry["decision_note"]) == ("on-request", "default", None)
        assert await requests_on(fo) == []

        second = (await ask(mb, FO)).json()
        assert second["status"] == "pending"
        assert second["id"] != first["id"]

    two_sided(scenario)


def test_policy_overrides_whatever_was_there():
    async def scenario(fo: Side, mb: Side, _: Mesh) -> None:
        assert (await policy(fo, MB, "twin:history", "approve")).status_code == 200
        assert (await access_to(mb, fo))["twin:history"]["status"] == "approved"
        assert (await policy(fo, MB, "twin:history", "deny")).status_code == 200
        assert (await access_to(mb, fo))["twin:history"]["status"] == "denied"
        # A provider can also refuse what is offered by default.
        assert (await policy(fo, MB, "twin:direct", "deny")).status_code == 200
        entry = (await access_to(mb, fo))["twin:direct"]
        assert (entry["status"], entry["source"]) == ("denied", "explicit")
        assert (await policy(fo, MB, "twin:direct", "reset")).status_code == 200
        assert (await access_to(mb, fo))["twin:direct"]["status"] == "auto"

    two_sided(scenario)


def test_incompatible_role_gets_403_and_stores_nothing():
    async def scenario(fo: Side, mb: Side, _: Mesh) -> None:
        answer = await ask(fo, OTHER_FO)
        assert answer.status_code == 403
        answer = await fo.client.get("/capabilities/access", params={"provider": OTHER_FO}, headers=auth(FO))
        assert answer.status_code == 403
        assert (await policy(fo, OTHER_FO, "twin:history", "approve")).status_code == 403
        assert await requests_on(fo) == []

    two_sided(scenario)


def test_unknown_capability_at_the_provider():
    async def scenario(fo: Side, mb: Side, _: Mesh) -> None:
        answer = await ask(mb, FO, capability="mb:confidential")
        assert answer.status_code == 404
        assert await requests_on(fo) == []
        assert (await ask(fo, MB, capability="twin:direct")).status_code == 404

    two_sided(scenario)


def test_asking_for_what_the_default_allows_changes_nothing():
    async def scenario(fo: Side, mb: Side, _: Mesh) -> None:
        answer = await ask(fo, MB, capability="mb:confidential")
        assert answer.status_code == 202
        assert (answer.json()["status"], answer.json()["id"]) == ("auto", None)
        assert await requests_on(mb) == []
        entry = (await access_to(fo, mb))["mb:confidential"]
        assert (entry["status"], entry["source"]) == ("auto", "default")

    two_sided(scenario)


def test_peer_token_sees_and_does_only_its_own():
    async def scenario(fo: Side, mb: Side, _: Mesh) -> None:
        assert (await policy(fo, MB, "twin:history", "approve")).status_code == 200
        # Another consumer's approval, recorded by management.
        other = {"consumer_id": "urn:test:other-mb", "capability": "twin:history", "action": "deny", "note": "x"}
        answer = await fo.client.post("/internal/capabilities/approvals", json=other, headers=KEY_HEADER)
        assert answer.status_code == 200

        state = (await fo.client.get("/internal/capabilities", headers=auth(MB))).json()
        assert [item["consumer_id"] for item in state["approvals"]] == [MB]
        assert {item["capability"] for item in state["capabilities"]} == {
            "twin:direct",
            "twin:adjacents",
            "twin:history",
        }
        everything = (await fo.client.get("/internal/capabilities", headers=KEY_HEADER)).json()
        assert {item["consumer_id"] for item in everything["approvals"]} == {MB, "urn:test:other-mb"}

        approvals = "/internal/capabilities/approvals"
        decision = {"consumer_id": MB, "capability": "twin:adjacents", "action": "approve"}
        assert (await fo.client.post(approvals, json=decision, headers=auth(MB))).status_code == 403
        for_other = {"consumer_id": "urn:test:other-mb", "capability": "twin:adjacents", "action": "request"}
        assert (await fo.client.post(approvals, json=for_other, headers=auth(MB))).status_code == 403
        own = {"consumer_id": MB, "capability": "twin:adjacents", "action": "request"}
        assert (await fo.client.post(approvals, json=own, headers=auth(MB))).status_code == 202

        approval_id = state["approvals"][0]["id"]
        change = await fo.client.patch(f"{approvals}/{approval_id}", json={"action": "reset"}, headers=auth(MB))
        assert change.status_code == 403
        change = await fo.client.patch(
            "/internal/capabilities/twin:history", json={"default_policy": "auto"}, headers=auth(MB)
        )
        assert change.status_code == 403

    two_sided(scenario)


def test_token_of_an_incompatible_or_unregistered_peer():
    async def scenario(fo: Side, mb: Side, _: Mesh) -> None:
        for peer in (OTHER_FO, "urn:test:nobody"):
            assert (await fo.client.get("/internal/capabilities", headers=auth(peer))).status_code == 403
            own = {"consumer_id": peer, "capability": "twin:history", "action": "request"}
            answer = await fo.client.post("/internal/capabilities/approvals", json=own, headers=auth(peer))
            assert answer.status_code == 403
        assert await requests_on(fo) == []

    two_sided(scenario)


def test_management_records_a_request_and_a_decision():
    async def scenario(fo: Side, mb: Side, _: Mesh) -> None:
        approvals = "/internal/capabilities/approvals"
        ask_for = {"consumer_id": MB, "capability": "twin:history", "action": "request"}
        answer = await fo.client.post(approvals, json=ask_for, headers=KEY_HEADER)
        assert (answer.status_code, answer.json()["status"]) == (202, "pending")
        resolved = await fo.client.patch(
            f"{approvals}/{answer.json()['id']}", json={"action": "approve", "note": "ok"}, headers=KEY_HEADER
        )
        assert (resolved.status_code, resolved.json()["decision_note"]) == (200, "ok")
        decision = {"consumer_id": MB, "capability": "twin:adjacents", "action": "deny", "note": "no"}
        answer = await fo.client.post(approvals, json=decision, headers=KEY_HEADER)
        assert (answer.status_code, answer.json()["status"], answer.json()["decision_note"]) == (200, "denied", "no")
        assert (await access_to(mb, fo))["twin:adjacents"]["status"] == "denied"

    two_sided(scenario)


def test_concurrent_requests_store_one():
    async def scenario(fo: Side, mb: Side, _: Mesh) -> None:
        answers = await asyncio.gather(*[ask(mb, FO, note=f"try {n}") for n in range(20)])
        assert [answer.status_code for answer in answers] == [202] * 20
        assert len({answer.json()["id"] for answer in answers}) == 1
        assert len(await requests_on(fo)) == 1

    two_sided(scenario)


def test_concurrent_decisions_have_one_winner():
    async def scenario(fo: Side, mb: Side, _: Mesh) -> None:
        for _round in range(5):
            request = (await ask(mb, FO)).json()
            actions = [("approve" if n % 2 else "deny", f"note {n}") for n in range(16)]
            answers = await asyncio.gather(*[decide(fo, request["id"], action, note) for action, note in actions])
            codes = [answer.status_code for answer in answers]
            assert codes.count(200) == 1, codes
            assert codes.count(409) == 15, codes
            winner = next(answer.json() for answer in answers if answer.status_code == 200)
            stored = (await requests_on(fo))[0]
            assert (stored["status"], stored["decision_note"]) == (winner["status"], winner["decision_note"])
            assert (await policy(fo, MB, "twin:history", "reset")).status_code == 200

    two_sided(scenario)


def test_concurrent_policy_changes_keep_one_row():
    async def scenario(fo: Side, mb: Side, _: Mesh) -> None:
        answers = await asyncio.gather(
            *[policy(fo, MB, "twin:history", "approve" if n % 2 else "deny") for n in range(16)]
        )
        assert [answer.status_code for answer in answers] == [200] * 16
        assert len(await requests_on(fo)) == 1

    two_sided(scenario)


def test_a_message_naming_a_denied_capability_is_delivered():
    async def scenario(fo: Side, mb: Side, _: Mesh) -> None:
        assert (await policy(fo, MB, "twin:history", "deny")).status_code == 200
        before = await requests_on(fo)

        # In both directions: the consumer asks anyway, and the provider sends data under that capability.
        asked = await mb.send(conversation_id="c", performative="request", capability="twin:history", payload={"a": 1})
        sent = await fo.send(conversation_id="c", capability="twin:history", payload={"values": [1, 2]})
        await assert_same(fo, mb, "c", "OPEN")

        received = await fo.inbox_message(asked["message_id"])
        assert (received["status"], received["capability"], received["payload"]) == (
            "received",
            "twin:history",
            {"a": 1},
        )
        received = await mb.inbox_message(sent["message_id"])
        assert (received["status"], received["capability"], received["payload"]) == (
            "received",
            "twin:history",
            {"values": [1, 2]},
        )
        assert (await fo.status(sent["message_id"]))["status"] == "notified"
        assert await requests_on(fo) == before

    two_sided(scenario)


def test_grant_and_deny_messages_leave_approval_records_alone():
    async def scenario(fo: Side, mb: Side, _: Mesh) -> None:
        pending = (await ask(mb, FO, capability="twin:history")).json()
        assert (await policy(fo, MB, "twin:adjacents", "deny")).status_code == 200
        before = await requests_on(fo)
        access_before = await access_to(mb, fo)

        request = await mb.send(conversation_id="c", performative="request", capability="twin:history")
        await settle(fo, mb)
        # A grant for a request that is still pending, and for a capability denied in the records.
        for capability in ("twin:history", "twin:adjacents"):
            await fo.send(
                conversation_id="c",
                performative="grant",
                capability=capability,
                in_reply_to=request["message_id"],
                authorization=AUTHORIZATION,
            )
        await fo.send(
            conversation_id="c", performative="deny", capability="twin:direct", in_reply_to=request["message_id"]
        )
        await assert_same(fo, mb, "c", "OPEN")

        assert await requests_on(fo) == before
        assert await access_to(mb, fo) == access_before
        assert await requests_on(mb) == []
        assert (await requests_on(fo, "pending"))[0]["id"] == pending["id"]

    two_sided(scenario)


def test_a_description_follows_a_changed_default_in_every_view():
    async def scenario(fo: Side, mb: Side, _: Mesh) -> None:
        def says(entry: dict, expected: str, other: str) -> None:
            assert expected in entry["description"] and other not in entry["description"], entry

        assert "by default" in (await access_to(fo, mb))["mb:confidential"]["description"]
        answer = await mb.client.patch(
            "/internal/capabilities/mb:confidential", json={"default_policy": "on-request"}, headers=KEY_HEADER
        )
        assert answer.status_code == 200
        says((await access_to(fo, mb))["mb:confidential"], "once approved", "by default")
        says((await view_of(mb, FO))["mb:confidential"], "once approved", "by default")
        state = (await mb.client.get("/internal/capabilities", headers=KEY_HEADER)).json()
        says(state["capabilities"][0], "once approved", "by default")

        answer = await fo.client.patch(
            "/internal/capabilities/twin:history", json={"default_policy": "auto"}, headers=KEY_HEADER
        )
        assert answer.status_code == 200
        says((await access_to(mb, fo))["twin:history"], "by default", "once approved")

    two_sided(scenario)


def test_a_request_racing_a_reset_gets_a_normal_answer():
    async def scenario(fo: Side, mb: Side, _: Mesh) -> None:
        peer = {"Authorization": f"Bearer {token(MB)}"}
        body = {"consumer_id": MB, "capability": "twin:history", "action": "request"}
        transport = httpx.ASGITransport(app=fo.client._transport.app, raise_app_exceptions=False)
        async with httpx.AsyncClient(transport=transport, base_url="http://fo.test") as quiet:

            async def ask_for() -> int:
                return (await quiet.post("/internal/capabilities/approvals", json=body, headers=peer)).status_code

            async def reset() -> int:
                action = {"consumer_id": MB, "capability": "twin:history", "action": "reset"}
                return (await quiet.post("/capabilities/policy", json=action, headers=auth(FO))).status_code

            for _round in range(40):
                codes = await asyncio.gather(ask_for(), reset(), ask_for(), reset())
                assert set(codes) <= {200, 202}, codes

    two_sided(scenario)


def test_a_decision_racing_a_reset_gets_a_normal_answer():
    async def scenario(fo: Side, mb: Side, _: Mesh) -> None:
        for _round in range(20):
            codes = await asyncio.gather(
                policy(fo, MB, "twin:history", "approve"),
                policy(fo, MB, "twin:history", "reset"),
                policy(fo, MB, "twin:history", "deny"),
            )
            assert {answer.status_code for answer in codes} == {200}

    two_sided(scenario)


@pytest.mark.parametrize(
    "status, body, expected",
    [
        (200, "<html>a proxy</html>", 503),
        (200, ["a", "list"], 503),
        (200, {"something": "else"}, 503),
        (200, {"capabilities": [{"no": "fields"}], "approvals": []}, 503),
        (200, {"capabilities": "text", "approvals": 5}, 503),
        (403, ["a", "list"], 403),
        (404, "<html>not found</html>", 404),
    ],
)
def test_an_answer_from_a_provider_that_cant_be_used(harness, status, body, expected):
    original = harness.world.handle

    def handle(request: httpx.Request) -> httpx.Response:
        if str(request.url).startswith("http://peer.test/internal/capabilities"):
            if isinstance(body, str):
                return httpx.Response(status, text=body)
            return httpx.Response(status, json=body)
        return original(request)

    harness.services.http._transport = httpx.MockTransport(handle)
    answer = harness.client.get("/capabilities/access", params={"provider": PEER}, headers=auth())
    assert answer.status_code == expected
    request = {"provider_participant": PEER, "capability": "mb:confidential"}
    asked = harness.client.post("/capabilities/requests", json=request, headers=auth())
    assert asked.status_code in {expected, 202}


def test_a_peer_token_must_hold_the_role_it_claims():
    async def scenario(fo: Side, mb: Side, _: Mesh) -> None:
        claims_only = {"Authorization": f"Bearer {token(MB, roles=[])}"}
        assert (await fo.client.get("/internal/capabilities", headers=claims_only)).status_code == 403
        other_role = {"Authorization": f"Bearer {token(MB, roles=['participant:urn:test:someone'])}"}
        own = {"consumer_id": MB, "capability": "twin:history", "action": "request"}
        answer = await fo.client.post("/internal/capabilities/approvals", json=own, headers=other_role)
        assert answer.status_code == 403
        assert await requests_on(fo) == []

    two_sided(scenario)
