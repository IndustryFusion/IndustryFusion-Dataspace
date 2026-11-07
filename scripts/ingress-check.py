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
"""Checks a Helm install from outside, through its Ingress: onboarding, messages and the body limits.

Needs an install from deploy/README.md on the local cluster, with -e local. The Ingress controller is reached
at --ingress, an address such as http://<node address>:<node port>, with each host sent as a header.

Without --ingress it forwards to the gateway and management Services, for an install with no Ingress controller.
That checks the same flows and limits as the services enforce them, and says nothing about the Ingress.
"""

import argparse
import hashlib
import json
import os
import subprocess
import sys
import tempfile
import uuid
import zipfile

import local_cluster as lc

OWNER, BUILDER = "urn:ingress-check:factory-owner", "urn:ingress-check:machine-builder"
ADMIN_CLIENT = "dataspace-admin-cli"


def curl(*args: str, stdin: str | None = None) -> tuple[int, str]:
    """Run curl and return the status, and what it wrote to its output."""
    answer = subprocess.run(
        ["curl", "-sS", "--max-time", "1800", "-w", "\n%{http_code}", *args],
        input=stdin,
        capture_output=True,
        text=True,
    )
    if answer.returncode:
        raise RuntimeError(f"curl failed: {answer.stderr}")
    body, _, status = answer.stdout.rpartition("\n")
    return int(status), body


class Through:
    """Calls one Ingress host."""

    def __init__(self, ingress: str, host: str, token: str | None = None) -> None:
        self.ingress, self.host, self.token = ingress, host, token

    def headers(self) -> list[str]:
        extra = ["-H", f"Host: {self.host}"]
        return [*extra, "-H", f"Authorization: Bearer {self.token}"] if self.token else extra

    def json(self, method: str, path: str, body: object = None) -> tuple[int, object]:
        args = ["-X", method, *self.headers()]
        content = None
        if body is not None:
            # On standard input, as a large body doesn't fit in an argument.
            args += ["-H", "Content-Type: application/json", "-H", "Expect:", "--data-binary", "@-"]
            content = json.dumps(body)
        status, text = curl(*args, f"{self.ingress}{path}", stdin=content)
        try:
            return status, json.loads(text) if text else None
        except ValueError:
            return status, text


def write_upload(path: str, receiver: str, total: int) -> str:
    """A multipart request of exactly `total` bytes, with random content. Return the content's hash."""
    boundary = uuid.uuid4().hex
    start = (
        f'--{boundary}\r\nContent-Disposition: form-data; name="receiver_participant"\r\n\r\n{receiver}\r\n'
        f'--{boundary}\r\nContent-Disposition: form-data; name="files"; filename="limit.bin"\r\n'
        "Content-Type: application/octet-stream\r\n\r\n"
    ).encode()
    end = f"\r\n--{boundary}--\r\n".encode()
    digest = hashlib.sha256()
    left = total - len(start) - len(end)
    with open(path, "wb") as target:
        target.write(start)
        while left:
            block = os.urandom(min(left, 1024**2))
            digest.update(block)
            target.write(block)
            left -= len(block)
        target.write(end)
    assert os.path.getsize(path) == total
    return boundary + " " + digest.hexdigest()


def upload(gateway: Through, path: str, boundary: str) -> tuple[int, str]:
    # -T streams the file, where --data-binary would read it into memory.
    return curl(
        "-X", "POST", *gateway.headers(), "-H", f"Content-Type: multipart/form-data; boundary={boundary}",
        "-H", "Expect:", "-T", path, f"{gateway.ingress}/outbox/files",
    )  # fmt: skip


def main() -> int:
    arguments = parse_arguments()
    if arguments.ingress:
        return run(arguments, arguments.ingress, arguments.ingress)
    print("NOTE no Ingress is involved in this run: it goes to the Services directly")
    with lc.port_forward("dataspace", "gateway", 8080) as gateway:
        with lc.port_forward("dataspace", "management", 3000) as management:
            return run(arguments, gateway, management)


def parse_arguments() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--ingress", help="Without this, go to the Services directly")
    parser.add_argument("--gateway-host", default="dataspace.localtest.me")
    parser.add_argument("--management-host", default="dataspace-management.localtest.me")
    parser.add_argument("--max-upload-bytes", type=int, default=1024**3)
    parser.add_argument("--max-json-bytes", type=int, default=4 * 1024**2)
    parser.add_argument("--keep", action="store_true", help="Leave the participants there")
    return parser.parse_args()


