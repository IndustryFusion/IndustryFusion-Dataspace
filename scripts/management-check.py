#!/usr/bin/env python3
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
"""Checks the management API on a real cluster: everything goes through its routes, as an administrator would.

Registers two participants, exchanges a message through the gateway, resets access through the management
routes, injects failures at each provisioning step, and deletes the participants. After each removal it looks
for what remains in Kubernetes, PostgreSQL, Keycloak and storage. Needs scripts/local-env.sh up and services.
"""

import argparse
import base64
import json
import sys
import urllib.parse

import local_cluster as lc

OWNER, BUILDER = "urn:mgmt-check:factory-owner", "urn:mgmt-check:machine-builder"
SPARE = "urn:mgmt-check:spare"
ADMIN_CLIENT = "dataspace-admin-cli"


def quoted(participant_id: str) -> str:
    return urllib.parse.quote(participant_id, safe=":")


def expect(what: str, status: int, wanted: int, body: object = None) -> None:
    if status != wanted:
        raise AssertionError(f"{what}: got {status}, wanted {wanted}: {body}")
    print(f"PASS {what}: {status}")


class Check:
    def __init__(self, management: str, keycloak: str, gateway: str, token: str) -> None:
        self.management, self.keycloak, self.gateway = management, keycloak, gateway
        self.admin = {"Authorization": f"Bearer {token}"}

    def api(self, method: str, path: str, body: object = None):
        return lc.http(method, f"{self.management}{path}", body, self.admin)

    def register(self, participant_id: str, kind: str, **fields):
        body = {"participant_id": participant_id, "participant_type": kind, **fields}
        return self.api("POST", "/api/participants", body)

    def agent_headers(self, participant_id: str, secret: str) -> dict[str, str]:
        form = {"grant_type": "client_credentials", "client_id": participant_id, "client_secret": secret}
        status, token = lc.http_form(f"{self.keycloak}/realms/dataspace/protocol/openid-connect/token", form)
        assert status == 200, token
        return {"Authorization": f"Bearer {token['access_token']}"}

    def remains(self, participant_id: str) -> list[str]:
        """Everything still present for this participant, in each of the four places it could be."""
        name = lc.slug(participant_id)
        found = []
        listed = lc.kubectl(
            "-n", lc.PARTICIPANTS, "get", "deployments,services,secrets,configmaps,pods", "-o", "name",
        )  # fmt: skip
        found += [line for line in listed.splitlines() if name in line]
        user = lc.credentials()["POSTGRES_USER"]
        databases = lc.kubectl(
            "-n", "iff", "exec", "deploy/acid-cluster", "--", "psql", "-U", user, "-d", "postgres", "-Atc",
            "SELECT datname FROM pg_database",
        )  # fmt: skip
        found += [f"database {line}" for line in databases.split() if name in line]
        admin = lc.KeycloakAdmin(self.keycloak)
        if admin.client_uuid(participant_id):
            found.append("client")
        status, _ = admin._call("GET", f"/roles/{urllib.parse.quote('participant:' + participant_id, safe='')}")
        if status != 404:
            found.append("realm role")
        status, _ = lc.http("GET", f"{self.management}/api/participants/{quoted(participant_id)}")
        if status != 404:
            found.append("registry entry")
        return found

    def assert_gone(self, participant_id: str) -> None:
        def clean():
            return not self.remains(participant_id)

        try:
            lc.poll(clean, timeout=120, interval=2, what="removal")
        except TimeoutError:
            raise AssertionError(f"Left behind for {participant_id}: {self.remains(participant_id)}") from None
        print(f"PASS nothing remains of {participant_id}")

    def buckets(self) -> list[str]:
        secrets = lc.credentials()
        script = (
            "import boto3,sys;c=boto3.client('s3',endpoint_url='http://seaweedfs.iff:80',"
            f"aws_access_key_id='{secrets['S3_ACCESS_KEY']}',aws_secret_access_key='{secrets['S3_SECRET_KEY']}',"
            "region_name='us-east-1');print(' '.join(b['Name'] for b in c.list_buckets()['Buckets']))"
        )
        return lc.kubectl("-n", "dataspace", "exec", "deploy/management", "--", "python", "-c", script).split()


