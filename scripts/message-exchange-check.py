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
OTHER_OWNER = "urn:check:other-factory-owner"
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
        adapter = lc.deploy_adapter(participant, role, key, client_secrets[participant], internal_key=key)
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
    # Only registered, with the same role as the factory owner, so that it is an incompatible provider.
    status, answer = lc.http(
        "POST",
        f"{registry}/participants",
        {
            "participant_id": OTHER_OWNER,
            "participant_type": "factory_owner",
            "adapter_url": "http://nowhere.invalid:8000",
            "dsp_url": "http://nowhere.invalid:8082/api/v1/dsp",
        },
    )
    assert status == 200, answer
    return client_secrets


def teardown(keycloak: str, registry: str) -> None:
    admin = lc.KeycloakAdmin(keycloak)
    lc.http("DELETE", f"{registry}/participants/{OTHER_OWNER}")
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


AUTHORIZATION = {"scope": "conversation", "expires_at": "2026-12-01T10:00:00+00:00", "constraints": {}}


def post(agent: Agent, receiver: str, **fields) -> tuple[int, dict]:
    body = {"receiver_participant": receiver, **fields}
    return lc.http("POST", f"{agent.base}/outbox/messages", body, agent.headers())


def conversation_on(agent: Agent, conversation_id: str) -> dict:
    status, shown = lc.http("GET", f"{agent.base}/conversations/{conversation_id}", headers=agent.headers())
    assert status == 200, (status, shown)
    return shown


def expect_same(owner: Agent, builder: Agent, conversation_id: str, state: str, outcome: str | None = None) -> dict:
    """Both copies must reach this, without any further message."""

    def agreed():
        first, second = conversation_on(owner, conversation_id), conversation_on(builder, conversation_id)
        same = all(first[name] == second[name] for name in ("state", "outcome", "escalated_by"))
        return first if same and (first["state"], first["outcome"]) == (state, outcome) else None

    return lc.poll(agreed, timeout=60, what=f"both copies of {conversation_id} to be {state}")


def conversations(owner: Agent, builder: Agent) -> None:
    """Each flow in protocol.md, with both participants' state compared after each step."""
    chat = str(uuid.uuid4())
    request = owner.send(MACHINE_BUILDER, conversation_id=chat, performative="request", capability="twin:history")
    received = builder.receive(request)
    assert received["performative"] == "request" and received["capability"] == "twin:history", received
    grant = builder.send(
        FACTORY_OWNER,
        conversation_id=chat,
        performative="grant",
        capability="twin:history",
        in_reply_to=request,
        authorization=AUTHORIZATION,
    )
    received = owner.receive(grant)
    assert received["authorization"] == AUTHORIZATION, received
    shown = expect_same(owner, builder, chat, "OPEN")
    assert shown["outstanding_requests"] == [] and len(shown["messages"]) == 2, shown
    print("Request and grant: both OPEN, the receiver reads the authorization, nothing outstanding")

    second = owner.send(MACHINE_BUILDER, conversation_id=chat, performative="request")
    builder.receive(second)
    assert [item["message_id"] for item in conversation_on(builder, chat)["outstanding_requests"]] == [second]
    denied = builder.send(
        FACTORY_OWNER, conversation_id=chat, performative="deny", capability="twin:history", in_reply_to=second
    )
    owner.receive(denied)
    third = owner.send(MACHINE_BUILDER, conversation_id=chat, performative="request")
    builder.receive(third)
    cancelled = owner.send(MACHINE_BUILDER, conversation_id=chat, performative="cancel", in_reply_to=third)
    builder.receive(cancelled)
    expect_same(owner, builder, chat, "OPEN")
    print("Deny and cancel: both OPEN")

    builder.send(FACTORY_OWNER, conversation_id=chat, performative="escalate")
    shown = expect_same(owner, builder, chat, "ESCALATING")
    assert shown["escalated_by"] == MACHINE_BUILDER, shown
    status, answer = post(owner, MACHINE_BUILDER, conversation_id=chat, performative="deescalate", payload={})
    assert status == 409 and answer["reason"] == "not_escalator", (status, answer)
    builder.send(FACTORY_OWNER, conversation_id=chat, performative="deescalate")
    expect_same(owner, builder, chat, "OPEN")
    print("Escalate and deescalate: same state and escalator on both sides, and the other side gets 409")

    owner.send(MACHINE_BUILDER, conversation_id=chat, performative="close", outcome="resolved")
    expect_same(owner, builder, chat, "CLOSED_RESOLVED", "resolved")
    status, answer = post(builder, FACTORY_OWNER, conversation_id=chat, performative="inform", payload={})
    assert status == 409 and answer["error"] == "conversation_state_violation", (status, answer)
    assert answer["conversation_state"] == "CLOSED_RESOLVED" and answer["closed_at"], answer
    status, audit = lc.http(
        "GET", f"{builder.base}/outbox/messages/{answer['message_id']}", headers=builder.headers()
    )
    assert status == 200 and audit["status"] == "rejected" and audit["applied"] is False, audit
    fields = {"conversation_id": chat, "performative": "close", "outcome": "failed", "payload": {}}
    status, answer = post(builder, FACTORY_OWNER, **fields)
    assert status == 202 and answer["applied"] is False, (status, answer)
    print("Close: both closed, a later message gets 409 and is kept for audit, a repeat close is not applied")

    builder.send(FACTORY_OWNER, conversation_id=chat, performative="reopen")
    expect_same(owner, builder, chat, "OPEN")
    print("Reopen: both OPEN")

    status, answer = post(owner, MACHINE_BUILDER, performative="grant", payload={})
    assert status == 422 and answer["error"] == "invalid_message", (status, answer)
    print("A message that breaks a validity rule: 422")

    _, listed = lc.http("GET", f"{owner.base}/conversations?state=open", headers=owner.headers())
    assert chat in {item["conversation_id"] for item in listed}, listed


