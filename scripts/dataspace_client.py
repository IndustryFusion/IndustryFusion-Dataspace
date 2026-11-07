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
"""A client for the agent API in gateway-api.md: a class for use from Python, and a command line over it.

It uses only the gateway and Keycloak. Credentials come from the environment, or from the options:
DATASPACE_GATEWAY_URL, DATASPACE_KEYCLOAK_URL, DATASPACE_REALM, DATASPACE_CLIENT_ID, DATASPACE_CLIENT_SECRET.
"""

import argparse
import json
import mimetypes
import os
import pathlib
import shutil
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
import uuid
from dataclasses import dataclass

TOKEN_MARGIN_SECONDS = 20


@dataclass
class Answer:
    status: int
    body: object
    headers: dict[str, str]


class ApiError(Exception):
    def __init__(self, answer: Answer) -> None:
        super().__init__(f"{answer.status}: {answer.body}")
        self.answer = answer


def _call(request: urllib.request.Request, timeout: float) -> Answer:
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            status, content, headers = response.status, response.read(), dict(response.headers)
    except urllib.error.HTTPError as error:
        status, content, headers = error.code, error.read(), dict(error.headers)
    try:
        body = json.loads(content) if content else None
    except ValueError:
        body = content
    return Answer(status, body, headers)