def versions(*names: str) -> dict[str, str]:
    listed = lc.kubectl(
        "-n", lc.PARTICIPANTS, "get", "deployments,services,secrets,configmaps", "-o",
        "custom-columns=KIND:.kind,NAME:.metadata.name,VERSION:.metadata.resourceVersion", "--no-headers",
    )  # fmt: skip
    result = {}
    for line in listed.splitlines():
        kind, name, version = line.split()
        if any(wanted in name for wanted in names):
            result[f"{kind}/{name}"] = version
    return result


def exchange(check: Check, owner_secret: str, builder_secret: str) -> None:
    owner = check.agent_headers(OWNER, owner_secret)
    builder = check.agent_headers(BUILDER, builder_secret)
    status, sent = lc.http(
        "POST",
        f"{check.gateway}/outbox/messages",
        {"receiver_participant": BUILDER, "performative": "request", "reply_expected": True, "payload": {"q": "hello"}},
        owner,
    )
    expect("the factory owner sends", status, 202, sent)

    def arrived():
        _, inbox = lc.http("GET", f"{check.gateway}/inbox/messages?status=received", headers=builder)
        return next((m for m in inbox if m["message_id"] == sent["message_id"]), None)

    message = lc.poll(arrived, timeout=120, what="the message")
    assert message["payload"] == {"q": "hello"}, message
    print("PASS the machine builder receives it")


