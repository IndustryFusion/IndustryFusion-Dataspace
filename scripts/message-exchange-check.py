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
"""Shows two participants exchanging messages in both directions through their connectors.

Needs scripts/local-env.sh up and scripts/local-env.sh services. It creates two
participants, runs the exchange, and removes them again. Set --keep to leave them running.
"""

import argparse
import secrets
import sys
import uuid

import local_cluster as lc

FACTORY_OWNER = "urn:check:factory-owner"
MACHINE_BUILDER = "urn:check:machine-builder"
KEYCLOAK_NS, KEYCLOAK_SERVICE, KEYCLOAK_PORT = "iff", "keycloak-service", 8080
REGISTRY_NS, REGISTRY_SERVICE, REGISTRY_PORT = "dataspace", "registry", 19000


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

        def notified():
            _, state = lc.http("GET", f"{self.base}/outbox/messages/{message_id}/status", headers=self.headers())
            assert state["status"] not in {"error", "rejected"}, state
            return state["status"] == "notified"

        lc.poll(notified, what=f"{self.name}'s message to be notified")
        return message_id

    def receive(self, message_id: str) -> dict:
        def arrived():
            _, inbox = lc.http("GET", f"{self.base}/inbox/messages", headers=self.headers())
            for message in inbox:
                if message["message_id"] == message_id:
                    assert message["status"] != "error", message
                    return message if message["status"] == "received" else None
            return None

        message = lc.poll(arrived, what=f"{message_id} to arrive at {self.name}")
        status, _ = lc.http("POST", f"{self.base}/inbox/messages/{message_id}/ack", headers=self.headers())
        assert status == 204
        return message


def exchange(owner: Agent, builder: Agent) -> None:
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

    nobody = {"receiver_participant": "urn:check:nobody", "payload": {}}
    status, _ = lc.http("POST", f"{builder.base}/outbox/messages", nobody, builder.headers())
    assert status == 404, status
    print("Unregistered receiver: 404")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--keep", action="store_true", help="Leave the participants running afterwards")
    args = parser.parse_args()
    key = secrets.token_hex(16)

    with (
        lc.port_forward(KEYCLOAK_NS, KEYCLOAK_SERVICE, KEYCLOAK_PORT) as keycloak_root,
        lc.port_forward(REGISTRY_NS, REGISTRY_SERVICE, REGISTRY_PORT) as registry,
    ):
        keycloak = f"{keycloak_root}/auth"
        try:
            client_secrets = setup(keycloak, registry, key)
            with (
                lc.port_forward(lc.PARTICIPANTS, f"adapter-{lc.slug(FACTORY_OWNER)}", 8000) as owner_url,
                lc.port_forward(lc.PARTICIPANTS, f"adapter-{lc.slug(MACHINE_BUILDER)}", 8000) as builder_url,
            ):
                owner = Agent("factory owner", FACTORY_OWNER, client_secrets[FACTORY_OWNER], keycloak, owner_url)
                builder_secret = client_secrets[MACHINE_BUILDER]
                builder = Agent("machine builder", MACHINE_BUILDER, builder_secret, keycloak, builder_url)
                exchange(owner, builder)
            print("PASS")
            return 0
        finally:
            if not args.keep:
                teardown(keycloak, registry)


if __name__ == "__main__":
    sys.exit(main())