class DataspaceClient:
    def __init__(
        self, gateway: str, keycloak: str, client_id: str, client_secret: str, realm: str = "dataspace"
    ) -> None:
        self.gateway = gateway.rstrip("/")
        self.token_url = f"{keycloak.rstrip('/')}/realms/{realm}/protocol/openid-connect/token"
        self.client_id, self.client_secret = client_id, client_secret
        self._token: str | None = None
        self._expires = 0.0

    def token(self) -> str:
        if self._token is None or time.monotonic() > self._expires:
            form = urllib.parse.urlencode(
                {"grant_type": "client_credentials", "client_id": self.client_id, "client_secret": self.client_secret}
            ).encode()
            answer = _call(urllib.request.Request(self.token_url, form), 30)
            if answer.status != 200:
                raise ApiError(answer)
            self._token = answer.body["access_token"]
            self._expires = time.monotonic() + answer.body.get("expires_in", 60) - TOKEN_MARGIN_SECONDS
        return self._token

    def request(
        self, method: str, path: str, body: object = None, authenticated: bool = True, timeout: float = 130
    ) -> Answer:
        """Make a call and return the answer, whatever its status."""
        data = None if body is None else json.dumps(body).encode()
        call = urllib.request.Request(f"{self.gateway}{path}", data, method=method)
        if data is not None:
            call.add_header("Content-Type", "application/json")
        if authenticated:
            call.add_header("Authorization", f"Bearer {self.token()}")
        return _call(call, timeout)

    def _ok(self, method: str, path: str, body: object = None) -> object:
        answer = self.request(method, path, body)
        if answer.status >= 300:
            raise ApiError(answer)
        return answer.body

    # Discovery
    def health(self) -> object:
        return self.request("GET", "/health", authenticated=False).body

    def compatible(self) -> object:
        return self._ok("GET", "/participants/compatible")

    # Sending
    def send(self, receiver: str, **fields) -> object:
        return self._ok("POST", "/outbox/messages", {"receiver_participant": receiver, **fields})

    def send_files_request(self, receiver: str, paths: list[str], **fields) -> Answer:
        """Stream the form from disk, so that a large file isn't held in memory."""
        boundary = uuid.uuid4().hex
        parts: list[bytes | pathlib.Path] = []
        for name, value in {"receiver_participant": receiver, **fields}.items():
            if value is not None:
                parts.append(
                    f'--{boundary}\r\nContent-Disposition: form-data; name="{name}"\r\n\r\n{value}\r\n'.encode()
                )
        for path in map(pathlib.Path, paths):
            kind = mimetypes.guess_type(path.name)[0] or "application/octet-stream"
            parts.append(
                f'--{boundary}\r\nContent-Disposition: form-data; name="files"; filename="{path.name}"\r\n'
                f"Content-Type: {kind}\r\n\r\n".encode()
            )
            parts.append(path)
            parts.append(b"\r\n")
        parts.append(f"--{boundary}--\r\n".encode())
        length = sum(part.stat().st_size if isinstance(part, pathlib.Path) else len(part) for part in parts)

        def stream():
            for part in parts:
                if isinstance(part, pathlib.Path):
                    with part.open("rb") as source:
                        while block := source.read(1024**2):
                            yield block
                else:
                    yield part

        call = urllib.request.Request(f"{self.gateway}/outbox/files", stream(), method="POST")
        call.add_header("Content-Type", f"multipart/form-data; boundary={boundary}")
        call.add_header("Content-Length", str(length))
        call.add_header("Authorization", f"Bearer {self.token()}")
        return _call(call, 3600)

    def send_files(self, receiver: str, paths: list[str], **fields) -> object:
        answer = self.send_files_request(receiver, paths, **fields)
        if answer.status >= 300:
            raise ApiError(answer)
        return answer.body

    def sent(self, message_id: str) -> object:
        return self._ok("GET", f"/outbox/messages/{_quoted(message_id)}")

    def status(self, message_id: str) -> object:
        return self._ok("GET", f"/outbox/messages/{_quoted(message_id)}/status")

    def wait_for_status(self, message_id: str, wanted: tuple[str, ...] = ("notified",), seconds: float = 120) -> dict:
        """Poll until the status is one of these, or a final one. Return it."""
        deadline = time.monotonic() + seconds
        while True:
            state = self.status(message_id)
            if state["status"] in wanted or state["status"] in ("error", "rejected"):
                return state
            if time.monotonic() > deadline:
                raise TimeoutError(f"Message {message_id} is still {state['status']}")
            time.sleep(0.5)

    # Receiving
    def inbox(self, status: str | None = None) -> object:
        return self._ok("GET", "/inbox/messages" + (f"?status={_quoted(status)}" if status else ""))

    def received(self, message_id: str) -> object:
        return self._ok("GET", f"/inbox/messages/{_quoted(message_id)}")

    def wait_for_message(self, message_id: str, seconds: float = 180) -> dict:
        """Poll until this message is ready to read. Return it."""
        deadline = time.monotonic() + seconds
        while True:
            answer = self.request("GET", f"/inbox/messages/{_quoted(message_id)}")
            if answer.status == 200 and answer.body["status"] in ("received", "acked", "error"):
                return answer.body
            if time.monotonic() > deadline:
                raise TimeoutError(f"Message {message_id} didn't arrive: {answer.status} {answer.body}")
            time.sleep(0.5)

    def ack(self, message_id: str) -> None:
        self._ok("POST", f"/inbox/messages/{_quoted(message_id)}/ack")

    def download(self, message_id: str, target: str) -> int:
        """Stream the message's ZIP to a file, and return its size."""
        call = urllib.request.Request(f"{self.gateway}/inbox/messages/{_quoted(message_id)}/download")
        call.add_header("Authorization", f"Bearer {self.token()}")
        try:
            with urllib.request.urlopen(call, timeout=3600) as response, open(target, "wb") as output:
                shutil.copyfileobj(response, output, 1024**2)
        except urllib.error.HTTPError as error:
            raise ApiError(Answer(error.code, _parsed(error.read()), dict(error.headers))) from error
        return os.path.getsize(target)

    # Conversations
    def conversations(self, state: str | None = None) -> object:
        return self._ok("GET", "/conversations" + (f"?state={_quoted(state)}" if state else ""))

    def conversation(self, conversation_id: str) -> object:
        return self._ok("GET", f"/conversations/{_quoted(conversation_id)}")

    # Capabilities
    def access(self, provider: str | None = None, consumer: str | None = None) -> object:
        query = urllib.parse.urlencode({k: v for k, v in (("provider", provider), ("consumer", consumer)) if v})
        return self._ok("GET", f"/capabilities/access?{query}")

    def request_access(self, provider: str, capability: str, **fields) -> object:
        body = {"provider_participant": provider, "capability": capability, **fields}
        return self._ok("POST", "/capabilities/requests", body)

    def access_requests(self, status: str | None = None) -> object:
        return self._ok("GET", "/capabilities/requests" + (f"?status={_quoted(status)}" if status else ""))

    def decide(self, request_id: str, action: str, note: str | None = None) -> object:
        body = {"action": action, **({"note": note} if note else {})}
        return self._ok("PATCH", f"/capabilities/requests/{_quoted(request_id)}", body)

    def policy(self, consumer: str, capability: str, action: str) -> object:
        body = {"consumer_id": consumer, "capability": capability, "action": action}
        return self._ok("POST", "/capabilities/policy", body)


def _quoted(value: str) -> str:
    return urllib.parse.quote(value, safe=":")


def _parsed(content: bytes) -> object:
    try:
        return json.loads(content)
    except ValueError:
        return content.decode(errors="replace")


def client_from_environment(args: argparse.Namespace) -> DataspaceClient:
    missing = [name for name in ("gateway", "keycloak", "client_id", "client_secret") if not getattr(args, name)]
    if missing:
        raise SystemExit(f"Missing: {', '.join(missing)}. See --help")
    return DataspaceClient(args.gateway, args.keycloak, args.client_id, args.client_secret, args.realm)


def json_object(text: str) -> dict:
    value = json.loads(text)
    if not isinstance(value, dict):
        raise argparse.ArgumentTypeError("It must be a JSON object")
    return value