def capability_reset(check: Check, owner_secret: str, builder_secret: str) -> None:
    builder = check.agent_headers(BUILDER, builder_secret)

    def access() -> dict:
        status, entries = lc.http("GET", f"{check.gateway}/capabilities/access?provider={OWNER}", headers=builder)
        assert status == 200, entries
        return {entry["capability"]: entry for entry in entries}

    capability = "twin:history"
    assert access()[capability]["status"] == "on-request"
    status, answer = lc.http(
        "POST",
        f"{check.gateway}/capabilities/requests",
        {"provider_participant": OWNER, "capability": capability},
        builder,
    )
    expect("the machine builder asks for access", status, 202, answer)
    status, state = check.call("GET", f"/api/participants/{quoted(OWNER)}/capabilities")
    expect("capabilities read with no token", status, 200, state)
    approval = next(a for a in state["approvals"] if a["consumer_id"] == BUILDER and a["capability"] == capability)
    path = f"/api/participants/{quoted(OWNER)}/approvals/{approval['id']}"
    status, answer = check.api("PATCH", path, {"action": "approve"})
    expect("approve through the management route", status, 200, answer)
    assert access()[capability]["status"] == "approved"
    status, answer = check.api("PATCH", path, {"action": "deny"})
    expect("deciding a resolved request gives 409", status, 409, answer)

    status, view = check.call("GET", f"/api/policy?fo={OWNER}&mb={BUILDER}")
    expect("policy view with no token", status, 200, view)
    entry = next(e for e in view["capabilities"] if e["capability"] == capability)
    assert entry["status"] == "approved" and entry["approval_id"] == approval["id"], entry

    status, answer = check.api("PATCH", path, {"action": "reset"})
    expect("reset through the management route", status, 200, answer)
    after = access()[capability]
    assert after["status"] == "on-request" and after["source"] == "default", after
    print("PASS reset takes access back to the default, as the agent sees it")
    status, answer = check.api("PATCH", path, {"action": "reset"})
    expect("a second reset of the same id finds nothing", status, 404, answer)

    status, answer = check.api(
        "POST",
        f"/api/participants/{quoted(OWNER)}/approvals",
        {"consumer_id": BUILDER, "capability": capability, "action": "deny"},
    )
    expect("record a decision through the management route", status, 200, answer)
    assert access()[capability]["status"] == "denied"
    status, state = check.call("GET", f"/api/participants/{quoted(OWNER)}/capabilities")
    denied = next(a for a in state["approvals"] if a["consumer_id"] == BUILDER and a["capability"] == capability)
    denied_path = f"/api/participants/{quoted(OWNER)}/approvals/{denied['id']}"
    status, answer = check.api("PATCH", denied_path, {"action": "reset"})
    expect("reset that decision", status, 200, answer)
    assert access()[capability]["source"] == "default"

    capability_path = f"/api/participants/{quoted(OWNER)}/capabilities/{capability}"
    status, answer = check.api("PATCH", capability_path, {"default_policy": "auto"})
    expect("change a default", status, 200, answer)
    assert access()[capability]["status"] == "auto"
    status, answer = check.api("PATCH", capability_path, {"default_policy": "on-request"})
    expect("change it back", status, 200, answer)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--admin-secret-file", default=str(lc.LOCAL / "admin-client-secret"))
    args = parser.parse_args()
    with open(args.admin_secret_file) as handle:
        admin_secret = handle.read().strip()

    with lc.port_forward("iff", "keycloak-service", 8080) as keycloak_base:
        keycloak = f"{keycloak_base}/auth"
        with lc.port_forward("dataspace", "gateway", 8080) as gateway:
            # Tokens from this address have the configured issuer, as Keycloak's hostname is fixed.
            def connect(base: str) -> Check:
                status, token = lc.http(
                    "POST", f"{base}/api/admin/token", {"client_id": ADMIN_CLIENT, "client_secret": admin_secret}
                )
                expect("admin token", status, 200, token)
                return Check(base, keycloak, gateway, token["access_token"])

            with lc.port_forward("dataspace", "management", 3000) as management:
                check = connect(management)
                # What an interrupted run left behind.
                for participant in (OWNER, BUILDER, SPARE):
                    check.api("DELETE", f"/api/participants/{quoted(participant)}")
                try:
                    status, health = lc.http("GET", f"{management}/api/health")
                    expect("health", status, 200, health)
                    assert health["status"] == "ok", health

                    status, answer = lc.http("POST", f"{management}/api/participants", {})
                    expect("no token on an admin route", status, 401, answer)

                    status, owner = check.register(OWNER, "factory_owner")
                    expect("register a factory owner", status, 200, owner)
                    before = versions(lc.slug(OWNER))
                    status, builder = check.register(BUILDER, "machine_builder")
                    expect("register a machine builder", status, 200, builder)
                    assert versions(lc.slug(OWNER)) == before, "the first participant's objects changed"
                    print("PASS adding a participant changes nothing of an existing one")

                    status, compatible = lc.http("GET", f"{management}/api/participants/compatible/{quoted(OWNER)}")
                    assert [c["participant_id"] for c in compatible] == [BUILDER], compatible
                    print("PASS the new participant is found through the registry")

                    exchange(check, owner["client_secret"], builder["client_secret"])
                    capability_reset(check, owner["client_secret"], builder["client_secret"])

                    status, again = check.register(OWNER, "factory_owner", externally_reachable=True)
                    expect("set reachability by registering again", status, 200, again)
                    assert again["client_secret"] == owner["client_secret"]
                    assert again["peer_notify_url"].endswith(f"/peer/{OWNER}"), again
                    status, again = check.register(OWNER, "factory_owner", externally_reachable=False)
                    expect("set it back", status, 200, again)

                    status, credentials = check.api("GET", f"/api/participants/{quoted(BUILDER)}/credentials")
                    expect("read credentials", status, 200, credentials)
                    assert credentials["client_secret"] == builder["client_secret"]
                    assert lc.slug(OWNER) and f"participant-{lc.slug(OWNER)}" in check.buckets()
                    print("PASS the adapter made its bucket")
                finally:
                    for participant in (OWNER, BUILDER):
                        status, answer = check.api("DELETE", f"/api/participants/{quoted(participant)}")
                        print("delete", participant, status, answer or "")
                for participant in (OWNER, BUILDER):
                    check.assert_gone(participant)
                remaining = [b for b in check.buckets() if lc.slug(OWNER) in b or lc.slug(BUILDER) in b]
                assert not remaining, remaining
                print("PASS their buckets are gone")

                status, answer = check.api("DELETE", f"/api/participants/{quoted(OWNER)}")
                expect("deleting again finds nothing", status, 404, answer)

            # A restart ends a port-forward, so each failure below runs on a forward of its own.
            run_failures(connect)
    print("All management checks passed")
    return 0


