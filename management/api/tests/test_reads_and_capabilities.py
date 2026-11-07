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

import httpx
import pytest
from conftest import make_token

from app import manifests

FO, MB = "urn:test:fo", "urn:test:mb"


def setup_pair(world):
    world.register(FO, "factory_owner")
    world.register(MB, "machine_builder")


def test_reads_need_no_token(world):
    setup_pair(world)
    listed = world.client.get("/api/participants").json()
    assert {entry["participant_id"] for entry in listed} == {FO, MB}
    record = world.client.get(f"/api/participants/{FO}").json()
    assert set(record) == {
        "participant_id", "participant_type", "adapter_url", "dsp_url", "hosted", "externally_reachable",
        "peer_notify_url",
    }  # fmt: skip
    compatible = world.client.get(f"/api/participants/compatible/{FO}").json()
    assert [entry["participant_id"] for entry in compatible] == [MB]


def test_reads_of_something_unknown_give_404(world):
    assert world.client.get("/api/participants/urn:none").status_code == 404
    assert world.client.get("/api/participants/compatible/urn:none").status_code == 404


@pytest.mark.parametrize("path", ["/api/participants", f"/api/participants/{FO}", f"/api/participants/compatible/{FO}"])
def test_reads_with_the_registry_down_give_503(world, path):
    world.registry.up = False
    assert world.client.get(path).status_code == 503


def test_credentials(world):
    secret = world.register(FO).json()["client_secret"]
    answer = world.client.get(f"/api/participants/{FO}/credentials", headers=world.admin)
    assert answer.json() == {"client_id": FO, "client_secret": secret}


def test_credentials_of_something_unknown(world):
    assert world.client.get("/api/participants/urn:none/credentials", headers=world.admin).status_code == 404


def test_credentials_of_a_client_this_service_did_not_make(world):
    world.keycloak.add_foreign_client("dataspace-admin-cli")
    world.registry.records["dataspace-admin-cli"] = {"participant_id": "dataspace-admin-cli", "hosted": False}
    path = "/api/participants/dataspace-admin-cli/credentials"
    assert world.client.get(path, headers=world.admin).status_code == 404


def test_reading_capabilities_uses_the_internal_key_and_no_token(world):
    setup_pair(world)
    answer = world.client.get(f"/api/participants/{FO}/capabilities")
    assert answer.status_code == 200
    assert answer.json()["capabilities"][0]["capability"] == "twin:history"
    method, url, key, _ = world.adapters.calls[-1]
    assert (method, key) == ("GET", "the-internal-key")
    assert url == f"http://adapter-{manifests.slug(FO)}.dataspace-participants:8000/internal/capabilities"


def test_changing_a_default(world):
    setup_pair(world)
    path = f"/api/participants/{FO}/capabilities/twin:history"
    answer = world.client.patch(path, json={"default_policy": "auto"}, headers=world.admin)
    assert answer.status_code == 200
    method, url, key, body = world.adapters.calls[-1]
    assert method == "PATCH" and url.endswith("/internal/capabilities/twin:history") and key == "the-internal-key"
    assert body == {"default_policy": "auto"}


def test_a_wrong_default_is_refused(world):
    setup_pair(world)
    path = f"/api/participants/{FO}/capabilities/twin:history"
    assert world.client.patch(path, json={"default_policy": "maybe"}, headers=world.admin).status_code == 422
    assert not world.adapters.calls


@pytest.mark.parametrize("action,status", [("approve", 200), ("deny", 200), ("request", 202)])
def test_recording_a_decision(world, action, status):
    setup_pair(world)
    answer = world.client.post(
        f"/api/participants/{FO}/approvals",
        json={"consumer_id": MB, "capability": "twin:history", "action": action},
        headers=world.admin,
    )
    assert answer.status_code == status
    assert world.adapters.calls[-1][3]["consumer_id"] == MB


