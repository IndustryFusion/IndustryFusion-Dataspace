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

import asyncio
import base64
import dataclasses
import json
import pathlib
import re

import httpx
import pytest
from conftest import World

from app import manifests
from app.main import app

ID = "urn:test:fo"
NAME = manifests.slug(ID)
OBJECTS = {
    ("Secret", f"participant-{NAME}"),
    ("ConfigMap", f"connector-{NAME}"),
    ("Deployment", f"connector-{NAME}"),
    ("Service", f"connector-{NAME}"),
    ("Deployment", f"adapter-{NAME}"),
    ("Service", f"adapter-{NAME}"),
}


def test_the_slug_is_the_first_eight_of_the_hash():
    assert manifests.slug("urn:x") == __import__("hashlib").sha256(b"urn:x").hexdigest()[:8]


def test_registering_a_hosted_participant_makes_everything(world):
    answer = world.register()
    assert answer.status_code == 200
    body = answer.json()
    assert body["client_id"] == ID and body["client_secret"].startswith("secret-")
    assert body["adapter_url"] == f"http://adapter-{NAME}.dataspace-participants:8000"
    assert body["dsp_url"] == f"http://connector-{NAME}.dataspace-participants:8082/api/v1/dsp"
    assert body["peer_notify_url"] is None
    assert body["participant_type"].endswith("#factory_owner")
    assert set(world.kubernetes.objects) == OBJECTS
    assert world.databases.names == {f"adapter_{NAME}", f"edc_{NAME}"}
    assert ID in world.registry.records

    client = world.keycloak.client_of(ID)
    assert client["serviceAccountsEnabled"] and not client["publicClient"] and not client["standardFlowEnabled"]
    mapper = client["protocolMappers"][0]
    assert mapper["protocolMapper"] == "oidc-hardcoded-claim-mapper"
    assert mapper["config"]["claim.name"] == "participant_id" and mapper["config"]["claim.value"] == ID
    assert [r["name"] for r in world.keycloak.assignments[f"sa-{client['id']}"]] == [f"participant:{ID}"]


def test_the_secret_holds_credentials_and_no_deployment_does(world):
    world.register()
    secret = world.kubernetes.objects[("Secret", f"participant-{NAME}")]
    decoded = {key: base64.b64decode(value).decode() for key, value in secret["data"].items()}
    assert decoded["internal-key"] == "the-internal-key"
    assert decoded["client-secret"].startswith("secret-")
    assert "p%40ss%2Fword" in decoded["database-url"], "a password is escaped in a URL"
    for kind, name in OBJECTS:
        if kind == "Deployment":
            text = json.dumps(world.kubernetes.objects[(kind, name)])
            assert "p@ss" not in text and "the-internal-key" not in text and "hidden-s3-value" not in text


def test_the_adapter_gets_what_it_reads(world):
    world.register()
    deployment = world.kubernetes.objects[("Deployment", f"adapter-{NAME}")]
    container = deployment["spec"]["template"]["spec"]["containers"][0]
    env = {entry["name"]: entry.get("value", "from-secret") for entry in container["env"]}
    assert env["PARTICIPANT_ID"] == ID
    assert env["PARTICIPANT_TYPE"] == "factory_owner"
    assert env["SEAWEEDFS_BUCKET"] == f"participant-{NAME}"
    assert env["MAX_UPLOAD_BYTES"] == str(1024**3) and env["MAX_JSON_BYTES"] == str(4 * 1024**2)
    assert env["KEYCLOAK_CLIENT_SECRET"] == "from-secret"
    adapter_config = pathlib.Path(__file__).parents[3] / "adapter" / "app" / "config.py"
    if adapter_config.exists():
        read = set(re.findall(r'_env\("([A-Z_]+)"', adapter_config.read_text()))
        with_defaults = {
            "CONTENT_RETENTION_HOURS", "CONTROL_PLANE_RETENTION_HOURS", "RETENTION_INTERVAL_SECONDS",
            "SCHEMA_CHECK_SECONDS", "TRANSFER_BUDGET_SECONDS",
        }  # fmt: skip
        assert read - with_defaults <= set(env), read - with_defaults - set(env)