def run_failures(connect) -> None:
    def step(prepare, what, wanted, cleanup):
        prepare()
        with lc.port_forward("dataspace", "management", 3000) as management:
            check = connect(management)
            try:
                status, answer = check.register(SPARE, "factory_owner")
                expect(what, status, wanted, answer)
            finally:
                cleanup()
        with lc.port_forward("dataspace", "management", 3000) as management:
            connect(management).assert_gone(SPARE)

    def restart_with(*assignments: str):
        def apply_it() -> None:
            lc.kubectl("-n", "dataspace", "set", "env", "deploy/management", *assignments)
            lc.wait_ready("dataspace", "management")

        return apply_it

    restore_password = (
        '{"spec":{"template":{"spec":{"containers":[{"name":"management","env":[{"name":"POSTGRES_PASSWORD",'
        '"value":null,"valueFrom":{"secretKeyRef":{"name":"service-credentials","key":"postgres-password"}}}]}]}}}}'
    )

    def put_password_back() -> None:
        lc.kubectl("-n", "dataspace", "patch", "deploy/management", "--type=strategic", "-p", restore_password)
        lc.wait_ready("dataspace", "management")

    step(restart_with("POSTGRES_PASSWORD=wrong"), "databases step: a wrong password fails", 503, put_password_back)

    saved: list[str] = []

    def remove_rights() -> None:
        saved.append(lc.kubectl("-n", lc.PARTICIPANTS, "get", "rolebinding", "management", "-o", "yaml"))
        lc.kubectl("-n", lc.PARTICIPANTS, "delete", "rolebinding", "management")

    step(remove_rights, "Kubernetes step: no rights fails", 502, lambda: lc.apply(saved[0]))

    step(
        restart_with("MAIN_VERSION=does-not-exist", "PROVISION_READY_SECONDS=20"),
        "availability: an image that can't be pulled fails",
        502,
        restart_with("MAIN_VERSION=dev", "PROVISION_READY_SECONDS=300"),
    )

    def registry_replicas(count: int):
        def scale() -> None:
            lc.kubectl("-n", "dataspace", "scale", "deploy/registry", f"--replicas={count}")
            if count:
                lc.wait_ready("dataspace", "registry")
            else:
                pods = ("-n", "dataspace", "get", "pods", "-l", "app=registry", "-o", "name")
                lc.poll(lambda: not lc.kubectl(*pods).strip(), 90, what="the registry to stop")

        return scale

    step(registry_replicas(0), "registry down: refused before anything changes", 503, registry_replicas(1))

    print("PASS failures at each step were undone")

    keycloak_step(connect)
    half_finished_client(connect)
    failed_re_registration(connect, restart_with)


def keycloak_step(connect) -> None:
    """A real token with the admin role and no rights in Keycloak is refused before anything is made."""
    with lc.port_forward("dataspace", "management", 3000) as management:
        check = connect(management)
        keycloak = lc.KeycloakAdmin(check.keycloak)
        name = "mgmt-check-weak-admin"
        status, answer = keycloak._call(
            "POST", "/clients", {"clientId": name, "publicClient": False, "serviceAccountsEnabled": True}
        )
        assert status == 201, answer
        uuid = keycloak.client_uuid(name)
        try:
            _, account = keycloak._call("GET", f"/clients/{uuid}/service-account-user")
            _, role = keycloak._call("GET", "/roles/dataspace-admin")
            keycloak._call("POST", f"/users/{account['id']}/role-mappings/realm", [role])
            _, secret = keycloak._call("GET", f"/clients/{uuid}/client-secret")
            status, token = lc.http(
                "POST", f"{management}/api/admin/token", {"client_id": name, "client_secret": secret["value"]}
            )
            expect("a token with the role and no Keycloak rights", status, 200, token)
            weak = Check(management, check.keycloak, check.gateway, token["access_token"])
            status, answer = weak.register(SPARE, "factory_owner")
            expect("Keycloak step: no rights in Keycloak fails", status, 403, answer)
            check.assert_gone(SPARE)
        finally:
            keycloak._call("DELETE", f"/clients/{uuid}")