def simultaneous_close(owner: Agent, builder: Agent, rounds: int = 6) -> None:
    """Both sides close at once, each with its own outcome, through real notifications."""
    for _ in range(rounds):
        chat = str(uuid.uuid4())
        opening = owner.send(MACHINE_BUILDER, conversation_id=chat)
        builder.receive(opening)

        step = {"conversation_id": chat, "performative": "close", "payload": {}}
        with ThreadPoolExecutor(max_workers=2) as pool:
            from_owner = pool.submit(post, owner, MACHINE_BUILDER, **step, outcome="resolved")
            from_builder = pool.submit(post, builder, FACTORY_OWNER, **step, outcome="withdrawn")
        (status_one, one), (status_two, two) = from_owner.result(), from_builder.result()
        assert status_one == status_two == 202, (one, two)
        if one["applied"] and two["applied"]:
            outcome = "resolved" if one["message_id"] < two["message_id"] else "withdrawn"
            kind = "crossed"
        else:
            outcome = "resolved" if one["applied"] else "withdrawn"
            kind = "one saw the other first"
        expect_same(owner, builder, chat, f"CLOSED_{outcome.upper()}", outcome)
        print(f"Simultaneous close ({kind}): both CLOSED_{outcome.upper()}")


CLOSE = {"performative": "close", "payload": {}}


def crossing_steps(owner: Agent, builder: Agent, rounds: int = 4) -> None:
    """Steps that cross, through real notifications, end in the same state on both sides."""
    for _ in range(rounds):
        chat = str(uuid.uuid4())
        builder.receive(owner.send(MACHINE_BUILDER, conversation_id=chat))

        def close_and_reopen(chat: str = chat) -> None:
            post(owner, MACHINE_BUILDER, conversation_id=chat, **CLOSE, outcome="resolved")
            post(owner, MACHINE_BUILDER, conversation_id=chat, performative="reopen", payload={})

        with ThreadPoolExecutor(max_workers=2) as pool:
            pool.submit(close_and_reopen)
            pool.submit(post, builder, FACTORY_OWNER, conversation_id=chat, **CLOSE, outcome="withdrawn")

        def settled(chat: str = chat):
            first, second = conversation_on(owner, chat), conversation_on(builder, chat)
            in_progress = {"pending", "registered", "transferring", "negotiating", "negotiated"}
            messages = first["messages"] + second["messages"]
            if any(item["status"] in in_progress for item in messages):
                return None
            return first if (first["state"], first["outcome"]) == (second["state"], second["outcome"]) else None

        state = lc.poll(settled, timeout=90, what="both copies")["state"]
        print(f"close and reopen crossing a close: both {state}")

        chat = str(uuid.uuid4())
        builder.receive(owner.send(MACHINE_BUILDER, conversation_id=chat))
        with ThreadPoolExecutor(max_workers=2) as pool:
            pool.submit(post, owner, MACHINE_BUILDER, **CLOSE, conversation_id=chat, outcome="failed")
            pool.submit(post, builder, FACTORY_OWNER, conversation_id=chat, performative="escalate", payload={})
        state = lc.poll(lambda c=chat: settled(c), timeout=90, what="both copies")["state"]
        print(f"close crossing escalate: both {state}")