def test_images_and_resources_come_from_configuration():
    world = World(
        main_registry="registry.test", main_repo="team/ds", main_version="1.2", cpu_limit="2", memory_limit=""
    )
    world.register()
    for name in (f"adapter-{NAME}", f"connector-{NAME}"):
        container = world.kubernetes.objects[("Deployment", name)]["spec"]["template"]["spec"]["containers"][0]
        assert container["image"] == f"registry.test/team/ds/{name.split('-')[0]}:1.2"
        assert container["resources"] == {"limits": {"cpu": "2"}}


def test_the_connector_properties_template_is_the_connectors_own():
    source = pathlib.Path(__file__).parents[3] / "connector" / "connector.properties.template"
    if not source.exists():
        pytest.skip("Only the management service is here")
    assert manifests.CONNECTOR_TEMPLATE.read_text() == source.read_text()


def test_the_connector_properties_are_filled_in(world):
    world.register()
    text = world.kubernetes.objects[("ConfigMap", f"connector-{NAME}")]["data"]["connector.properties"]
    assert f"edc.participant.id={ID}" in text
    assert f"edc.hostname=http://connector-{NAME}.dataspace-participants" in text
    assert "${" not in text


def test_addresses_given_for_a_hosted_participant_are_replaced(world):
    body = world.register(adapter_url="http://evil", dsp_url="http://evil", peer_notify_url="http://evil").json()
    assert "evil" not in json.dumps(body)


def test_an_externally_reachable_hosted_participant_gets_the_peer_route(world):
    body = world.register(externally_reachable=True).json()
    assert body["peer_notify_url"] == f"http://gateway.test:8080/peer/{ID}"
    assert body["adapter_url"] == f"http://adapter-{NAME}.dataspace-participants:8000"


@pytest.mark.parametrize(
    "fields",
    [
        {"participant_type": "robot"},
        {"participant_id": ""},
        {"participant_id": "   "},
        {"participant_id": "a b"},
        {"participant_id": "a\nedc.x=y"},
        {"participant_id": "x" * 201},
    ],
)
def test_an_invalid_request_creates_nothing(world, fields):
    answer = world.register(**{"participant_id": ID, "participant_type": "factory_owner", **fields})
    assert answer.status_code == 422
    assert not world.databases.names and not world.kubernetes.objects and not world.keycloak.clients


@pytest.mark.parametrize(
    "kind",
    [
        "factory_owner",
        "ds:factory_owner",
        "https://industryfusion.github.io/contexts/ontology/v0/dataspace#factory_owner",
    ],
)
def test_each_form_of_type_is_accepted(world, kind):
    assert world.register(participant_type=kind).json()["participant_type"].endswith("#factory_owner")


def test_an_external_participant_gets_keycloak_and_registry_only(world):
    answer = world.register(
        hosted=False, adapter_url="http://a.example", dsp_url="http://d.example", peer_notify_url="http://n.example"
    )
    assert answer.status_code == 200
    body = answer.json()
    assert body["adapter_url"] == "http://a.example" and body["peer_notify_url"] == "http://n.example"
    assert body["client_secret"]
    assert not world.databases.names and not world.kubernetes.objects
    assert world.keycloak.client_of(ID)


@pytest.mark.parametrize("fields", [{}, {"adapter_url": "http://a"}, {"dsp_url": "http://d"}])
def test_an_external_participant_without_addresses_is_refused(world, fields):
    assert world.register(hosted=False, **fields).status_code == 422
    assert not world.keycloak.clients and ID not in world.registry.records