def half_finished_client(connect) -> None:
    with lc.port_forward("dataspace", "management", 3000) as management:
        check = connect(management)
        keycloak = lc.KeycloakAdmin(check.keycloak)
        status, answer = keycloak._call(
            "POST",
            "/clients",
            {
                "clientId": SPARE,
                "publicClient": False,
                "serviceAccountsEnabled": False,
                "attributes": {"dataspace.participant_id": SPARE},
            },
        )
        assert status == 201, answer
        try:
            status, record = check.register(SPARE, "factory_owner")
            expect("a half-finished client is completed", status, 200, record)
            claims = check.agent_headers(SPARE, record["client_secret"])["Authorization"].split(".")[1]
            decoded = json.loads(base64.urlsafe_b64decode(claims + "=" * (-len(claims) % 4)))
            assert decoded["participant_id"] == SPARE, decoded
            assert f"participant:{SPARE}" in decoded["realm_access"]["roles"], decoded
            print("PASS its token carries the claim and the role")
        finally:
            status, answer = check.api("DELETE", f"/api/participants/{quoted(SPARE)}")
            expect("removing it", status, 204, answer)
        check.assert_gone(SPARE)


def failed_re_registration(connect, restart_with) -> None:
    """A real participant, its pods running, and a registration that fails on a wrong image."""
    with lc.port_forward("dataspace", "management", 3000) as management:
        status, record = connect(management).register(SPARE, "factory_owner")
        expect("a participant to register again", status, 200, record)
    name = lc.slug(SPARE)
    deployment = f"adapter-{name}"
    image = (
        "-n",
        lc.PARTICIPANTS,
        "get",
        "deployment",
        deployment,
        "-o",
        "jsonpath={.spec.template.spec.containers[0].image}",
    )
    before = lc.kubectl(*image)
    restart_with("MAIN_VERSION=does-not-exist", "PROVISION_READY_SECONDS=15")()
    try:
        with lc.port_forward("dataspace", "management", 3000) as management:
            status, answer = connect(management).register(SPARE, "factory_owner")
            expect("registering again with a wrong image fails", status, 502, answer)
    finally:
        restart_with("MAIN_VERSION=dev", "PROVISION_READY_SECONDS=300")()
    assert lc.kubectl(*image) == before, "the image was not put back"
    lc.wait_ready(lc.PARTICIPANTS, deployment)
    with lc.port_forward("dataspace", "management", 3000) as management:
        check = connect(management)
        user = lc.credentials()["POSTGRES_USER"]
        query = f"SELECT count(*) FROM pg_database WHERE datname IN ('adapter_{name}', 'edc_{name}')"
        kept = lc.kubectl(
            "-n", "iff", "exec", "deploy/acid-cluster", "--", "psql", "-U", user, "-d", "postgres", "-Atc", query
        )
        assert kept.strip() == "2", kept
        print("PASS the databases and image of the existing participant remain")
        again = lc.http("GET", f"{management}/api/participants/{quoted(SPARE)}/credentials", headers=check.admin)[1]
        assert again["client_secret"] == record["client_secret"], "the credentials changed"
        print("PASS its credentials remain")
        status, answer = check.api("DELETE", f"/api/participants/{quoted(SPARE)}")
        expect("removing it", status, 204, answer)
        check.assert_gone(SPARE)


if __name__ == "__main__":
    sys.exit(main())
