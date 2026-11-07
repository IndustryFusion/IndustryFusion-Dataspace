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
"""A mock agent for local testing: it polls through the gateway with normal authentication, and answers.

A `request` gets an `inform` in reply, and a `grant`, `deny` or `inform` is only acknowledged. So is a `close`. It takes
the credentials dataspace_client.py takes. --once stops after the messages waiting now, and otherwise it runs until
interrupted.
"""

import argparse
import json
import os
import sys
import time

from dataspace_client import ApiError, DataspaceClient

POLL_SECONDS = 2


def handle(client: DataspaceClient, message: dict, reply_payload: dict) -> str:
    """Acknowledge one message, and reply if it asks for that. Return what was done."""
    client.ack(message["message_id"])
    if message["performative"] != "request" or message["sender_participant"] == client.client_id:
        return f"{message['performative']}: acknowledged"
    reply = client.send(
        message["sender_participant"],
        performative="inform",
        conversation_id=message["conversation_id"],
        in_reply_to=message["message_id"],
        payload=reply_payload,
    )
    return f"request: acknowledged, replied with {reply['message_id']}"


def poll(client: DataspaceClient, reply_payload: dict) -> int:
    handled = 0
    for message in client.inbox("received"):
        try:
            print(f"{message['message_id']} {handle(client, message, reply_payload)}", flush=True)
        except ApiError as error:
            # A conversation can have closed meanwhile. An agent reads that and goes on.
            print(f"{message['message_id']} could not reply: {error}", file=sys.stderr, flush=True)
        handled += 1
    return handled


def main() -> int:
    top = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    environ = os.environ.get
    top.add_argument("--gateway", default=environ("DATASPACE_GATEWAY_URL"))
    top.add_argument("--keycloak", default=environ("DATASPACE_KEYCLOAK_URL"))
    top.add_argument("--realm", default=environ("DATASPACE_REALM", "dataspace"))
    top.add_argument("--client-id", default=environ("DATASPACE_CLIENT_ID"))
    top.add_argument("--client-secret", default=environ("DATASPACE_CLIENT_SECRET"))
    top.add_argument(
        "--reply", default='{"answer": "from the mock agent"}', type=json.loads, help="The reply's payload"
    )
    top.add_argument("--once", action="store_true")
    args = top.parse_args()
    if not all((args.gateway, args.keycloak, args.client_id, args.client_secret)):
        top.error("gateway, keycloak, client id and secret are all needed")
    client = DataspaceClient(args.gateway, args.keycloak, args.client_id, args.client_secret, args.realm)
    while True:
        handled = poll(client, args.reply)
        if args.once:
            print(f"Handled {handled}", flush=True)
            return 0
        time.sleep(POLL_SECONDS)


if __name__ == "__main__":
    try:
        sys.exit(main())
    except KeyboardInterrupt:
        sys.exit(0)