# Every call that makes a step. A failure at any of them has to leave nothing.
KEYCLOAK_FAILURES = [
    "POST /auth/admin/realms/dataspace/roles$",
    "POST /auth/admin/realms/dataspace/clients$",
    "GET .*/protocol-mappers/models$",
    "GET .*/service-account-user$",
    "GET .*/role-mappings/realm$",
    "POST .*/role-mappings/realm$",
    "GET .*/client-secret$",
]
KUBERNETES_FAILURES = [
    "POST .*/secrets$", "POST .*/configmaps$", "POST .*/deployments$", "POST .*/services$",
]  # fmt: skip


@pytest.mark.parametrize("database", ["adapter_", "edc_"])
def test_failing_to_create_a_database_undoes_everything(world, database):
    world.databases.fail_create = database
    assert world.register().status_code == 503
    world.nothing_of(ID)


@pytest.mark.parametrize("pattern", KEYCLOAK_FAILURES)
def test_a_keycloak_failure_undoes_everything(world, pattern):
    world.keycloak.fail = re.compile(pattern)
    answer = world.register()
    assert answer.status_code == 502
    world.keycloak.fail = None
    world.nothing_of(ID)


@pytest.mark.parametrize("pattern", KUBERNETES_FAILURES)
def test_a_kubernetes_failure_undoes_everything(world, pattern):
    world.kubernetes.fail = re.compile(pattern)
    answer = world.register()
    assert answer.status_code == 502
    world.kubernetes.fail = None
    world.nothing_of(ID)
    assert f"participant-{NAME}" in world.buckets.removed


@pytest.mark.parametrize("deployment", ["adapter", "connector"])
def test_pods_that_never_become_available_undo_everything(world, deployment):
    world.kubernetes.never_available = {f"{deployment}-{NAME}"}
    answer = world.register()
    assert answer.status_code == 502
    assert "available" in answer.json()["detail"]
    world.nothing_of(ID)


def test_a_registry_failure_undoes_everything(world):
    world.registry.fail_save = True
    assert world.register().status_code == 503
    world.nothing_of(ID)


def test_an_undo_that_fails_is_reported_and_delete_clears_it(world):
    world.registry.fail_save = True
    world.databases.fail_drop = True
    answer = world.register()
    assert answer.status_code == 503
    assert "could not be undone" in answer.json()["detail"] and "database" in answer.json()["detail"]
    world.databases.fail_drop = False
    world.registry.fail_save = False
    assert world.client.delete(f"/api/participants/{ID}", headers=world.admin).status_code == 204
    world.nothing_of(ID)


def snapshot(world):
    return (
        set(world.databases.names),
        {key: value["data"] if key[0] == "Secret" else value["spec"] if "spec" in value else value["data"]
         for key, value in world.kubernetes.objects.items()},
        world.keycloak.client_of(ID)["secret"],
        dict(world.registry.records),
    )  # fmt: skip


@pytest.mark.parametrize(
    "failure",
    ["save", "available", "deployments", "GET .*/protocol-mappers/models$", "GET .*/client-secret$"],
)
def test_a_failed_re_registration_leaves_the_participant_whole(world, failure):
    assert world.register().status_code == 200
    before = snapshot(world)
    if failure == "save":
        world.registry.fail_save = True
    elif failure == "available":
        world.kubernetes.never_available = {f"adapter-{NAME}"}
    elif failure == "deployments":
        world.kubernetes.fail = re.compile("PUT .*/deployments/connector")
    else:
        world.keycloak.fail = re.compile(failure)
    answer = world.register(externally_reachable=True)
    assert answer.status_code in (502, 503), answer.text
    world.kubernetes.fail = world.keycloak.fail = None
    world.kubernetes.never_available = set()
    world.registry.fail_save = False
    assert snapshot(world) == before
    assert not world.buckets.removed


