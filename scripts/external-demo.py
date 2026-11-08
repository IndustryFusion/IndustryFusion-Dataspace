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
"""Deploys and removes two self-hosted participants on the local environment from scripts/local-env.sh.

    external-demo.py up      Deploy both, each in its own namespace, and register them. It can be repeated
    external-demo.py down    Remove both, and their registrations. Hosted participants aren't touched
    external-demo.py check   Try connections from real pods, to show that the NetworkPolicy is enforced

Their ids and client secrets go in .local/external-demo.json, which contract_test.py --local reads. Images are
dataspace/<name>:<DATASPACE_IMAGE_VERSION>, by default dev, as scripts/local-env.sh images loads them.
"""

import json
import os
import subprocess
import sys
import textwrap
import urllib.parse
from secrets import token_hex

import local_cluster as lc

STATE = lc.LOCAL / "external-demo.json"
PARTICIPANTS = {
    "external-machine-builder": ("urn:demo:external-machine-builder", "machine_builder"),
    "external-factory-owner": ("urn:demo:external-factory-owner", "factory_owner"),
}


def admin_token(management: str) -> str:
    secret = (lc.LOCAL / "admin-client-secret").read_text().strip()
    body = {"client_id": "dataspace-admin-cli", "client_secret": secret}
    status, answer = lc.http("POST", f"{management}/api/admin/token", body)
    if status != 200:
        raise SystemExit(f"No admin token: {status} {answer}")
    return answer["access_token"]


def existing_secret(namespace: str, key: str) -> str | None:
    """A value this participant already has, so that repeating this doesn't change what its pods hold."""
    try:
        return lc.kubectl(
            "-n", namespace, "get", "secret", "credentials", "--ignore-not-found",
            "-o", f"go-template={{{{index .data \"{key}\" | base64decode}}}}",
        ).strip() or None  # fmt: skip
    except RuntimeError:
        return None


def up() -> int:
    version = os.environ.get("DATASPACE_IMAGE_VERSION", "dev")
    state = {}
    with lc.port_forward("dataspace", "management", 3000) as management:
        token = admin_token(management)
        for namespace, (participant_id, participant_type) in PARTICIPANTS.items():
            status, record = lc.http(
                "POST",
                f"{management}/api/participants",
                {
                    "participant_id": participant_id,
                    "participant_type": participant_type,
                    "hosted": False,
                    "adapter_url": f"http://adapter.{namespace}:8000",
                    "dsp_url": f"http://connector.{namespace}:8082/api/v1/dsp",
                },
                {"Authorization": f"Bearer {token}"},
            )
            if status != 200:
                raise SystemExit(f"Could not register {participant_id}: {status} {record}")
            url = f"http://connector.{namespace}"
            lc.apply(
                lc.render(
                    "external-participant.yaml.template",
                    NAMESPACE=namespace,
                    PARTICIPANTS_NAMESPACE=lc.PARTICIPANTS,
                    PARTICIPANT_ID=participant_id,
                    PARTICIPANT_TYPE=participant_type,
                    IMAGE_VERSION=version,
                    CLIENT_SECRET=record["client_secret"],
                    POSTGRES_PASSWORD=existing_secret(namespace, "postgres-password") or token_hex(24),
                    EDC_API_KEY=existing_secret(namespace, "edc-api-key") or token_hex(24),
                    S3_ACCESS_KEY=existing_secret(namespace, "s3-access-key") or token_hex(12),
                    S3_SECRET_KEY=existing_secret(namespace, "s3-secret-key") or token_hex(24),
                    INTERNAL_KEY=existing_secret(namespace, "internal-key") or token_hex(24),
                    CONNECTOR_PROPERTIES=textwrap.indent(lc.connector_properties(participant_id, url), "    "),
                )
            )
            state[namespace] = {"participant_id": participant_id, "client_secret": record["client_secret"]}
    for namespace in PARTICIPANTS:
        for deployment in ("postgres", "storage", "connector", "adapter"):
            lc.wait_ready(namespace, deployment)
    STATE.touch(mode=0o600)
    STATE.write_text(json.dumps(state))
    print(f"Up: {', '.join(PARTICIPANTS)}. Ids and secrets are in {STATE}")
    return 0


def down() -> int:
    with lc.port_forward("dataspace", "management", 3000) as management:
        token = admin_token(management)
        for participant_id, _ in PARTICIPANTS.values():
            quoted = urllib.parse.quote(participant_id, safe=":")
            status, answer = lc.http(
                "DELETE", f"{management}/api/participants/{quoted}", None, {"Authorization": f"Bearer {token}"}
            )
            if status not in (204, 404):
                print(f"Could not remove {participant_id}: {status} {answer}", file=sys.stderr)
    for namespace in PARTICIPANTS:
        lc.kubectl("delete", "namespace", namespace, "--ignore-not-found")
    STATE.unlink(missing_ok=True)
    print("Down")
    return 0


