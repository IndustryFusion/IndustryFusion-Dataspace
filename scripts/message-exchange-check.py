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
"""Shows the definition of done in manifest.md: two agents exchanging messages in both directions.

The agents use only the gateway and Keycloak. Messages travel through the adapters and connectors.
Needs scripts/local-env.sh up and scripts/local-env.sh services. It creates two participants,
runs the exchange, and removes them again. Set --keep to leave them running.
"""

import argparse
import hashlib
import io
import json
import os
import secrets
import subprocess
import sys
import tempfile
import time
import uuid
import zipfile
from concurrent.futures import ThreadPoolExecutor

import local_cluster as lc

FACTORY_OWNER = "urn:check:factory-owner"
MACHINE_BUILDER = "urn:check:machine-builder"
KEYCLOAK_NS, KEYCLOAK_SERVICE, KEYCLOAK_PORT = "iff", "keycloak-service", 8080
REGISTRY_NS, REGISTRY_SERVICE, REGISTRY_PORT = "dataspace", "registry", 19000
GATEWAY_NS, GATEWAY_SERVICE, GATEWAY_PORT = "dataspace", "gateway", 8080
BURST = 12
LIMIT_BYTES = 1024**3


def setup(keycloak: str, registry: str, key: str) -> dict[str, str]:
    admin = lc.KeycloakAdmin(keycloak)
    client_secrets = {}
    for participant, role in ((FACTORY_OWNER, "factory_owner"), (MACHINE_BUILDER, "machine_builder")):
        client_secrets[participant] = admin.add_participant(participant)
        connector = lc.deploy_connector(participant, key)
        adapter = lc.deploy_adapter(participant, role, key, client_secrets[participant])
        name = lc.slug(participant)
        status, answer = lc.http(
            "POST",
            f"{registry}/participants",
            {
                "participant_id": participant,
                "participant_type": role,
                "adapter_url": f"http://adapter-{name}.{lc.PARTICIPANTS}:8000",
                "dsp_url": f"http://connector-{name}.{lc.PARTICIPANTS}:8082/api/v1/dsp",
            },
        )
        assert status == 200, answer
        lc.wait_ready(lc.PARTICIPANTS, connector)
        lc.wait_ready(lc.PARTICIPANTS, adapter)
    return client_secrets


def teardown(keycloak: str, registry: str) -> None:
    admin = lc.KeycloakAdmin(keycloak)
    for participant in (FACTORY_OWNER, MACHINE_BUILDER):
        lc.http("DELETE", f"{registry}/participants/{participant}")
        lc.remove_adapter(participant)
        lc.remove_connector(participant)
        admin.remove_participant(participant)


class Agent:
    """An agent using the routes in gateway-api.md."""

    def __init__(self, name: str, participant: str, secret: str, keycloak: str, base: str) -> None:
        self.name, self.participant, self.secret, self.keycloak, self.base = name, participant, secret, keycloak, base

    def headers(self) -> dict[str, str]:
        # A fresh token each time keeps this simple. Tokens must carry the configured issuer.
        status, answer = lc.http_form(
            f"{self.keycloak}/realms/dataspace/protocol/openid-connect/token",
            {"grant_type": "client_credentials", "client_id": self.participant, "client_secret": self.secret},
        )
        assert status == 200, answer
        return {"Authorization": f"Bearer {answer['access_token']}"}

    def send(self, receiver: str, **fields) -> str:
        body = {"receiver_participant": receiver, **fields}
        status, answer = lc.http("POST", f"{self.base}/outbox/messages", body, self.headers())
        assert status == 202, (status, answer)
        message_id = answer["message_id"]
        self.wait_notified(message_id)
        return message_id

    def wait_notified(self, message_id: str) -> None:
        def notified():
            _, state = lc.http("GET", f"{self.base}/outbox/messages/{message_id}/status", headers=self.headers())
            assert state["status"] not in {"error", "rejected"}, state
            return state["status"] == "notified"

        lc.poll(notified, what=f"{self.name}'s message to be notified")

    def receive(self, message_id: str, acknowledge: bool = True, timeout: float = 120) -> dict:
        def arrived():
            _, inbox = lc.http("GET", f"{self.base}/inbox/messages", headers=self.headers())
            for message in inbox:
                if message["message_id"] == message_id:
                    assert message["status"] != "error", message
                    return message if message["status"] == "received" else None
            return None

        message = lc.poll(arrived, timeout=timeout, what=f"{message_id} to arrive at {self.name}")
        if acknowledge:
            status, _ = lc.http("POST", f"{self.base}/inbox/messages/{message_id}/ack", headers=self.headers())
            assert status == 204
        return message