def failed_notification(owner: Agent, builder: Agent) -> None:
    """The receiver's adapter is down while a close is sent. A repeat afterwards settles the two copies."""
    chat = str(uuid.uuid4())
    builder.receive(owner.send(MACHINE_BUILDER, conversation_id=chat))
    adapter = f"adapter-{lc.slug(MACHINE_BUILDER)}"
    lc.kubectl("-n", lc.PARTICIPANTS, "scale", f"deploy/{adapter}", "--replicas=0")
    pods = ("-n", lc.PARTICIPANTS, "get", "pods", "-l", f"app={adapter}", "-o", "name")
    lc.poll(lambda: not lc.kubectl(*pods), what="the adapter to stop")
    closing = {"conversation_id": chat, "performative": "close", "outcome": "superseded", "payload": {}}
    try:
        status, first = post(owner, MACHINE_BUILDER, **closing)
        assert status == 202, first

        def failed():
            path = f"{owner.base}/outbox/messages/{first['message_id']}/status"
            state = lc.http("GET", path, headers=owner.headers())[1]
            return state if state["status"] == "error" else None

        lc.poll(failed, what="the notification to fail")
    finally:
        lc.kubectl("-n", lc.PARTICIPANTS, "scale", f"deploy/{adapter}", "--replicas=1")
        lc.wait_ready(lc.PARTICIPANTS, adapter)
    assert conversation_on(owner, chat)["state"] == "CLOSED_SUPERSEDED"
    assert conversation_on(builder, chat)["state"] == "OPEN"
    print("Failed notification: the sender is closed, the receiver is still OPEN, and the status is error")

    status, again = post(owner, MACHINE_BUILDER, **closing)
    assert status == 202 and again["applied"] is True, (status, again)
    owner.wait_notified(again["message_id"])
    expect_same(owner, builder, chat, "CLOSED_SUPERSEDED", "superseded")
    print("Failed notification: the repeat reads applied, reaches the receiver, and both are closed")


def role_rules_at_the_receiver(owner: Agent) -> None:
    notification = {
        "message_id": str(uuid.uuid4()),
        "conversation_id": str(uuid.uuid4()),
        "sender_participant": FACTORY_OWNER,
        "receiver_participant": FACTORY_OWNER,
        "asset_id": "none",
        "provider_dsp_url": "http://nowhere.invalid",
    }
    route = f"{owner.base}/peer/{FACTORY_OWNER}/internal/transfer-request"
    status, answer = lc.http("POST", route, notification, owner.headers())
    assert status == 403, (status, answer)
    print("A notification from a sender whose role isn't compatible: 403")