def test_a_failed_re_registration_puts_changed_objects_back(world):
    world.register()
    objects = world.kubernetes.objects
    previous = objects[("Deployment", f"adapter-{NAME}")]["spec"]["template"]["spec"]["containers"][0]["image"]
    world.services.provisioner.settings = dataclasses.replace(world.settings, main_version="9.9")
    world.registry.fail_save = True
    assert world.register().status_code == 503
    assert objects[("Deployment", f"adapter-{NAME}")]["spec"]["template"]["spec"]["containers"][0]["image"] == previous


def test_repeating_keeps_credentials_and_updates_reachability(world):
    first = world.register().json()
    key = world.kubernetes.objects[("Secret", f"participant-{NAME}")]["data"]["edc-api-key"]
    second = world.register(externally_reachable=True).json()
    assert second["client_secret"] == first["client_secret"]
    assert world.kubernetes.objects[("Secret", f"participant-{NAME}")]["data"]["edc-api-key"] == key
    assert world.registry.records[ID]["externally_reachable"] is True
    assert second["peer_notify_url"]


def test_a_half_finished_client_is_completed(world):
    settings = {
        "clientId": ID, "publicClient": True, "serviceAccountsEnabled": False,
        "attributes": {"dataspace.participant_id": ID}, "id": "half", "secret": "kept", "protocolMappers": [],
    }  # fmt: skip
    world.keycloak.clients["half"] = settings
    answer = world.register()
    assert answer.status_code == 200
    assert answer.json()["client_secret"] == "kept"
    client = world.keycloak.clients["half"]
    assert client["serviceAccountsEnabled"] is True and client["publicClient"] is False
    assert client["protocolMappers"][0]["config"]["claim.value"] == ID
    assert [r["name"] for r in world.keycloak.assignments["sa-half"]] == [f"participant:{ID}"]


def test_a_failed_registration_keeps_a_half_finished_client_to_complete_later(world):
    world.keycloak.clients["half"] = {
        "clientId": ID, "attributes": {"dataspace.participant_id": ID}, "id": "half", "secret": "kept",
        "protocolMappers": [], "publicClient": False, "serviceAccountsEnabled": True,
    }  # fmt: skip
    world.registry.fail_save = True
    assert world.register().status_code == 503
    assert world.keycloak.client_of(ID) is not None
    assert not world.databases.names


@pytest.mark.parametrize(
    "fields",
    [{"hosted": False, "adapter_url": "http://a", "dsp_url": "http://d"}, {"participant_type": "machine_builder"}],
)
def test_changing_hosting_or_type_is_refused(world, fields):
    world.register()
    before = snapshot(world)
    assert world.register(**fields).status_code == 409
    assert snapshot(world) == before


def test_a_foreign_client_is_left_alone(world):
    world.keycloak.add_foreign_client(ID)
    answer = world.register()
    assert answer.status_code == 409
    assert world.keycloak.clients["foreign"] == {
        "id": "foreign",
        "clientId": ID,
        "attributes": {},
        "protocolMappers": [],
    }
    assert not world.databases.names and not world.kubernetes.objects and not world.keycloak.roles


def test_a_slug_held_by_another_participant_is_refused(world, monkeypatch):
    world.register()
    before = snapshot(world)
    monkeypatch.setattr(manifests, "slug", lambda _: NAME)
    assert world.register("urn:test:other").status_code == 409
    assert snapshot(world) == before
    assert world.client.delete("/api/participants/urn:test:other", headers=world.admin).status_code == 404
    assert snapshot(world) == before