def test_a_consumer_not_registered_or_not_compatible(world):
    setup_pair(world)
    world.register("urn:test:fo2", "factory_owner")
    post = lambda consumer: world.client.post(  # noqa: E731
        f"/api/participants/{FO}/approvals",
        json={"consumer_id": consumer, "capability": "twin:history", "action": "approve"},
        headers=world.admin,
    )
    assert post("urn:none").status_code == 404
    assert post("urn:test:fo2").status_code == 403
    assert not world.adapters.calls


@pytest.mark.parametrize("action", ["approve", "deny", "reset"])
def test_changing_a_decision(world, action):
    setup_pair(world)
    answer = world.client.patch(f"/api/participants/{FO}/approvals/a1", json={"action": action}, headers=world.admin)
    assert answer.status_code == 200
    method, url, key, body = world.adapters.calls[-1]
    assert method == "PATCH" and url.endswith("/internal/capabilities/approvals/a1") and key == "the-internal-key"
    assert body["action"] == action


@pytest.mark.parametrize("status", [404, 409, 422])
def test_an_adapters_refusal_is_passed_on(world, status):
    setup_pair(world)
    world.adapters.answer = httpx.Response(status, json={"detail": "Already resolved"})
    answer = world.client.patch(f"/api/participants/{FO}/approvals/a1", json={"action": "approve"}, headers=world.admin)
    assert answer.status_code == status
    assert answer.json() == {"detail": "Already resolved"}


def test_a_wrong_internal_key_is_not_called_an_auth_error_of_the_caller(world):
    setup_pair(world)
    world.adapters.answer = httpx.Response(401, json={"detail": "Wrong internal key"})
    assert world.client.get(f"/api/participants/{FO}/capabilities").status_code == 502


@pytest.mark.parametrize("response", [httpx.Response(500, json={}), httpx.Response(200, text="not json")])
def test_an_unusable_adapter_gives_503(world, response):
    setup_pair(world)
    world.adapters.answer = response
    assert world.client.get(f"/api/participants/{FO}/capabilities").status_code == 503


def test_an_adapter_that_does_not_answer_gives_503(world):
    setup_pair(world)
    world.adapters.up = False
    assert world.client.get(f"/api/participants/{FO}/capabilities").status_code == 503


def test_an_external_participant_never_gets_the_key(world):
    world.register("urn:test:ext", "factory_owner", hosted=False, adapter_url="http://ext.example", dsp_url="http://d")
    world.register(MB, "machine_builder")
    responses = [
        world.client.get("/api/participants/urn:test:ext/capabilities"),
        world.client.patch(
            "/api/participants/urn:test:ext/capabilities/twin:history",
            json={"default_policy": "auto"},
            headers=world.admin,
        ),
        world.client.post(
            "/api/participants/urn:test:ext/approvals",
            json={"consumer_id": MB, "capability": "twin:history", "action": "approve"},
            headers=world.admin,
        ),
        world.client.patch(
            "/api/participants/urn:test:ext/approvals/a1", json={"action": "reset"}, headers=world.admin
        ),
    ]
    assert [answer.status_code for answer in responses] == [409] * 4
    assert not world.adapters.calls


def test_unknown_participants_on_capability_routes(world):
    assert world.client.get("/api/participants/urn:none/capabilities").status_code == 404
    answer = world.client.patch("/api/participants/urn:none/approvals/a", json={"action": "reset"}, headers=world.admin)
    assert answer.status_code == 404


def test_policy_for_a_hosted_pair_needs_no_token(world):
    setup_pair(world)
    world.adapters.state["approvals"] = [
        {"id": "a1", "consumer_id": MB, "capability": "twin:history", "status": "approved", "decision_note": "Yes"},
        {
            "id": "a2",
            "consumer_id": "urn:someone:else",
            "capability": "twin:history",
            "status": "denied",
            "decision_note": None,
        },
    ]
    answer = world.client.get("/api/policy", params={"fo": FO, "mb": MB})
    assert answer.status_code == 200
    body = answer.json()
    assert body["unavailable"] == []
    providers = {entry["provider"]: entry for entry in body["capabilities"]}
    assert set(providers) == {FO, MB}
    owner_side = providers[FO]
    assert owner_side["consumer"] == MB and owner_side["status"] == "approved" and owner_side["source"] == "explicit"
    assert owner_side["approval_id"] == "a1" and owner_side["decision_note"] == "Yes"
    builder_side = providers[MB]
    assert builder_side["status"] == "on-request" and builder_side["source"] == "default"
    assert builder_side["approval_id"] is None