def parser() -> argparse.ArgumentParser:
    top = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    environ = os.environ.get
    top.add_argument("--gateway", default=environ("DATASPACE_GATEWAY_URL"))
    top.add_argument("--keycloak", default=environ("DATASPACE_KEYCLOAK_URL"), help="Including any path such as /auth")
    top.add_argument("--realm", default=environ("DATASPACE_REALM", "dataspace"))
    top.add_argument("--client-id", default=environ("DATASPACE_CLIENT_ID"), help="The participant id")
    top.add_argument("--client-secret", default=environ("DATASPACE_CLIENT_SECRET"))
    commands = top.add_subparsers(dest="command", required=True)

    def command(name: str, *arguments: tuple, help_text: str) -> None:
        sub = commands.add_parser(name, help=help_text)
        for flags, options in arguments:
            sub.add_argument(*flags, **options)

    message_id = (("message_id",), {})
    command("token", help_text="Print a token")
    command("health", help_text="The gateway's health")
    command("compatible", help_text="The participants this one may communicate with")
    command(
        "send",
        (("receiver",), {}),
        (("--performative",), {}),
        (("--conversation-id",), {}),
        (("--in-reply-to",), {}),
        (("--capability",), {}),
        (("--outcome",), {}),
        (("--authorization",), {"type": json_object}),
        (("--payload",), {"type": json_object}),
        (("--reply-expected",), {"action": "store_true"}),
        help_text="Send a message",
    )
    command(
        "send-files",
        (("receiver",), {}),
        (("files",), {"nargs": "+"}),
        (("--performative",), {}),
        (("--conversation-id",), {}),
        (("--in-reply-to",), {}),
        (("--capability",), {}),
        help_text="Send files",
    )
    command("sent", message_id, help_text="A sent message")
    command("status", message_id, help_text="A sent message's status")
    command(
        "wait", message_id, (("--seconds",), {"type": float, "default": 120}), help_text="Wait until notified, or final"
    )
    command("inbox", (("--status",), {}), help_text="Received messages")
    command("read", message_id, help_text="A received message")
    command("ack", message_id, help_text="Acknowledge a received message")
    command("download", message_id, (("target",), {}), help_text="Download a received message's ZIP")
    command("conversations", (("--state",), {}), help_text="Conversations")
    command("conversation", (("conversation_id",), {}), help_text="One conversation")
    command("access", (("--provider",), {}), (("--consumer",), {}), help_text="Effective capability access")
    command(
        "request-access",
        (("provider",), {}),
        (("capability",), {}),
        (("--conversation-id",), {}),
        (("--purpose",), {}),
        (("--note",), {}),
        help_text="Ask a provider for access",
    )
    command("requests", (("--status",), {}), help_text="Access requests received")
    command(
        "decide", (("request_id",), {}), (("action",), {}), (("--note",), {}), help_text="Approve or deny a request"
    )
    command(
        "policy", (("consumer",), {}), (("capability",), {}), (("action",), {}), help_text="Set a consumer's access"
    )
    return top


def _given(args: argparse.Namespace, *names: str) -> dict:
    values = {name: getattr(args, name) for name in names}
    return {name: value for name, value in values.items() if value not in (None, False)}


def run(args: argparse.Namespace, client: DataspaceClient) -> object:
    match args.command:
        case "token":
            return client.token()
        case "health":
            return client.health()
        case "compatible":
            return client.compatible()
        case "send":
            names = (
                "performative", "conversation_id", "in_reply_to", "capability", "outcome", "authorization", "payload",
                "reply_expected",
            )  # fmt: skip
            return client.send(args.receiver, **_given(args, *names))
        case "send-files":
            fields = _given(args, "performative", "conversation_id", "in_reply_to", "capability")
            return client.send_files(args.receiver, args.files, **fields)
        case "sent":
            return client.sent(args.message_id)
        case "status":
            return client.status(args.message_id)
        case "wait":
            return client.wait_for_status(args.message_id, seconds=args.seconds)
        case "inbox":
            return client.inbox(args.status)
        case "read":
            return client.received(args.message_id)
        case "ack":
            client.ack(args.message_id)
            return {"message_id": args.message_id, "acknowledged": True}
        case "download":
            return {"path": args.target, "bytes": client.download(args.message_id, args.target)}
        case "conversations":
            return client.conversations(args.state)
        case "conversation":
            return client.conversation(args.conversation_id)
        case "access":
            return client.access(args.provider, args.consumer)
        case "request-access":
            fields = _given(args, "conversation_id", "purpose", "note")
            return client.request_access(args.provider, args.capability, **fields)
        case "requests":
            return client.access_requests(args.status)
        case "decide":
            return client.decide(args.request_id, args.action, args.note)
        case "policy":
            return client.policy(args.consumer, args.capability, args.action)
    raise AssertionError(args.command)


def main() -> int:
    args = parser().parse_args()
    try:
        answer = run(args, client_from_environment(args))
    except ApiError as error:
        print(json.dumps({"status": error.answer.status, "body": error.answer.body}), file=sys.stderr)
        return 1
    except (OSError, TimeoutError) as error:
        print(f"Could not complete it: {type(error).__name__}: {error}", file=sys.stderr)
        return 2
    print(answer if isinstance(answer, str) else json.dumps(answer, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