def conversation_burst(owner: Agent, builder: Agent, count: int = BURST) -> None:
    """Concurrent messages from both sides on one conversation, then racing with a close."""
    chat = str(uuid.uuid4())
    builder.receive(owner.send(MACHINE_BUILDER, conversation_id=chat))
    owner_headers, builder_headers = owner.headers(), builder.headers()

    def send(agent: Agent, headers: dict, receiver: str, fields: dict) -> tuple[int, dict]:
        body = {"receiver_participant": receiver, "conversation_id": chat, "payload": {}, **fields}
        return lc.http("POST", f"{agent.base}/outbox/messages", body, headers)

    with ThreadPoolExecutor(max_workers=count * 2) as pool:
        items = [{"payload": {"n": n}} for n in range(count)]
        calls = [pool.submit(send, owner, owner_headers, MACHINE_BUILDER, item) for item in items]
        calls += [pool.submit(send, builder, builder_headers, FACTORY_OWNER, item) for item in items]
    answers = [call.result() for call in calls]
    assert all(status == 202 for status, _ in answers), answers
    for status_answer, agent in zip(answers, [owner] * count + [builder] * count, strict=True):
        agent.wait_notified(status_answer[1]["message_id"])
    from_owner = {answer["message_id"] for _, answer in answers[:count]}
    from_builder = {answer["message_id"] for _, answer in answers[count:]}
    for message_id in from_owner:
        builder.receive(message_id)
    for message_id in from_builder:
        owner.receive(message_id)
    expect_same(owner, builder, chat, "OPEN")
    print(f"Burst on one conversation: {count} from each side at once, all delivered, both OPEN")

    fields = [{"payload": {"n": n}} for n in range(count)]
    fields.insert(count // 2, {"performative": "close", "outcome": "resolved"})
    with ThreadPoolExecutor(max_workers=len(fields)) as pool:
        calls = [pool.submit(send, owner, owner_headers, MACHINE_BUILDER, item) for item in fields]
    answers = [call.result() for call in calls]
    assert {status for status, _ in answers} <= {202, 409}, answers
    accepted = [answer["message_id"] for status, answer in answers if status == 202]
    for message_id in accepted:
        owner.wait_notified(message_id)
    for message_id in accepted:
        builder.receive(message_id)
    expect_same(owner, builder, chat, "CLOSED_RESOLVED", "resolved")
    refused = len(fields) - len(accepted)
    print(f"Burst racing a close: {len(accepted)} accepted and delivered, {refused} refused with 409, both closed")

    closes = str(uuid.uuid4())
    builder.receive(owner.send(MACHINE_BUILDER, conversation_id=closes))
    outcomes = ["resolved", "failed", "withdrawn", "rejected"] * 3

    def close_with(outcome: str) -> tuple[int, dict]:
        body = {
            "receiver_participant": MACHINE_BUILDER, "conversation_id": closes, "payload": {},
            "performative": "close", "outcome": outcome,
        }  # fmt: skip
        return lc.http("POST", f"{owner.base}/outbox/messages", body, owner_headers)

    with ThreadPoolExecutor(max_workers=len(outcomes)) as pool:
        answers = list(pool.map(close_with, outcomes))
    assert all(status == 202 for status, _ in answers), answers
    winners = [outcome for (_, answer), outcome in zip(answers, outcomes, strict=True) if answer["applied"]]
    assert len(winners) == 1, winners
    expect_same(owner, builder, closes, f"CLOSED_{winners[0].upper()}", winners[0])
    print(f"Closes racing on one side: {len(outcomes)} accepted, one applied, the same state on both sides")
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


def capabilities(owner: Agent, builder: Agent, key: str) -> None:
    """A request, decisions and access checks between two participants, with a provider that is the factory owner."""

    def access(agent: Agent, query: str) -> dict[str, dict]:
        status, items = lc.http("GET", f"{agent.base}/capabilities/access?{query}", headers=agent.headers())
        assert status == 200, (status, items)
        return {item["capability"]: item for item in items}

    def ask(agent: Agent, provider: str, capability: str, **fields) -> tuple[int, dict]:
        body = {"provider_participant": provider, "capability": capability, **fields}
        return lc.http("POST", f"{agent.base}/capabilities/requests", body, agent.headers())

    def decide(approval_id: str, **body) -> tuple[int, dict]:
        return lc.http("PATCH", f"{owner.base}/capabilities/requests/{approval_id}", body, owner.headers())

    def policy(capability: str, action: str) -> tuple[int, dict]:
        body = {"consumer_id": MACHINE_BUILDER, "capability": capability, "action": action}
        return lc.http("POST", f"{owner.base}/capabilities/policy", body, owner.headers())

    provider_query = f"provider={FACTORY_OWNER}"
    seen = access(builder, provider_query)
    assert seen["twin:history"]["status"] == "on-request" and seen["twin:direct"]["status"] == "auto", seen
    assert access(owner, f"provider={MACHINE_BUILDER}")["mb:confidential"]["status"] == "auto"
    print("Access check: defaults through the gateway, from each side")

    status, request = ask(builder, FACTORY_OWNER, "twin:history", purpose="Compare runs", note="Line 3")
    assert status == 202 and request["status"] == "pending", (status, request)
    assert access(builder, provider_query)["twin:history"]["status"] == "pending"
    status, listed = lc.http("GET", f"{owner.base}/capabilities/requests?status=pending", headers=owner.headers())
    assert status == 200 and [item["id"] for item in listed] == [request["id"]], listed
    status, decided = decide(request["id"], action="approve", note="For this quarter")
    assert status == 200 and decided["decision_note"] == "For this quarter" and decided["note"] == "Line 3", decided
    entry = access(builder, provider_query)["twin:history"]
    assert (entry["status"], entry["source"]) == ("approved", "explicit"), entry
    assert access(owner, f"consumer={MACHINE_BUILDER}")["twin:history"]["status"] == "approved"
    status, again = decide(request["id"], action="deny")
    assert status == 409, (status, again)
    print("Request, approval and access check: approved on both views, the note returned, a second decision 409")

    status, answer = ask(owner, OTHER_OWNER, "twin:history")
    assert status == 403, (status, answer)
    print("Request from an incompatible role: 403")

    status, answer = ask(builder, FACTORY_OWNER, "mb:confidential")
    assert status == 404, (status, answer)
    print("A capability the provider doesn't offer: 404")

    status, denied = ask(builder, FACTORY_OWNER, "twin:adjacents")
    assert status == 202, denied
    status, answer = decide(denied["id"], action="deny", note="Not this line")
    assert status == 200 and answer["status"] == "denied", answer
    entry = access(builder, provider_query)["twin:adjacents"]
    assert (entry["status"], entry["decision_note"]) == ("denied", "Not this line"), entry

    before = lc.http("GET", f"{owner.base}/capabilities/requests", headers=owner.headers())[1]
    asked = builder.send(FACTORY_OWNER, performative="request", capability="twin:adjacents", payload={"a": 1})
    arrived = owner.receive(asked)
    assert (arrived["capability"], arrived["payload"]) == ("twin:adjacents", {"a": 1}), arrived
    chat = arrived["conversation_id"]
    sent = owner.send(MACHINE_BUILDER, conversation_id=chat, capability="twin:adjacents", payload={"line": [1, 2]})
    arrived = builder.receive(sent)
    assert arrived["payload"] == {"line": [1, 2]}, arrived
    print("A message naming a denied capability: delivered in both directions")

    grant = owner.send(
        MACHINE_BUILDER,
        conversation_id=chat,
        performative="grant",
        capability="twin:adjacents",
        in_reply_to=asked,
        authorization=AUTHORIZATION,
    )
    builder.receive(grant)
    refusal = owner.send(
        MACHINE_BUILDER, conversation_id=chat, performative="deny", capability="twin:history", in_reply_to=asked
    )
    builder.receive(refusal)
    after = lc.http("GET", f"{owner.base}/capabilities/requests", headers=owner.headers())[1]
    assert after == before, (before, after)
    assert access(builder, provider_query)["twin:adjacents"]["status"] == "denied"
    assert access(builder, provider_query)["twin:history"]["status"] == "approved"
    print("grant and deny messages: approval records unchanged")

    status, answer = policy("twin:adjacents", "reset")
    assert status == 200 and (answer["status"], answer["source"]) == ("on-request", "default"), answer
    assert access(builder, provider_query)["twin:adjacents"]["status"] == "on-request"
    status, answer = ask(builder, FACTORY_OWNER, "twin:adjacents")
    assert status == 202 and answer["status"] == "pending", answer
    print("Reset through the agent route: back to the default, and the consumer can ask again")

    name = lc.slug(FACTORY_OWNER)
    with lc.port_forward(lc.PARTICIPANTS, f"adapter-{name}", 8000) as adapter:
        headers = {"X-Internal-Key": key}
        status, state = lc.http("GET", f"{adapter}/internal/capabilities", headers=headers)
        assert status == 200 and state["approvals"], (status, state)
        status, answer = lc.http(
            "PATCH", f"{adapter}/internal/capabilities/approvals/{request['id']}", {"action": "reset"}, headers
        )
        assert status == 200 and (answer["status"], answer["source"]) == ("on-request", "default"), answer
        assert access(builder, provider_query)["twin:history"]["status"] == "on-request"
        print("Reset through the internal route that the management API will use: back to the default")

        status, answer = lc.http(
            "PATCH", f"{adapter}/internal/capabilities/twin:adjacents", {"default_policy": "auto"}, headers
        )
        assert status == 200, answer
        status, answer = lc.http("GET", f"{adapter}/internal/capabilities")
        assert status == 401, (status, answer)
        print("Internal routes: the key can change a default, and no credential gets 401")
        lc.http("PATCH", f"{adapter}/internal/capabilities/twin:adjacents", {"default_policy": "on-request"}, headers)

    for path in ("/internal/capabilities", "/%69nternal/capabilities"):
        status, _ = lc.http("GET", f"{owner.base}{path}", headers={**owner.headers(), "X-Internal-Key": key})
        assert status == 404, (path, status)
    print("Internal capability routes through the gateway: 404")


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
                conversations(owner, builder)
                simultaneous_close(owner, builder)
                conversation_burst(owner, builder)
                crossing_steps(owner, builder)
                role_rules_at_the_receiver(owner)
                failed_notification(owner, builder)
                size_limits(owner)
                capabilities(owner, builder, key)
            print("PASS")
            return 0
        finally:
            if not args.keep:
                teardown(keycloak, registry)


if __name__ == "__main__":
    sys.exit(main())