def run(args: argparse.Namespace, gateway_address: str, management_address: str) -> int:
    secret = (lc.LOCAL / "admin-client-secret").read_text().strip()
    management = Through(management_address, args.management_host)
    status, token = management.json("POST", "/api/admin/token", {"client_id": ADMIN_CLIENT, "client_secret": secret})
    assert status == 200, token
    management.token = token["access_token"]
    print("PASS an admin token through management")
    status, health = management.json("GET", "/api/health")
    assert status == 200 and health["status"] == "ok", health
    print("PASS health through management: every component ok")

    status, owner = management.json(
        "POST", "/api/participants", {"participant_id": OWNER, "participant_type": "factory_owner"}
    )
    assert status == 200, owner
    print("PASS register a factory owner through this route, waiting for its pods")
    status, builder = management.json(
        "POST", "/api/participants", {"participant_id": BUILDER, "participant_type": "machine_builder"}
    )
    assert status == 200, builder

    try:
        with lc.port_forward("iff", "keycloak-service", 8080) as keycloak:
            url = f"{keycloak}/auth/realms/dataspace/protocol/openid-connect/token"

            def agent(record: dict) -> Through:
                form = {
                    "grant_type": "client_credentials",
                    "client_id": record["client_id"],
                    "client_secret": record["client_secret"],
                }
                status, answer = lc.http_form(url, form)
                assert status == 200, answer
                return Through(gateway_address, args.gateway_host, answer["access_token"])

            sender, receiver = agent(owner), agent(builder)

        status, sent = sender.json(
            "POST",
            "/outbox/messages",
            {"receiver_participant": BUILDER, "performative": "request", "payload": {"a": 1}},
        )
        assert status == 202, sent

        def arrived(message_id: str, timeout: float = 120) -> dict:
            def check():
                _, inbox = receiver.json("GET", "/inbox/messages?status=received")
                return next((m for m in inbox if m["message_id"] == message_id), None)

            return lc.poll(check, timeout=timeout, what="the message")

        assert arrived(sent["message_id"])["payload"] == {"a": 1}
        print("PASS a message through the gateway, the adapters and the connectors")

        status, body = sender.json(
            "POST", "/outbox/messages", {"receiver_participant": BUILDER, "payload": {"x": "y" * args.max_json_bytes}}
        )
        assert status == 413 and set(body) == {"detail"}, (status, body)
        print("PASS a JSON body over its limit gets 413 with the contract's body")

        with tempfile.TemporaryDirectory(prefix="ingress-check-") as folder:
            path = os.path.join(folder, "at-limit.bin")
            boundary, digest = write_upload(path, BUILDER, args.max_upload_bytes).split()
            status, text = upload(sender, path, boundary)
            assert status == 202, (status, text[:300])
            message_id = json.loads(text)["message_id"]
            print(f"PASS an upload of exactly {args.max_upload_bytes} bytes through this route: 202")
            arrived(message_id, timeout=420)
            bundle = os.path.join(folder, "bundle.zip")
            status, text = curl(
                *receiver.headers(), "-o", bundle, f"{gateway_address}/inbox/messages/{message_id}/download"
            )
            assert status == 200, (status, text[:300])
            got = hashlib.sha256()
            with zipfile.ZipFile(bundle) as archive, archive.open("limit.bin") as source:
                while block := source.read(1024**2):
                    got.update(block)
            assert got.hexdigest() == digest, "The bytes differ"
            print(f"PASS downloaded through this route with the same bytes: sha256 {digest}")

            with open(path, "ab") as target:
                target.write(b"\n")
            status, text = upload(sender, path, boundary)
            assert status == 413, (status, text[:300])
            print("PASS one byte over the limit through this route: 413")
    finally:
        if not args.keep:
            for participant in (OWNER, BUILDER):
                status, answer = management.json("DELETE", f"/api/participants/{participant}")
                print(f"delete {participant}: {status} {answer or ''}")
    print("All Ingress checks passed")
    return 0


if __name__ == "__main__":
    sys.exit(main())