def exchange(owner: Agent, builder: Agent) -> str:
    question = {"summary": f"Spindle temperature alarm {uuid.uuid4().hex}"}
    sent = owner.send(MACHINE_BUILDER, performative="request", reply_expected=True, payload=question)
    received = builder.receive(sent)
    assert received["payload"] == question, received
    assert received["sender_participant"] == FACTORY_OWNER
    print(f"Factory owner -> machine builder: delivered, {received['performative']}")

    answer = {"recommendation": f"Replace the coolant filter {uuid.uuid4().hex}"}
    reply = builder.send(
        FACTORY_OWNER,
        performative="inform",
        in_reply_to=sent,
        conversation_id=received["conversation_id"],
        payload=answer,
    )
    received = owner.receive(reply)
    assert received["payload"] == answer, received
    assert received["in_reply_to"] == sent
    print("Machine builder -> factory owner: delivered, same conversation")

    empty = owner.send(MACHINE_BUILDER, conversation_id=received["conversation_id"], payload={})
    received = builder.receive(empty)
    assert received["payload"] == {}, received
    assert received["error_message"] is None
    print("Empty payload: delivered, not an error")

    status, _ = lc.http(
        "POST",
        f"{builder.base}/outbox/messages",
        {"receiver_participant": "urn:check:nobody", "payload": {}},
        builder.headers(),
    )
    assert status == 404, status
    print("Unregistered receiver: 404")

    return sent


def burst(owner: Agent, builder: Agent, count: int = BURST) -> None:
    """Many messages opening one new conversation at once must all arrive, with none taken for a duplicate."""
    conversation = str(uuid.uuid4())
    headers = owner.headers()
    bodies = [
        {"receiver_participant": MACHINE_BUILDER, "conversation_id": conversation, "payload": {"item": item}}
        for item in range(count)
    ]

    def post(body: dict) -> str:
        status, answer = lc.http("POST", f"{owner.base}/outbox/messages", body, headers)
        assert status == 202, (status, answer)
        return answer["message_id"]

    with ThreadPoolExecutor(max_workers=count) as pool:
        sent = list(pool.map(post, bodies))
    assert len(set(sent)) == count
    print(f"Burst: {count} concurrent sends accepted")

    for item, message_id in enumerate(sent):
        received = builder.receive(message_id)
        assert received["payload"] == {"item": item}, received
        assert received["conversation_id"] == conversation, received
    print(f"Burst: all {count} delivered to the receiver, in one conversation")

    def transfer_id(message_id: str) -> str | None:
        _, state = lc.http("GET", f"{owner.base}/outbox/messages/{message_id}/status", headers=owner.headers())
        assert state["status"] == "notified", state
        return state["edc_transfer_id"]

    for message_id in sent:
        lc.poll(lambda chosen=message_id: transfer_id(chosen), timeout=30, what=f"the transfer id of {message_id}")
    print("Burst: every sender status has a transfer id")


def file_transfer(owner: Agent, builder: Agent, original: str) -> None:
    files = {"machine.json": b'{"spindle": 71.5}', "trace.bin": os.urandom(2 * 1024 * 1024), "empty.txt": b""}
    _, first = lc.http("GET", f"{builder.base}/inbox/messages/{original}", headers=builder.headers())
    fields = {
        "receiver_participant": MACHINE_BUILDER,
        "conversation_id": first["conversation_id"],
        "in_reply_to": original,
        "capability": "twin:direct",
        "performative": "inform",
    }
    status, answer = lc.http_multipart(f"{owner.base}/outbox/files", fields, list(files.items()), owner.headers())
    assert status == 202, (status, answer)
    message_id = answer["message_id"]
    owner.wait_notified(message_id)
    received = builder.receive(message_id, acknowledge=False)
    assert received["has_files"] is True and received["payload"] == {"_bundle": True}, received
    assert received["in_reply_to"] == original and received["conversation_id"] == first["conversation_id"], received
    status, content = lc.http(
        "GET", f"{builder.base}/inbox/messages/{message_id}/download", headers=builder.headers(), raw=True
    )
    assert status == 200, status
    with zipfile.ZipFile(io.BytesIO(content)) as archive:
        assert {name: archive.read(name) for name in archive.namelist()} == files
    print(f"Files: {len(files)} transferred through the connectors, same bytes, linked to the original message")

    status, _ = lc.http("GET", f"{builder.base}/inbox/messages/{original}/download", headers=builder.headers())
    assert status == 400, status
    print("Download of a message with no files: 400")
    status, _ = lc.http("GET", f"{owner.base}/inbox/messages/{message_id}/download", headers=owner.headers())
    assert status == 404, status
    print("Download of the other participant's message: 404")
    status, _ = lc.http("POST", f"{builder.base}/inbox/messages/{message_id}/ack", headers=builder.headers())
    assert status == 204, status

    fields = {"receiver_participant": MACHINE_BUILDER}
    status, _ = lc.http_multipart(f"{owner.base}/outbox/files", fields, [], owner.headers())
    assert status == 422, status
    print("Upload with no files: 422")