def test_policy_with_an_external_side_needs_admin(world):
    world.register(FO, "factory_owner")
    world.register(
        "urn:test:ext", "machine_builder", hosted=False, adapter_url="http://ext.example", dsp_url="http://d"
    )
    params = {"fo": FO, "mb": "urn:test:ext"}
    assert world.client.get("/api/policy", params=params).status_code == 401
    other = {"Authorization": f"Bearer {make_token(roles=('x',))}"}
    assert world.client.get("/api/policy", params=params, headers=other).status_code == 403
    assert not world.adapters.calls


def test_policy_with_an_external_side_as_admin(world):
    world.register(FO, "factory_owner")
    world.register(
        "urn:test:ext", "machine_builder", hosted=False, adapter_url="http://ext.example", dsp_url="http://d"
    )
    answer = world.client.get("/api/policy", params={"fo": FO, "mb": "urn:test:ext"}, headers=world.admin)
    assert answer.status_code == 200
    assert answer.json()["unavailable"] == ["urn:test:ext"]
    assert {entry["provider"] for entry in answer.json()["capabilities"]} == {FO}
    assert all("ext.example" not in call[1] for call in world.adapters.calls)


def test_policy_for_a_wrong_pair(world):
    setup_pair(world)
    world.register("urn:test:fo2", "factory_owner")
    get = lambda fo, mb: world.client.get("/api/policy", params={"fo": fo, "mb": mb}).status_code  # noqa: E731
    assert get(FO, "urn:none") == 404
    assert get("urn:none", MB) == 404
    assert get(MB, FO) == 422
    assert get(FO, "urn:test:fo2") == 422
    assert world.client.get("/api/policy", params={"fo": FO}).status_code == 422


def test_policy_with_an_adapter_down_gives_503(world):
    setup_pair(world)
    world.adapters.up = False
    assert world.client.get("/api/policy", params={"fo": FO, "mb": MB}).status_code == 503


def test_health_when_all_answer(world):
    answer = world.client.get("/api/health")
    assert answer.status_code == 200
    body = answer.json()
    names = {component["name"]: component for component in body["components"]}
    assert set(names) == {"registry", "gateway", "dsp-gateway", "keycloak", "postgresql", "storage"}
    assert all(component["status"] == "ok" and component["detail"] is None for component in names.values())
    assert body["status"] == "ok"


def test_health_with_a_component_down_is_still_200_and_holds_no_secrets(world):
    world.registry.up = False

    async def refuses():
        raise RuntimeError("password authentication failed for p@ss/word")

    world.services.databases.healthy = refuses
    answer = world.client.get("/api/health")
    assert answer.status_code == 200
    body = answer.json()
    names = {component["name"]: component for component in body["components"]}
    assert body["status"] == "degraded"
    assert names["registry"]["status"] == "unhealthy" and names["registry"]["detail"]
    assert names["postgresql"]["status"] == "unhealthy"
    assert "keycloak.test" not in answer.text and "registry.test" not in answer.text


def test_health_for_the_probe(world):
    assert world.client.get("/health").json() == {"status": "ok"}


def test_the_key_never_goes_to_an_address_the_registry_holds(world):
    world.registry.records["urn:evil"] = {
        "participant_id": "urn:evil", "participant_type": "x", "hosted": True,
        "adapter_url": "http://attacker.example:9", "dsp_url": None, "externally_reachable": False,
        "peer_notify_url": None,
    }  # fmt: skip
    world.client.get("/api/participants/urn:evil/capabilities")
    assert world.adapters.calls
    assert not [call for call in world.adapters.calls if "attacker.example" in call[1]]
    derived = f"adapter-{manifests.slug('urn:evil')}.dataspace-participants"
    assert all(derived in call[1] for call in world.adapters.calls)