def reaches(namespace: str, deployment: str, host: str, port: int) -> bool:
    """Whether a connection can be opened from that pod. A blocked one times out."""
    code = (
        "import socket, sys\n"
        "s = socket.socket(); s.settimeout(4)\n"
        f"sys.exit(s.connect_ex(({host!r}, {port})) != 0)\n"
    )
    process = subprocess.run(
        [
            "kubectl", "--kubeconfig", str(lc.KUBECONFIG), "-n", namespace, "exec", f"deploy/{deployment}",
            "--", "python", "-c", code,
        ],  # fmt: skip
        capture_output=True,
        text=True,
    )
    if process.returncode not in (0, 1) or (process.returncode == 1 and "Traceback" in process.stderr):
        raise SystemExit(f"Could not try {host}:{port} from {namespace}: {process.stderr}")
    return process.returncode == 0


def check() -> int:
    """Each answer is compared with what the policy says, from both sides of it, with a hosted participant running."""
    probe = "urn:demo:policy-probe"
    failures = 0

    def expect(namespace: str, deployment: str, host: str, port: int, wanted: bool) -> None:
        nonlocal failures
        found = reaches(namespace, deployment, host, port)
        failures += found != wanted
        word = "open" if found else "closed"
        print(f"{'ok  ' if found == wanted else 'FAIL'} {namespace}/{deployment} -> {host}:{port}: {word}")

    with lc.port_forward("dataspace", "management", 3000) as management:
        headers = {"Authorization": f"Bearer {admin_token(management)}"}
        body = {"participant_id": probe, "participant_type": "factory_owner"}
        status, answer = lc.http("POST", f"{management}/api/participants", body, headers)
        if status != 200:
            raise SystemExit(f"Could not register a hosted participant: {status} {answer}")
        try:
            name = lc.slug(probe)
            hosted_adapter = f"adapter-{name}.{lc.PARTICIPANTS}"
            hosted_connector = f"connector-{name}.{lc.PARTICIPANTS}"
            for namespace in PARTICIPANTS:
                # The public routes.
                expect(namespace, "adapter", "gateway.dataspace", 8080, True)
                expect(namespace, "adapter", "dsp-gateway.dataspace", 8085, True)
                expect(namespace, "adapter", "management.dataspace", 3000, True)
                expect(namespace, "adapter", "keycloak-service.iff", 8080, True)
                # What it runs itself.
                expect(namespace, "adapter", "postgres", 5432, True)
                expect(namespace, "adapter", "connector", 8081, True)
                # Everything else in the hub.
                expect(namespace, "adapter", hosted_adapter, 8000, False)
                expect(namespace, "adapter", hosted_connector, 8082, False)
                expect(namespace, "adapter", hosted_connector, 8084, False)
                expect(namespace, "adapter", "registry.dataspace", 19000, False)
                expect(namespace, "adapter", "acid-cluster.iff", 5432, False)
                expect(namespace, "adapter", "seaweedfs.iff", 80, False)
            hosted = f"adapter-{name}"
            for namespace in PARTICIPANTS:
                # From a hosted pod, what connectors use is open, and nothing else.
                expect(lc.PARTICIPANTS, hosted, f"adapter.{namespace}", 8000, True)
                expect(lc.PARTICIPANTS, hosted, f"connector.{namespace}", 8082, True)
                expect(lc.PARTICIPANTS, hosted, f"connector.{namespace}", 8081, False)
                expect(lc.PARTICIPANTS, hosted, f"connector.{namespace}", 8083, False)
                expect(lc.PARTICIPANTS, hosted, f"postgres.{namespace}", 5432, False)
                expect(lc.PARTICIPANTS, hosted, f"storage.{namespace}", 80, False)
            for namespace in PARTICIPANTS:
                # The gateway's peer route reaches the adapter, and nothing else of it.
                expect("dataspace", "gateway", f"adapter.{namespace}", 8000, True)
                expect("dataspace", "gateway", f"connector.{namespace}", 8081, False)
                expect("dataspace", "gateway", f"postgres.{namespace}", 5432, False)
            # One demo participant to the other: the same limits.
            one, two = list(PARTICIPANTS)
            expect(one, "adapter", f"adapter.{two}", 8000, True)
            expect(one, "adapter", f"connector.{two}", 8082, True)
            expect(one, "adapter", f"connector.{two}", 8081, False)
            expect(one, "adapter", f"postgres.{two}", 5432, False)
        finally:
            quoted = urllib.parse.quote(probe, safe=":")
            lc.http("DELETE", f"{management}/api/participants/{quoted}", None, headers)
    print(f"{failures} failed")
    return 1 if failures else 0


def main() -> int:
    actions = {"up": up, "down": down, "check": check}
    action = actions.get(sys.argv[1]) if len(sys.argv) == 2 else None
    if action is None:
        print(__doc__, file=sys.stderr)
        return 2
    return action()


if __name__ == "__main__":
    sys.exit(main())