def curl(*args: str) -> str:
    return subprocess.run(["curl", "-sS", *args], check=True, capture_output=True, text=True).stdout.strip()


def peak_memory(deployment: str, namespace: str) -> int:
    """A container's highest resident memory so far, in KiB."""
    status = lc.kubectl("-n", namespace, "exec", f"deploy/{deployment}", "--", "cat", "/proc/1/status")
    return next(int(line.split()[1]) for line in status.splitlines() if line.startswith("VmHWM"))


def large_file(owner: Agent, builder: Agent, size_mib: int) -> None:
    """A file near the limit, through the gateway and connectors, with the same bytes at the other end."""
    with tempfile.TemporaryDirectory(prefix="large-file-") as folder:
        path = os.path.join(folder, "large.bin")
        digest = hashlib.sha256()
        with open(path, "wb") as target:
            for _ in range(size_mib):
                block = os.urandom(1024**2)
                digest.update(block)
                target.write(block)

        def auth_header(agent: Agent) -> str:
            return f"Authorization: {agent.headers()['Authorization']}"

        before = peak_memory("gateway", "dataspace")
        start = time.monotonic()
        answer = curl(
            "-f", "-H", auth_header(owner), "-F", f"receiver_participant={MACHINE_BUILDER}",
            "-F", f"files=@{path};filename=large.bin", f"{owner.base}/outbox/files",
        )  # fmt: skip
        message_id = json.loads(answer)["message_id"]
        print(f"Large file: {size_mib} MiB uploaded through the gateway in {time.monotonic() - start:.0f} s")
        start = time.monotonic()
        owner.wait_notified(message_id)
        builder.receive(message_id, acknowledge=False, timeout=300)
        print(f"Large file: arrived through the connectors in {time.monotonic() - start:.0f} s")

        start = time.monotonic()
        bundle = os.path.join(folder, "bundle.zip")
        curl(
            "-f", "-H", auth_header(builder), "-o", bundle,
            f"{builder.base}/inbox/messages/{message_id}/download",
        )  # fmt: skip
        print(f"Large file: downloaded through the gateway in {time.monotonic() - start:.0f} s")
        arrived = hashlib.sha256()
        with zipfile.ZipFile(bundle) as archive, archive.open("large.bin") as source:
            while block := source.read(1024**2):
                arrived.update(block)
        assert arrived.hexdigest() == digest.hexdigest()
        print(f"Large file: same bytes, sha256 {digest.hexdigest()}")
        after = peak_memory("gateway", "dataspace")
        print(f"Large file: gateway peak memory {before // 1024} MiB before, {after // 1024} MiB after")
        assert after // 1024 < size_mib / 2 or size_mib < 512, "The gateway seems to hold bodies in memory"
        lc.http("POST", f"{builder.base}/inbox/messages/{message_id}/ack", headers=builder.headers())

        over = os.path.join(folder, "over.bin")
        with open(over, "wb") as target:
            target.truncate(LIMIT_BYTES + 1)
        code = curl(
            "-o", "/dev/null", "-w", "%{http_code}", "-H", auth_header(owner),
            "-F", f"receiver_participant={MACHINE_BUILDER}", "-F", f"files=@{over}", f"{owner.base}/outbox/files",
        )  # fmt: skip
        assert code == "413", code
        print("Over the limit of 1 GiB: 413")