def test_concurrent_registrations_are_serialised_and_one_failing_leaves_the_other_whole(world):
    """The first to save fails. Without the lock, its undo takes away what the second one relies on."""
    calls = 0
    original = world.registry.handle

    def first_save_fails(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        if request.method == "POST":
            calls += 1
            if calls == 1:
                return httpx.Response(500, json={})
        return original(request)

    world.registry.handle = first_save_fails

    async def both():
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://m", headers=world.admin) as client:
            body = {"participant_id": ID, "participant_type": "factory_owner"}
            return await asyncio.gather(*(client.post("/api/participants", json=body) for _ in range(2)))

    answers = asyncio.run(both())
    assert sorted(answer.status_code for answer in answers) == [200, 503]
    assert set(world.kubernetes.objects) == OBJECTS
    assert world.databases.names == {f"adapter_{NAME}", f"edc_{NAME}"}
    assert world.keycloak.client_of(ID) and ID in world.registry.records


def test_concurrent_requests_for_different_participants_all_finish(world):
    async def many():
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://m", headers=world.admin) as client:
            return await asyncio.gather(
                *(
                    client.post(
                        "/api/participants", json={"participant_id": f"urn:p:{n}", "participant_type": "factory_owner"}
                    )
                    for n in range(8)
                )
            )

    assert [answer.status_code for answer in asyncio.run(many())] == [200] * 8
    assert len(world.registry.records) == 8


def test_adding_a_participant_changes_nothing_of_another(world):
    world.register()
    before = {key: value["metadata"]["resourceVersion"] for key, value in world.kubernetes.objects.items()}
    world.register("urn:test:mb", "machine_builder")
    after = {key: value["metadata"]["resourceVersion"] for key, value in world.kubernetes.objects.items()}
    assert {key: after[key] for key in before} == before


def test_demo_creates_the_named_participants_and_repeats_with_the_same_credentials():
    world = World(demo_participants=[("urn:d:fo", "factory_owner"), ("urn:d:mb", "machine_builder")])
    first = world.client.post("/api/demo", headers=world.admin)
    assert first.status_code == 200
    assert {entry["participant_id"] for entry in first.json()} == {"urn:d:fo", "urn:d:mb"}
    second = world.client.post("/api/demo", headers=world.admin).json()
    assert {e["client_secret"] for e in second} == {e["client_secret"] for e in first.json()}


def test_demo_with_none_configured_gives_an_empty_list(world):
    answer = world.client.post("/api/demo", headers=world.admin)
    assert answer.status_code == 200 and answer.json() == []


def test_demo_reports_a_failure_and_undoes_only_the_one_that_failed():
    world = World(demo_participants=[("urn:d:fo", "factory_owner"), ("urn:d:mb", "machine_builder")])
    world.kubernetes.never_available = {manifests.adapter_name("urn:d:mb")}
    assert world.client.post("/api/demo", headers=world.admin).status_code == 502
    assert "urn:d:fo" in world.registry.records
    world.nothing_of("urn:d:mb")


def test_demo_configuration_is_parsed():
    from app.config import parse_demo_participants

    assert parse_demo_participants("urn:a:b=factory_owner, c=machine_builder,") == [
        ("urn:a:b", "factory_owner"),
        ("c", "machine_builder"),
    ]
    with pytest.raises(ValueError):
        parse_demo_participants("no-type")


def test_removing_a_hosted_participant_leaves_nothing(world):
    world.register()
    world.buckets.names.add(f"participant-{NAME}")
    assert world.client.delete(f"/api/participants/{ID}", headers=world.admin).status_code == 204
    world.nothing_of(ID)
    assert not world.buckets.names


def test_deployments_are_removed_with_their_pods(world):
    world.register()
    world.client.delete(f"/api/participants/{ID}", headers=world.admin)
    gets_after_delete = [call for call in world.kubernetes.calls if call.endswith("/pods")]
    assert gets_after_delete, "It looks for remaining pods"


def test_removing_an_external_participant(world):
    world.register(hosted=False, adapter_url="http://a", dsp_url="http://d")
    world.kubernetes.calls.clear()
    assert world.client.delete(f"/api/participants/{ID}", headers=world.admin).status_code == 204
    world.nothing_of(ID)
    assert not world.kubernetes.calls
    assert not world.buckets.removed


def test_removing_something_unknown_gives_404(world):
    assert world.client.delete("/api/participants/urn:none", headers=world.admin).status_code == 404


@pytest.mark.parametrize("failing", ["database", "kubernetes", "keycloak"])
def test_a_failing_step_is_named_the_others_run_and_a_repeat_finishes(world, failing):
    world.register()
    if failing == "database":
        world.databases.fail_drop = True
    elif failing == "kubernetes":
        world.kubernetes.fail = re.compile("DELETE .*/deployments/")
    else:
        world.keycloak.fail = re.compile("DELETE .*/clients/")
    answer = world.client.delete(f"/api/participants/{ID}", headers=world.admin)
    assert answer.status_code == 502
    assert {"database": "database", "kubernetes": "Deployment", "keycloak": "client"}[failing] in answer.json()[
        "detail"
    ]
    assert ID not in world.registry.records, "The other steps ran"
    world.databases.fail_drop = False
    world.kubernetes.fail = world.keycloak.fail = None
    assert world.client.delete(f"/api/participants/{ID}", headers=world.admin).status_code == 204
    world.nothing_of(ID)


def test_a_token_that_cant_administer_keycloak_removes_nothing(world):
    world.register()
    world.keycloak.refuse_admin = True
    answer = world.client.delete(f"/api/participants/{ID}", headers=world.admin)
    assert answer.status_code == 403
    assert ID in world.registry.records and set(world.kubernetes.objects) == OBJECTS


def test_a_token_that_cant_administer_keycloak_creates_nothing(world):
    world.keycloak.refuse_admin = True
    assert world.register().status_code == 403
    assert not world.databases.names and not world.kubernetes.objects


def test_removal_does_not_touch_a_foreign_client(world):
    world.keycloak.add_foreign_client(ID)
    assert world.client.delete(f"/api/participants/{ID}", headers=world.admin).status_code == 404
    assert world.keycloak.client_of(ID)


def test_two_participants_registered_and_deleted_leave_no_orphans(world):
    world.register()
    world.register("urn:test:mb", "machine_builder")
    for participant in (ID, "urn:test:mb"):
        assert world.client.delete(f"/api/participants/{participant}", headers=world.admin).status_code == 204
    assert not world.kubernetes.objects and not world.databases.names and not world.registry.records
    assert not world.keycloak.clients and not world.keycloak.roles


def expiring_during_the_wait(world, seconds: int = 400):
    """The caller's token runs out while pods are awaited, as it does by default: both are 5 minutes."""
    real = world.services.provisioner.kubernetes.wait_available

    async def wait(name, limit):
        try:
            await real(name, limit)
        finally:
            world.keycloak.seconds_ahead = seconds

    world.services.provisioner.kubernetes.wait_available = wait


def test_a_token_that_expires_during_the_wait_does_not_stop_the_undo(world):
    world.kubernetes.never_available.add(f"connector-{NAME}")
    expiring_during_the_wait(world)
    answer = world.register()
    assert answer.status_code == 502
    assert "could not be undone" not in answer.json()["detail"]
    world.nothing_of(ID)


def test_with_no_credential_of_its_own_it_names_what_is_left(world):
    world.services.provisioner.settings = dataclasses.replace(world.settings, management_client_secret="")
    world.kubernetes.never_available.add(f"connector-{NAME}")
    expiring_during_the_wait(world)
    detail = world.register().json()["detail"]
    assert "so DELETE it" in detail and "client" in detail and "realm role" in detail


def test_a_removal_with_a_token_that_expires_during_its_wait(world):
    world.register()
    real = world.services.provisioner.kubernetes.wait_gone

    async def wait(*args):
        await real(*args)
        world.keycloak.seconds_ahead = 400

    world.services.provisioner.kubernetes.wait_gone = wait
    assert world.client.delete(f"/api/participants/{ID}", headers=world.admin).status_code == 204
    world.keycloak.seconds_ahead = 0
    world.nothing_of(ID)


def test_undo_runs_latest_first_and_waits_for_pods_before_what_they_use(world):
    order = []
    provisioner = world.services.provisioner
    real_gone, real_drop = provisioner.kubernetes.wait_gone, world.databases.drop
    real_bucket = world.buckets.remove

    async def gone(*args):
        order.append("pods")
        await real_gone(*args)

    async def drop(name):
        order.append("database")
        return await real_drop(name)

    async def bucket(name):
        order.append("bucket")
        return await real_bucket(name)

    provisioner.kubernetes.wait_gone, world.databases.drop, world.buckets.remove = gone, drop, bucket
    world.registry.fail_save = True
    assert world.register().status_code == 503
    assert order[0] == "pods", order
    assert order.index("pods") < order.index("bucket") < order.index("database"), order


def test_a_registration_has_one_deadline(world):
    world.services.provisioner.settings = dataclasses.replace(world.settings, ready_seconds=0.5)
    world.kubernetes.never_available.update({f"connector-{NAME}", f"adapter-{NAME}"})
    began = asyncio.run(_timed(world))
    assert began < 1.0, f"It took {began}s, with a deadline of 0.5s"


async def _timed(world) -> float:
    import time

    start = time.monotonic()
    await asyncio.to_thread(world.register)
    return time.monotonic() - start


def test_an_undo_with_no_time_left_names_what_it_did_not_do(world, monkeypatch):
    from app import provisioning

    monkeypatch.setattr(provisioning, "UNDO_SECONDS", 0.01)
    real = world.services.provisioner.kubernetes.wait_gone

    async def slow(*args):
        await asyncio.sleep(0.05)
        await real(*args)

    world.services.provisioner.kubernetes.wait_gone = slow
    world.registry.fail_save = True
    assert "so DELETE it" in world.register().json()["detail"]


def test_a_changed_secret_restarts_pods_and_an_unchanged_one_does_not(world):
    def templates():
        return {name: world.kubernetes.objects[("Deployment", name)]["spec"]["template"]
                for name in (f"adapter-{NAME}", f"connector-{NAME}")}  # fmt: skip

    world.register()
    first = templates()
    world.register()
    assert templates() == first
    world.services.provisioner.settings = dataclasses.replace(world.settings, adapter_internal_key="a new key")
    world.register()
    second = templates()
    for name, template in second.items():
        assert template["metadata"]["annotations"] != first[name]["metadata"]["annotations"], name


def test_reachable_without_a_peer_address_is_refused(world):
    world.services.provisioner.settings = dataclasses.replace(world.settings, gateway_peer_url="")
    assert world.register(externally_reachable=True).status_code == 422
    world.nothing_of(ID)


@pytest.mark.parametrize(
    "participant_id",
    ["a/credentials", "compatible/x", "compatible", "..", ".", "$(id)", "café", "-a", "a b", "a%2Fb", "a?b", "a#b"],
)
def test_ids_that_would_not_work_are_refused(world, participant_id):
    assert world.register(participant_id, hosted=False, adapter_url="http://x", dsp_url="http://y").status_code == 422
    assert participant_id not in world.registry.records


@pytest.mark.parametrize("participant_id", ["urn:ifric:ifx-eur-com-own-1", "urn:example:a.b_c", "A1"])
def test_ids_in_use_are_taken_and_can_be_read(world, participant_id):
    assert world.register(participant_id, hosted=False, adapter_url="http://x", dsp_url="http://y").status_code == 200
    assert world.client.get(f"/api/participants/{participant_id}").json()["participant_id"] == participant_id


def test_a_removal_the_registry_refuses_is_not_called_removed(world):
    world.register()
    world.registry.delete_status = 405
    answer = world.client.delete(f"/api/participants/{ID}", headers=world.admin)
    assert answer.status_code == 502
    assert ID in world.registry.records


@pytest.mark.parametrize("path", ["..", ".", "a%2Fb", "compatible"])
def test_removing_what_can_not_be_an_id_is_not_found(world, path):
    assert world.client.delete(f"/api/participants/{path}", headers=world.admin).status_code in (404, 405)