def size_limits(owner: Agent) -> None:
    """Routes other than the file route refuse a large body, with or without a stated length."""
    large = {"receiver_participant": MACHINE_BUILDER, "payload": {"x": "a" * (5 * 1024**2)}}
    status, _ = lc.http("POST", f"{owner.base}/outbox/messages", large, owner.headers())
    assert status == 413, status
    route = f"{owner.base}/peer/{MACHINE_BUILDER}/internal/transfer-request"
    status, _ = lc.http("POST", route, large, owner.headers())
    assert status == 413, status
    print("JSON over 4 MiB: 413, on the agent route and the peer route")

    with tempfile.NamedTemporaryFile(suffix=".json") as body:
        body.write(json.dumps(large).encode())
        body.flush()
        code = curl(
            "-o", "/dev/null", "-w", "%{http_code}", "-H", f"Authorization: {owner.headers()['Authorization']}",
            "-H", "Content-Type: application/json", "-H", "Transfer-Encoding: chunked",
            "--data-binary", f"@{body.name}", f"{owner.base}/outbox/messages",
        )  # fmt: skip
    assert code == "413", code
    print("JSON over 4 MiB with no stated length: 413")


def isolation(owner: Agent, builder: Agent, delivered_to_builder: str) -> None:
    base = owner.base
    status, _ = lc.http("GET", f"{base}/inbox/messages")
    assert status == 401, status
    print("No token: 401")

    status, peers = lc.http("GET", f"{base}/participants/compatible", headers=owner.headers())
    assert status == 200 and [peer["participant_id"] for peer in peers] == [MACHINE_BUILDER], peers
    print("Compatible participants: the machine builder")

    status, _ = lc.http("GET", f"{builder.base}/inbox/messages/{delivered_to_builder}", headers=builder.headers())
    assert status == 200, status
    status, _ = lc.http("GET", f"{base}/inbox/messages/{delivered_to_builder}", headers=owner.headers())
    assert status == 404, status
    print("The other participant's message: 404 with this token, 200 with its own")

    for path in ("/internal/payload/x", "/INTERNAL/payload/x", "/%69nternal/payload/x", "/inbox/../internal/payload/x"):
        status, _ = lc.http("GET", f"{base}{path}", headers=owner.headers())
        assert status == 404, (path, status)
    print("internal paths through the gateway: 404")

    notification = {
        "message_id": "forged",
        "conversation_id": "forged",
        "sender_participant": MACHINE_BUILDER,
        "receiver_participant": MACHINE_BUILDER,
        "asset_id": "forged",
        "provider_dsp_url": "http://nowhere",
    }
    route = f"{base}/peer/{MACHINE_BUILDER}/internal/transfer-request"
    status, _ = lc.http("POST", route, notification, owner.headers())
    assert status == 403, status
    print("Peer route: reaches the receiver, which refuses a stated sender the token doesn't match")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--keep", action="store_true", help="Leave the participants running afterwards")
    parser.add_argument("--large-file-mib", type=int, default=64, help="Size of the large file to transfer")
    args = parser.parse_args()
    key = secrets.token_hex(16)

    with (
        lc.port_forward(KEYCLOAK_NS, KEYCLOAK_SERVICE, KEYCLOAK_PORT) as keycloak_root,
        lc.port_forward(REGISTRY_NS, REGISTRY_SERVICE, REGISTRY_PORT) as registry,
    ):
        keycloak = f"{keycloak_root}/auth"
        try:
            client_secrets = setup(keycloak, registry, key)
            with lc.port_forward(GATEWAY_NS, GATEWAY_SERVICE, GATEWAY_PORT) as gateway:
                owner = Agent("factory owner", FACTORY_OWNER, client_secrets[FACTORY_OWNER], keycloak, gateway)
                builder = Agent("machine builder", MACHINE_BUILDER, client_secrets[MACHINE_BUILDER], keycloak, gateway)
                delivered = exchange(owner, builder)
                isolation(owner, builder, delivered)
                burst(owner, builder)
                file_transfer(owner, builder, delivered)
                large_file(owner, builder, args.large_file_mib)
                size_limits(owner)
            print("PASS")
            return 0
        finally:
            if not args.keep:
                teardown(keycloak, registry)


if __name__ == "__main__":
    sys.exit(main())
