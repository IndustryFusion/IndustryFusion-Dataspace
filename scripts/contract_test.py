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
"""Checks a deployment against gateway-api.md and flow.md, through dataspace_client.py.

Every answer is compared with a shape written out below, by hand, from gateway-api.md: each field, its type and its
allowed values. A field the document doesn't name fails too.

    contract_test.py --self-test    Needs no deployment. Shows that each shape refuses a wrong answer
    contract_test.py --local        Against scripts/local-env.sh, whether deployed with services or by Helm
    contract_test.py --gateway-url U --keycloak-url U --management-url U --admin-secret S
    contract_test.py --gateway-url U --keycloak-url U --owner ID:SECRET --builder ID:SECRET

External participants' flows run if there are any: with --local, those from scripts/external-demo.py, and otherwise
those given with --external-owner and --external-builder, each as ADAPTER_URL,ID,SECRET. Their agents call their own
adapter, and the hosted participants have to be externally reachable, which the suite arranges where it created them.

--tamper 'GET /conversations/*:outcome' puts a proxy in front of the gateway that removes a field from one route's real
answers. That run must fail, naming the field. It exits with 0 only if everything that ran passed.
"""

import argparse
import contextlib
import hashlib
import http.client
import http.server
import json
import os
import re
import select
import sys
import tempfile
import threading
import time
import traceback
import urllib.error
import urllib.parse
import urllib.request
import uuid
import zipfile
from collections.abc import Callable, Iterator
from dataclasses import dataclass

from dataspace_client import Answer, ApiError, DataspaceClient


# --- Shapes -----------------------------------------------------------------------------------------------------------
class Shape:
    def problems(self, value: object, where: str) -> list[str]:
        raise NotImplementedError

    def sample(self) -> object:
        raise NotImplementedError

    def wrong(self) -> object:
        raise NotImplementedError


class Kind(Shape):
    def __init__(self, kind: type, sample: object, wrong: object) -> None:
        self.kind, self._sample, self._wrong = kind, sample, wrong

    def problems(self, value, where):
        # A boolean is an int to Python, but not to JSON.
        matches = isinstance(value, self.kind) and (self.kind is bool or not isinstance(value, bool))
        return [] if matches else [f"{where}: expected {self.kind.__name__}, got {value!r}"]

    def sample(self):
        return self._sample

    def wrong(self):
        return self._wrong


class Moment(Kind):
    def __init__(self) -> None:
        super().__init__(str, "2026-11-07T10:00:00+00:00", 5)

    def problems(self, value, where):
        found = super().problems(value, where)
        if found:
            return found
        try:
            time.strptime(value[:19], "%Y-%m-%dT%H:%M:%S")
        except ValueError:
            return [f"{where}: expected a date-time, got {value!r}"]
        return []


class OneOf(Shape):
    def __init__(self, *values: str) -> None:
        self.values = values

    def problems(self, value, where):
        return [] if value in self.values else [f"{where}: {value!r} is not one of {self.values}"]

    def sample(self):
        return self.values[0]

    def wrong(self):
        return "not-a-documented-value"


class Pattern(Kind):
    def __init__(self, pattern: str, sample: str) -> None:
        super().__init__(str, sample, 5)
        self.pattern = pattern

    def problems(self, value, where):
        found = super().problems(value, where)
        if not found and not re.fullmatch(self.pattern, value):
            return [f"{where}: {value!r} doesn't match {self.pattern}"]
        return found

    def wrong(self):
        return "not-the-right-form"


class Nullable(Shape):
    def __init__(self, inner: Shape) -> None:
        self.inner = inner

    def problems(self, value, where):
        return [] if value is None else self.inner.problems(value, where)

    def sample(self):
        return self.inner.sample()

    def wrong(self):
        return self.inner.wrong()


class Exactly(Shape):
    """An object with these fields and no others."""

    def __init__(self, **fields: Shape) -> None:
        self.fields = fields

    def problems(self, value, where):
        if not isinstance(value, dict):
            return [f"{where}: expected an object, got {value!r}"]
        found = [f"{where}.{name}: missing" for name in self.fields if name not in value]
        found += [f"{where}.{name}: the contract doesn't name it" for name in value if name not in self.fields]
        for name, shape in self.fields.items():
            if name in value:
                found += shape.problems(value[name], f"{where}.{name}")
        return found

    def sample(self):
        return {name: shape.sample() for name, shape in self.fields.items()}

    def wrong(self):
        return "not-an-object"


class Each(Shape):
    def __init__(self, inner: Shape) -> None:
        self.inner = inner

    def problems(self, value, where):
        if not isinstance(value, list):
            return [f"{where}: expected a list, got {value!r}"]
        found = []
        for position, item in enumerate(value):
            found += self.inner.problems(item, f"{where}[{position}]")
        return found

    def sample(self):
        return [self.inner.sample()]

    def wrong(self):
        return "not-a-list"


TEXT = Kind(str, "text", 5)
FLAG = Kind(bool, True, "yes")
OBJECT = Kind(dict, {}, "not-an-object")
WHEN = Moment()
ANY_NAME = Nullable(TEXT)
SENT_STATUS = OneOf("pending", "registered", "notified", "error", "rejected")
INBOX_STATUS = OneOf("transferring", "negotiating", "negotiated", "received", "acked", "error")
STATE = Pattern(r"OPEN|ESCALATING|CLOSED_[A-Z_]+", "OPEN")
PERFORMATIVE = OneOf("request", "inform", "grant", "deny", "cancel", "close", "reopen", "escalate", "deescalate")
ACCESS_STATUS = OneOf("auto", "on-request", "pending", "approved", "denied")
ONTOLOGY = "https://industryfusion.github.io/contexts/ontology/v0/dataspace#"

PARTICIPANT = Exactly(
    participant_id=TEXT,
    participant_type=Pattern(re.escape(ONTOLOGY) + "(factory_owner|machine_builder)", ONTOLOGY + "factory_owner"),
    adapter_url=ANY_NAME,
    dsp_url=ANY_NAME,
    hosted=FLAG,
    externally_reachable=FLAG,
    peer_notify_url=ANY_NAME,
)
ACCEPTED = Exactly(message_id=TEXT, status=OneOf("pending"), applied=FLAG, conversation_state=STATE)
SENT = Exactly(
    message_id=TEXT,
    conversation_id=TEXT,
    performative=PERFORMATIVE,
    capability=ANY_NAME,
    in_reply_to=ANY_NAME,
    outcome=ANY_NAME,
    sender_participant=TEXT,
    receiver_participant=TEXT,
    created_at=WHEN,
    payload_ref=ANY_NAME,
    content_ref=Nullable(OBJECT),
    reply_expected=FLAG,
    status=SENT_STATUS,
    applied=FLAG,
)
STATUS = Exactly(
    message_id=TEXT,
    status=SENT_STATUS,
    edc_transfer_id=ANY_NAME,
    error_message=ANY_NAME,
    updated_at=WHEN,
    applied=FLAG,
    conversation_state=Nullable(STATE),
)
RECEIVED = Exactly(
    message_id=TEXT,
    conversation_id=TEXT,
    performative=PERFORMATIVE,
    capability=ANY_NAME,
    in_reply_to=ANY_NAME,
    outcome=ANY_NAME,
    authorization=Nullable(OBJECT),
    expires_at=Nullable(WHEN),
    response_due_at=Nullable(WHEN),
    sender_participant=TEXT,
    receiver_participant=TEXT,
    created_at=WHEN,
    received_at=Nullable(WHEN),
    payload=Nullable(OBJECT),
    status=INBOX_STATUS,
    applied=FLAG,
    error_message=ANY_NAME,
    has_files=FLAG,
)
CONVERSATION_FIELDS = {
    "conversation_id": TEXT,
    "state": STATE,
    "outcome": ANY_NAME,
    "counterpart_participant": TEXT,
    "opened_at": WHEN,
    "closed_at": Nullable(WHEN),
    "last_message_at": WHEN,
    "escalated_by": ANY_NAME,
}
CONVERSATION = Exactly(**CONVERSATION_FIELDS)
CONVERSATION_MESSAGE = Exactly(
    message_id=TEXT,
    direction=OneOf("sent", "received"),
    performative=PERFORMATIVE,
    capability=ANY_NAME,
    in_reply_to=ANY_NAME,
    outcome=ANY_NAME,
    sender_participant=TEXT,
    receiver_participant=TEXT,
    created_at=WHEN,
    applied=FLAG,
    status=OneOf(*SENT_STATUS.values, *INBOX_STATUS.values),
    has_files=FLAG,
    replied_at=Nullable(WHEN),
    payload=Nullable(OBJECT),
)
CONVERSATION_DETAIL = Exactly(
    **CONVERSATION_FIELDS, messages=Each(CONVERSATION_MESSAGE), outstanding_requests=Each(CONVERSATION_MESSAGE)
)
ACCESS = Exactly(
    capability=TEXT,
    label=TEXT,
    description=TEXT,
    data_classification=TEXT,
    status=ACCESS_STATUS,
    source=OneOf("default", "explicit"),
    decision_note=ANY_NAME,
)
ACCESS_REQUEST = Exactly(
    id=ANY_NAME,
    consumer_id=TEXT,
    capability=TEXT,
    status=ACCESS_STATUS,
    conversation_id=ANY_NAME,
    purpose=ANY_NAME,
    note=ANY_NAME,
    decision_note=ANY_NAME,
    requested_at=Nullable(WHEN),
    resolved_at=Nullable(WHEN),
)
POLICY = Exactly(consumer_id=TEXT, capability=TEXT, status=ACCESS_STATUS, source=OneOf("default", "explicit"))
STANDARD = Exactly(detail=TEXT)
VALIDATION = Exactly(detail=Each(OBJECT))
VIOLATION = Exactly(
    error=OneOf("conversation_state_violation"),
    reason=TEXT,
    detail=TEXT,
    conversation_id=TEXT,
    conversation_state=Nullable(STATE),
    closed_at=Nullable(WHEN),
    message_id=TEXT,
)
INVALID = Exactly(error=OneOf("invalid_message"), reason=TEXT, detail=TEXT, performative=TEXT)

SHAPES = {name: shape for name, shape in globals().items() if isinstance(shape, Exactly) and name.isupper()}


def self_test() -> int:
    """Each shape takes a valid answer, and refuses each kind of wrong one."""
    checks = failures = 0

    def refuses(shape: Shape, value: object, what: str) -> None:
        nonlocal checks, failures
        checks += 1
        if not shape.problems(value, "answer"):
            failures += 1
            print(f"FAIL the shape accepted: {what}")

    for name, shape in SHAPES.items():
        checks += 1
        found = shape.problems(shape.sample(), "answer")
        if found:
            failures += 1
            print(f"FAIL {name}'s own sample was refused: {found}")
        for field, inner in shape.fields.items():
            without = {key: value for key, value in shape.sample().items() if key != field}
            refuses(shape, without, f"{name} without {field}")
            refuses(shape, {**shape.sample(), field: inner.wrong()}, f"{name} with a wrong {field}")
            if not isinstance(inner, Nullable):
                refuses(shape, {**shape.sample(), field: None}, f"{name} with a null {field}")
        refuses(shape, {**shape.sample(), "unnamed": 1}, f"{name} with a field the contract doesn't name")
        refuses(shape, shape.wrong(), f"{name} that isn't an object")
    refuses(CONVERSATION_DETAIL, {**CONVERSATION_DETAIL.sample(), "messages": [{}]}, "a list with an empty entry")
    print(f"Self-test: {checks} checks, {failures} failures")
    return 1 if failures else 0


# --- Reporting --------------------------------------------------------------------------------------------------------
class Report:
    def __init__(self) -> None:
        self.passed = 0
        self.failed: list[str] = []
        self.not_run: list[str] = []

    def shape(self, route: str, answer: Answer, status: int, shape: Shape) -> object:
        """The route gave this status and shape. Goes on after a failure, so that a report lists all of them."""
        problems = (
            [] if answer.status == status else [f"status {answer.status}, wanted {status}: {answer.body!r}"[:400]]
        )
        problems += shape.problems(answer.body, "answer") if answer.status == status else []
        self.note(route, problems)
        return answer.body

    def status(self, route: str, answer: Answer, status: int) -> None:
        wrong = answer.status != status
        self.note(route, [f"status {answer.status}, wanted {status}: {answer.body!r}"[:400]] if wrong else [])

    def that(self, what: str, condition: bool, detail: object = "") -> None:
        self.note(what, [] if condition else [f"not so: {detail!r}"[:400]])

    def note(self, what: str, problems: list[str]) -> None:
        if problems:
            self.failed.append(what)
            print(f"FAIL {what}")
            for problem in problems:
                print(f"     {problem}")
        else:
            self.passed += 1
            print(f"PASS {what}")

    def finish(self) -> int:
        print(f"\n{self.passed} passed, {len(self.failed)} failed, {len(self.not_run)} not run")
        for what in self.not_run:
            print(f"NOT RUN {what}")
        return 1 if self.failed else 0


@dataclass
class External:
    """The external participants, and what is needed for the hosted ones to be reached from outside."""

    owner: DataspaceClient
    builder: DataspaceClient
    gateway: str
    keycloak: str
    make_hosted_reachable: Callable[[], None]


class Run:
    def __init__(
        self,
        report: Report,
        owner: DataspaceClient,
        builder: DataspaceClient,
        other: str | None,
        external: External | None = None,
    ) -> None:
        self.report, self.owner, self.builder, self.other = report, owner, builder, other
        self.owner_id, self.builder_id = owner.client_id, builder.client_id
        self.external = external

    def post(self, sender: DataspaceClient, receiver: str, **fields) -> Answer:
        return sender.request("POST", "/outbox/messages", {"receiver_participant": receiver, **fields})

    def sent_and_arrived(self, sender: DataspaceClient, receiver: DataspaceClient, **fields) -> dict:
        """Send a message that has to be accepted, and wait for it at the receiver. Return what the receiver read."""
        answer = self.post(sender, receiver.client_id, **fields)
        if answer.status != 202:
            raise ApiError(answer)
        message_id = answer.body["message_id"]
        state = sender.wait_for_status(message_id)
        if state["status"] != "notified":
            raise AssertionError(f"Message {message_id} ended as {state['status']}: {state['error_message']}")
        return receiver.wait_for_message(message_id)


# --- The routes -------------------------------------------------------------------------------------------------------
def discovery(run: Run) -> None:
    report = run.report
    report.status("GET /health needs no token", run.owner.request("GET", "/health", authenticated=False), 200)
    compatible = run.owner.request("GET", "/participants/compatible")
    report.shape("GET /participants/compatible", compatible, 200, Each(PARTICIPANT))
    ids = [entry.get("participant_id") for entry in compatible.body if isinstance(entry, dict)]
    report.that("GET /participants/compatible names the other side", run.builder_id in ids, ids)
    report.that("GET /participants/compatible doesn't name this side", run.owner_id not in ids, ids)
    hosted = [entry for entry in compatible.body if isinstance(entry, dict) and entry.get("hosted")]
    report.that(
        "A hosted peer's addresses inside the hub are left out",
        all(entry["adapter_url"] is None and entry["dsp_url"] is None for entry in hosted),
        hosted,
    )
    answer = run.owner.request("GET", "/participants/compatible", authenticated=False)
    report.shape("No token: 401", answer, 401, STANDARD)
    call = urllib.request.Request(f"{run.owner.gateway}/participants/compatible")
    call.add_header("Authorization", "Bearer not-a-token")
    try:
        with urllib.request.urlopen(call, timeout=30) as response:
            status = response.status
    except urllib.error.HTTPError as error:
        status = error.code
    report.that("An invalid token: 401", status == 401, status)
    for path in ("/internal/payload/x", "/internal/capabilities", "/internal/transfer-request"):
        report.shape(f"GET {path}: 404 through the gateway", run.owner.request("GET", path), 404, STANDARD)


def sending(run: Run) -> None:
    report, owner = run.report, run.owner
    answer = run.post(owner, run.builder_id, performative="request", reply_expected=True, payload={"summary": "Alarm"})
    accepted = report.shape("POST /outbox/messages", answer, 202, ACCEPTED)
    message_id = accepted["message_id"]
    report.that(
        "A new conversation is OPEN and applied", accepted["conversation_state"] == "OPEN" and accepted["applied"]
    )

    sent = report.shape("GET /outbox/messages/{id}", owner.request("GET", f"/outbox/messages/{message_id}"), 200, SENT)
    chat = sent["conversation_id"]
    report.that(
        "A sent message names its sides",
        (sent["sender_participant"], sent["receiver_participant"]) == (run.owner_id, run.builder_id),
    )
    report.that("reply_expected is kept", sent["reply_expected"] is True)
    state = owner.wait_for_status(message_id)
    report.that("It reaches notified", state["status"] == "notified", state)
    report.shape(
        "GET /outbox/messages/{id}/status", owner.request("GET", f"/outbox/messages/{message_id}/status"), 200, STATUS
    )

    report.shape(
        "GET /outbox/messages/{id} of nothing: 404", owner.request("GET", "/outbox/messages/none"), 404, STANDARD
    )
    report.shape("Status of nothing: 404", owner.request("GET", "/outbox/messages/none/status"), 404, STANDARD)
    report.shape("An unregistered receiver: 404", run.post(owner, "urn:contract:nobody", payload={}), 404, STANDARD)
    if run.other:
        report.shape("An incompatible receiver: 403", run.post(owner, run.other, payload={}), 403, STANDARD)
    else:
        report.not_run.append("An incompatible receiver: this run has no third participant")
    report.shape(
        "A schema error: 422 with no values",
        owner.request("POST", "/outbox/messages", {"payload": {}}),
        422,
        VALIDATION,
    )
    both = {"payload": {}, "content_ref": {"asset_id": "a", "dsp_url": "http://d"}}
    report.shape("payload with content_ref: 422", run.post(owner, run.builder_id, **both), 422, INVALID)
    for what, fields in {
        "An unknown performative": {"performative": "shout"},
        "grant without its fields": {"performative": "grant"},
        "close without an outcome": {"performative": "close", "conversation_id": chat},
        "An unknown outcome": {"performative": "close", "conversation_id": chat, "outcome": "nope"},
        "inform with an outcome": {"outcome": "resolved"},
    }.items():
        report.shape(f"{what}: 422 invalid_message", run.post(owner, run.builder_id, **fields), 422, INVALID)

    report.shape("A body over MAX_JSON_BYTES: 413", oversized_post(owner, 4 * 1024**2 + 1), 413, STANDARD)


def oversized_post(client: DataspaceClient, size: int) -> Answer:
    headers = {"Authorization": f"Bearer {client.token()}", "Content-Type": "application/json"}
    status, content, answer_headers = watching_for_an_early_answer(
        client.gateway, "POST", "/outbox/messages", headers, b" " * size
    )
    return Answer(status, json.loads(content) if content else None, answer_headers)


def watching_for_an_early_answer(base: str, method: str, path: str, headers: dict, body: bytes | None) -> tuple:
    """Send the headers first: a service that refuses a body's stated length answers at once, and may close then."""
    parts = urllib.parse.urlsplit(base)
    connection = http.client.HTTPConnection(parts.hostname, parts.port, timeout=130)
    connection.putrequest(method, path, skip_accept_encoding=True)
    for name, value in headers.items():
        connection.putheader(name, value)
    if body:
        connection.putheader("Content-Length", str(len(body)))
    connection.endheaders()
    if body and not select.select([connection.sock], [], [], 3)[0]:
        connection.send(body)
    response = connection.getresponse()
    content = response.read()
    connection.close()
    return response.status, content, dict(response.headers)


def receiving(run: Run) -> None:
    report, owner, builder = run.report, run.owner, run.builder
    answer = run.post(owner, run.builder_id, performative="request", payload={"n": 1})
    message_id = answer.body["message_id"]
    message = builder.wait_for_message(message_id)
    report.that("A message arrives as received", message["status"] == "received", message)
    report.that("Its payload arrives", message["payload"] == {"n": 1}, message)
    report.that("A message with no files reads has_files false", message["has_files"] is False)
    read = builder.request("GET", f"/inbox/messages/{message_id}")
    report.shape("GET /inbox/messages/{id}", read, 200, RECEIVED)
    listed = builder.request("GET", "/inbox/messages?status=received")
    report.shape("GET /inbox/messages?status=received", listed, 200, Each(RECEIVED))
    report.that("The filter gives only that status", all(item["status"] == "received" for item in listed.body))
    report.that("The list holds it", message_id in [item["message_id"] for item in listed.body])
    report.shape("GET /inbox/messages", builder.request("GET", "/inbox/messages"), 200, Each(RECEIVED))

    report.status("POST /inbox/messages/{id}/ack", builder.request("POST", f"/inbox/messages/{message_id}/ack"), 204)
    report.status("Ack is safe to repeat", builder.request("POST", f"/inbox/messages/{message_id}/ack"), 204)
    after = builder.request("GET", f"/inbox/messages/{message_id}").body
    report.that("It then reads acked", after["status"] == "acked", after)
    report.shape("Ack of nothing: 404", builder.request("POST", "/inbox/messages/none/ack"), 404, STANDARD)
    report.shape("Read of nothing: 404", builder.request("GET", "/inbox/messages/none"), 404, STANDARD)
    report.shape(
        "Another participant's message: 404", owner.request("GET", f"/inbox/messages/{message_id}"), 404, STANDARD
    )
    report.shape(
        "Download with no files: 400", builder.request("GET", f"/inbox/messages/{message_id}/download"), 400, STANDARD
    )


def files(run: Run, folder: str) -> None:
    report, owner, builder = run.report, run.owner, run.builder
    paths = [os.path.join(folder, name) for name in ("first.bin", "machine.json")]
    digests = {}
    for path in paths:
        content = os.urandom(200_000)
        with open(path, "wb") as target:
            target.write(content)
        digests[os.path.basename(path)] = hashlib.sha256(content).hexdigest()
    answer = owner.send_files_request(run.builder_id, paths)
    accepted = report.shape("POST /outbox/files", answer, 202, ACCEPTED)
    message_id = accepted["message_id"]
    message = builder.wait_for_message(message_id)
    report.that("A file message reads has_files", message["has_files"] is True, message)
    report.that("Its payload reads _bundle", message["payload"] == {"_bundle": True}, message)
    target = os.path.join(folder, "bundle.zip")
    builder.download(message_id, target)
    with zipfile.ZipFile(target) as archive:
        report.that("The ZIP holds the files", sorted(archive.namelist()) == sorted(digests), archive.namelist())
        same = all(hashlib.sha256(archive.read(name)).hexdigest() == digest for name, digest in digests.items())
        stored = all(info.compress_type == zipfile.ZIP_STORED for info in archive.infolist())
    report.that("With the same bytes", same)
    report.that("Stored uncompressed", stored)
    report.shape(
        "Download by someone else: 404", owner.request("GET", f"/inbox/messages/{message_id}/download"), 404, STANDARD
    )
    report.shape("No files: 422", owner.send_files_request(run.builder_id, []), 422, STANDARD)


def rules(run: Run) -> None:
    report, owner, builder = run.report, run.owner, run.builder
    opening = run.sent_and_arrived(owner, builder, performative="request", payload={})
    chat = opening["conversation_id"]

    listed = owner.request("GET", "/conversations")
    report.shape("GET /conversations", listed, 200, Each(CONVERSATION))
    report.that("The list holds it", chat in [item["conversation_id"] for item in listed.body])
    lower = owner.request("GET", "/conversations?state=open")
    report.that("The state filter is case-insensitive", chat in [item["conversation_id"] for item in lower.body])
    detail = report.shape(
        "GET /conversations/{id}", owner.request("GET", f"/conversations/{chat}"), 200, CONVERSATION_DETAIL
    )
    report.that("The message reads sent", detail["messages"][0]["direction"] == "sent", detail["messages"])
    report.that("The counterpart is the other side", detail["counterpart_participant"] == run.builder_id)
    report.that("A request is outstanding", len(detail["outstanding_requests"]) == 1, detail["outstanding_requests"])
    report.shape("GET /conversations/{id} of nothing: 404", owner.request("GET", "/conversations/none"), 404, STANDARD)

    run.sent_and_arrived(builder, owner, conversation_id=chat, in_reply_to=opening["message_id"], payload={"a": 1})
    detail = owner.conversation(chat)
    report.that("A reply clears it", detail["outstanding_requests"] == [], detail["outstanding_requests"])
    replied = [item for item in detail["messages"] if item["message_id"] == opening["message_id"]][0]
    report.that("And sets replied_at", replied["replied_at"] is not None, replied)

    closed = run.post(owner, run.builder_id, conversation_id=chat, performative="close", outcome="resolved", payload={})
    body = report.shape("close", closed, 202, ACCEPTED)
    report.that("It reads CLOSED_RESOLVED", body["conversation_state"] == "CLOSED_RESOLVED", body)
    builder.wait_for_message(body["message_id"])
    report.that("Both sides are closed", builder.conversation(chat)["state"] == "CLOSED_RESOLVED")
    again = run.post(owner, run.builder_id, conversation_id=chat, performative="close", outcome="resolved", payload={})
    body = report.shape("A second close: 202", again, 202, ACCEPTED)
    report.that("It reads applied false", body["applied"] is False, body)
    refused = report.shape(
        "Any other message on a closed conversation: 409",
        run.post(owner, run.builder_id, conversation_id=chat, payload={}),
        409,
        VIOLATION,
    )
    report.that("Its reason is conversation_closed", refused["reason"] == "conversation_closed", refused)
    kept = owner.request("GET", f"/outbox/messages/{refused['message_id']}")
    report.that(
        "It is kept for audit, as rejected", kept.status == 200 and kept.body["status"] == "rejected", kept.body
    )

    unknown = run.post(owner, run.builder_id, conversation_id=f"none-{uuid.uuid4()}", performative="reopen", payload={})
    body = report.shape("reopen of nothing: 409", unknown, 409, VIOLATION)
    report.that(
        "Its state is null", body["conversation_state"] is None and body["reason"] == "conversation_not_found", body
    )


def capabilities(run: Run) -> None:
    report, owner, builder = run.report, run.owner, run.builder
    provider, consumer = run.owner_id, run.builder_id
    answer = builder.request("GET", f"/capabilities/access?provider={provider}")
    entries = report.shape("GET /capabilities/access?provider=", answer, 200, Each(ACCESS))
    by_name = {entry["capability"]: entry for entry in entries}
    report.that(
        "The factory owner's catalogue",
        set(by_name) == {"twin:direct", "twin:adjacents", "twin:history"},
        sorted(by_name),
    )
    answer = owner.request("GET", f"/capabilities/access?consumer={consumer}")
    report.shape("GET /capabilities/access?consumer=", answer, 200, Each(ACCESS))
    report.shape("Neither parameter: 422", owner.request("GET", "/capabilities/access"), 422, STANDARD)
    both = owner.request("GET", f"/capabilities/access?provider={provider}&consumer={consumer}")
    report.shape("Both parameters: 422", both, 422, STANDARD)
    unknown = builder.request("GET", "/capabilities/access?provider=urn:contract:nobody")
    report.shape("An unregistered provider: 404", unknown, 404, STANDARD)
    if run.other:
        wrong = owner.request("GET", f"/capabilities/access?provider={run.other}")
        report.shape("An incompatible provider: 403", wrong, 403, STANDARD)

    capability = "twin:history"
    report.that("twin:history starts on-request", by_name[capability]["status"] == "on-request", by_name[capability])
    body = {"provider_participant": provider, "capability": capability, "purpose": "Compare runs", "note": "Please"}
    made = report.shape(
        "POST /capabilities/requests", builder.request("POST", "/capabilities/requests", body), 202, ACCESS_REQUEST
    )
    report.that("It reads pending", made["status"] == "pending", made)
    repeated = builder.request("POST", "/capabilities/requests", body)
    report.that("Asking again returns the same one", repeated.body.get("id") == made["id"], repeated.body)
    auto = {"provider_participant": provider, "capability": "twin:direct"}
    automatic = builder.request("POST", "/capabilities/requests", auto).body
    report.that(
        "An automatic capability stores nothing", (automatic["status"], automatic["id"]) == ("auto", None), automatic
    )
    missing = {"provider_participant": provider, "capability": "no:such"}
    report.shape(
        "A capability not offered: 404", builder.request("POST", "/capabilities/requests", missing), 404, STANDARD
    )

    listed = owner.request("GET", "/capabilities/requests?status=pending")
    report.shape("GET /capabilities/requests?status=pending", listed, 200, Each(ACCESS_REQUEST))
    report.that("The provider sees it", made["id"] in [item["id"] for item in listed.body])
    report.that("The consumer doesn't", builder.request("GET", "/capabilities/requests").body == [])

    decided = owner.request(
        "PATCH", f"/capabilities/requests/{made['id']}", {"action": "approve", "note": "This quarter"}
    )
    decision = report.shape("PATCH /capabilities/requests/{id}", decided, 200, ACCESS_REQUEST)
    report.that("It stores the note", decision["decision_note"] == "This quarter", decision)
    seen = {entry["capability"]: entry for entry in builder.access(provider=provider)}[capability]
    report.that(
        "The consumer reads approved, with the note",
        (seen["status"], seen["decision_note"]) == ("approved", "This quarter"),
        seen,
    )
    resolved = owner.request("PATCH", f"/capabilities/requests/{made['id']}", {"action": "deny"})
    report.shape("Deciding a resolved request: 409", resolved, 409, STANDARD)
    report.shape(
        "Deciding nothing: 404",
        owner.request("PATCH", "/capabilities/requests/none", {"action": "deny"}),
        404,
        STANDARD,
    )

    for action, status, source in (
        ("deny", "denied", "explicit"),
        ("reset", "on-request", "default"),
        ("reset", "on-request", "default"),
    ):
        call = {"consumer_id": consumer, "capability": capability, "action": action}
        answer = owner.request("POST", "/capabilities/policy", call)
        got = report.shape(f"POST /capabilities/policy {action}", answer, 200, POLICY)
        report.that(f"It reads {status}", (got["status"], got["source"]) == (status, source), got)
    if run.other:
        call = {"consumer_id": run.other, "capability": capability, "action": "approve"}
        report.shape(
            "An incompatible consumer: 403", owner.request("POST", "/capabilities/policy", call), 403, STANDARD
        )
    call = {"consumer_id": "urn:contract:nobody", "capability": capability, "action": "approve"}
    report.shape("An unregistered consumer: 404", owner.request("POST", "/capabilities/policy", call), 404, STANDARD)


# --- The flows --------------------------------------------------------------------------------------------------------
def flow_worked_example(run: Run, folder: str) -> None:
    """flow.md, step by step."""
    report, owner, builder = run.report, run.owner, run.builder
    report.that("Flow 1: find the peer", run.builder_id in [peer["participant_id"] for peer in owner.compatible()])

    request = run.post(
        owner,
        run.builder_id,
        performative="request",
        reply_expected=True,
        payload={"summary": "Spindle temperature alarm"},
    )
    report.that(
        "Flow 2: a request starts a conversation",
        request.status == 202 and request.body["conversation_state"] == "OPEN",
        request.body,
    )
    request_id = request.body["message_id"]
    chat = owner.sent(request_id)["conversation_id"]
    report.that("Flow 2: it reaches notified", owner.wait_for_status(request_id)["status"] == "notified")

    message = builder.wait_for_message(request_id)
    report.that(
        "Flow 3: the machine builder reads it", message["payload"] == {"summary": "Spindle temperature alarm"}, message
    )
    builder.ack(request_id)

    path = os.path.join(folder, "flow-machine.json")
    content = json.dumps({"temperature": [71, 72, 90]}).encode()
    with open(path, "wb") as target:
        target.write(content)
    sent_file = owner.send_files(
        run.builder_id, [path], conversation_id=chat, in_reply_to=request_id, capability="twin:direct"
    )
    arrived = builder.wait_for_message(sent_file["message_id"])
    report.that(
        "Flow 4: the file arrives in the conversation",
        arrived["has_files"] and arrived["conversation_id"] == chat,
        arrived,
    )
    bundle = os.path.join(folder, "flow.zip")
    builder.download(sent_file["message_id"], bundle)
    with zipfile.ZipFile(bundle) as archive:
        report.that("Flow 4: with the same bytes", archive.read("flow-machine.json") == content)
    builder.ack(sent_file["message_id"])

    access = {entry["capability"]: entry for entry in builder.access(provider=run.owner_id)}
    report.that(
        "Flow 5: twin:history shows on-request",
        access["twin:history"]["status"] in ("on-request", "approved"),
        access["twin:history"],
    )
    owner.policy(run.builder_id, "twin:history", "reset")
    asked = builder.request_access(
        run.owner_id, "twin:history", conversation_id=chat, purpose="Compare with earlier runs"
    )
    pending = [item["id"] for item in owner.access_requests("pending")]
    report.that("Flow 5: the factory owner sees the request", asked["id"] in pending, pending)
    owner.decide(asked["id"], "approve")
    now = {entry["capability"]: entry for entry in builder.access(provider=run.owner_id)}["twin:history"]
    report.that("Flow 5: the next check shows approved", now["status"] == "approved", now)
    grant = run.sent_and_arrived(
        owner,
        builder,
        conversation_id=chat,
        performative="grant",
        capability="twin:history",
        in_reply_to=request_id,
        authorization={"scope": "conversation", "expires_at": "2026-12-01T10:00:00Z", "constraints": {}},
    )
    report.that("Flow 5: the grant carries its authorization", grant["authorization"]["scope"] == "conversation", grant)
    builder.ack(grant["message_id"])

    answer = run.sent_and_arrived(
        builder,
        owner,
        conversation_id=chat,
        performative="inform",
        in_reply_to=request_id,
        payload={"recommendation": "Replace the coolant filter"},
    )
    report.that(
        "Flow 6: the reply reads as sent", answer["payload"] == {"recommendation": "Replace the coolant filter"}, answer
    )
    owner.ack(answer["message_id"])

    closed = run.sent_and_arrived(
        owner, builder, conversation_id=chat, performative="close", outcome="resolved", payload={}
    )
    builder.ack(closed["message_id"])
    report.that(
        "Flow 7: both read CLOSED_RESOLVED",
        owner.conversation(chat)["state"] == builder.conversation(chat)["state"] == "CLOSED_RESOLVED",
    )
    repeat = run.post(owner, run.builder_id, conversation_id=chat, performative="close", outcome="resolved", payload={})
    report.that(
        "Flow 7: a second close reads applied false",
        (repeat.status, repeat.body.get("applied")) == (202, False),
        repeat.body,
    )
    other = run.post(builder, run.owner_id, conversation_id=chat, payload={})
    report.that("Flow 7: any other message gets 409", other.status == 409, other.body)
    owner.policy(run.builder_id, "twin:history", "reset")


def flow_escalation(run: Run) -> None:
    report, owner, builder = run.report, run.owner, run.builder
    chat = run.sent_and_arrived(owner, builder, performative="request", payload={})["conversation_id"]
    run.sent_and_arrived(owner, builder, conversation_id=chat, performative="escalate", payload={})
    one, two = owner.conversation(chat), builder.conversation(chat)
    report.that(
        "Escalation: both ESCALATING, by the same side",
        (one["state"], one["escalated_by"]) == (two["state"], two["escalated_by"]) == ("ESCALATING", run.owner_id),
        (one["state"], two["state"]),
    )
    other = run.post(builder, run.owner_id, conversation_id=chat, performative="deescalate", payload={})
    report.shape("Escalation: only the escalator can deescalate", other, 409, VIOLATION)
    run.sent_and_arrived(owner, builder, conversation_id=chat, performative="deescalate", payload={})
    report.that(
        "Escalation: deescalate takes both to OPEN",
        owner.conversation(chat)["state"] == builder.conversation(chat)["state"] == "OPEN",
    )
    run.sent_and_arrived(owner, builder, conversation_id=chat, performative="escalate", payload={})
    run.sent_and_arrived(owner, builder, conversation_id=chat, performative="close", outcome="escalated", payload={})
    report.that(
        "Escalation: close as escalated, on both sides",
        owner.conversation(chat)["state"] == builder.conversation(chat)["state"] == "CLOSED_ESCALATED",
    )
    refused = run.post(owner, run.builder_id, conversation_id=chat, performative="reopen", payload={})
    report.shape("Reopening: refused if closed as escalated", refused, 409, VIOLATION)


def flow_reopening(run: Run) -> None:
    report, owner, builder = run.report, run.owner, run.builder
    chat = run.sent_and_arrived(owner, builder, performative="request", payload={})["conversation_id"]
    run.sent_and_arrived(builder, owner, conversation_id=chat, performative="close", outcome="withdrawn", payload={})
    run.sent_and_arrived(owner, builder, conversation_id=chat, performative="reopen", payload={})
    one, two = owner.conversation(chat), builder.conversation(chat)
    report.that(
        "Reopening: both OPEN, with no outcome",
        (one["state"], one["outcome"]) == (two["state"], two["outcome"]) == ("OPEN", None),
        (one["state"], two["state"]),
    )


def worked_scenario(run: Run, folder: str) -> None:
    """A factory owner opens a request with a data file, the machine builder asks for more, and it closes."""
    report, owner, builder = run.report, run.owner, run.builder
    path = os.path.join(folder, "alarm-data.csv")
    content = b"time,temperature\n1,71\n2,90\n"
    with open(path, "wb") as target:
        target.write(content)
    opened = owner.send_files(run.builder_id, [path], performative="request")
    report.that("Scenario: a request with a data file is accepted", opened["applied"] is True, opened)
    chat = owner.sent(opened["message_id"])["conversation_id"]
    message = builder.wait_for_message(opened["message_id"])
    report.that(
        "Scenario: it arrives as a request with files",
        (message["performative"], message["has_files"]) == ("request", True),
        message,
    )
    bundle = os.path.join(folder, "alarm.zip")
    builder.download(opened["message_id"], bundle)
    with zipfile.ZipFile(bundle) as archive:
        report.that("Scenario: the data file has the same bytes", archive.read("alarm-data.csv") == content)
    builder.ack(opened["message_id"])

    owner.policy(run.builder_id, "twin:history", "reset")
    ask = run.sent_and_arrived(
        builder,
        owner,
        conversation_id=chat,
        performative="request",
        capability="twin:history",
        in_reply_to=opened["message_id"],
        payload={"need": "Earlier runs"},
    )
    owner.ack(ask["message_id"])
    asked = builder.request_access(run.owner_id, "twin:history", conversation_id=chat, purpose="Earlier runs")
    report.that("Scenario: the machine builder's request is pending", asked["status"] == "pending", asked)
    owner.decide(asked["id"], "approve", "For this case")
    grant = run.sent_and_arrived(
        owner, builder,
        conversation_id=chat, performative="grant", capability="twin:history", in_reply_to=ask["message_id"],
        authorization={"scope": "conversation", "expires_at": None, "constraints": {"machines": ["m1"]}},
    )  # fmt: skip
    report.that(
        "Scenario: the grant carries its authorization",
        grant["authorization"]["constraints"] == {"machines": ["m1"]},
        grant,
    )
    builder.ack(grant["message_id"])
    seen = {entry["capability"]: entry for entry in builder.access(provider=run.owner_id)}["twin:history"]
    report.that(
        "Scenario: access shows approved, with the note",
        (seen["status"], seen["decision_note"]) == ("approved", "For this case"),
        seen,
    )
    closed = run.sent_and_arrived(
        owner, builder, conversation_id=chat, performative="close", outcome="resolved", payload={}
    )
    builder.ack(closed["message_id"])
    one, two = owner.conversation(chat), builder.conversation(chat)
    report.that(
        "Scenario: both read the same closed state",
        (one["state"], one["outcome"]) == (two["state"], two["outcome"]) == ("CLOSED_RESOLVED", "resolved"),
        (one["state"], two["state"]),
    )
    report.that(
        "Scenario: both read the same messages",
        sorted(m["message_id"] for m in one["messages"]) == sorted(m["message_id"] for m in two["messages"]),
    )
    report.that(
        "Scenario: nothing outstanding on the first request",
        opened["message_id"] not in [m["message_id"] for m in one["outstanding_requests"]],
    )
    owner.policy(run.builder_id, "twin:history", "reset")


# --- External participants --------------------------------------------------------------------------------------------
def write_files(folder: str, name: str) -> tuple[str, str]:
    path = os.path.join(folder, name)
    content = os.urandom(300_000)
    with open(path, "wb") as target:
        target.write(content)
    return path, hashlib.sha256(content).hexdigest()


def file_crosses(run: Run, what: str, sender: DataspaceClient, receiver: DataspaceClient, folder: str) -> None:
    report = run.report
    path, digest = write_files(folder, f"{uuid.uuid4().hex}.bin")
    answer = sender.send_files_request(receiver.client_id, [path])
    accepted = report.shape(f"{what}: POST /outbox/files", answer, 202, ACCEPTED)
    state = sender.wait_for_status(accepted["message_id"])
    report.that(f"{what}: it reaches notified", state["status"] == "notified", state)
    message = receiver.wait_for_message(accepted["message_id"])
    report.shape(
        f"{what}: GET /inbox/messages/{{id}}",
        receiver.request("GET", f"/inbox/messages/{accepted['message_id']}"),
        200,
        RECEIVED,
    )
    report.that(f"{what}: the message reads has_files", message["has_files"] is True, message)
    if message["status"] != "received":
        raise AssertionError(f"{what}: it ended as {message['status']}: {message['error_message']}")
    target = os.path.join(folder, f"{uuid.uuid4().hex}.zip")
    receiver.download(accepted["message_id"], target)
    with zipfile.ZipFile(target) as archive:
        names = archive.namelist()
        same = names == [os.path.basename(path)] and hashlib.sha256(archive.read(names[0])).hexdigest() == digest
    report.that(f"{what}: the same bytes arrive", same, names)
    receiver.ack(accepted["message_id"])


def message_crosses(run: Run, what: str, sender: DataspaceClient, receiver: DataspaceClient, **fields) -> dict:
    report = run.report
    message = run.sent_and_arrived(sender, receiver, **fields)
    report.shape(
        f"{what}: GET /inbox/messages/{{id}}",
        receiver.request("GET", f"/inbox/messages/{message['message_id']}"),
        200,
        RECEIVED,
    )
    report.that(f"{what}: the content arrives", message["payload"] == fields.get("payload"), message)
    report.that(f"{what}: the token decided the sender", message["sender_participant"] == sender.client_id, message)
    receiver.ack(message["message_id"])
    return message


def capability_requested(
    run: Run, what: str, consumer: DataspaceClient, provider: DataspaceClient, capability: str
) -> None:
    report = run.report
    route = f"/capabilities/access?provider={urllib.parse.quote(provider.client_id, safe=':')}"
    entries = report.shape(f"{what}: GET /capabilities/access", consumer.request("GET", route), 200, Each(ACCESS))
    status_of = {entry["capability"]: entry["status"] for entry in entries}
    report.that(f"{what}: on request at first", status_of.get(capability) == "on-request", status_of)

    body = {"provider_participant": provider.client_id, "capability": capability, "purpose": "Contract test"}
    answer = consumer.request("POST", "/capabilities/requests", body)
    asked = report.shape(f"{what}: POST /capabilities/requests", answer, 202, ACCESS_REQUEST)
    report.that(f"{what}: the request is pending", asked["status"] == "pending", asked)

    held = provider.request("GET", "/capabilities/requests?status=pending")
    pending = report.shape(f"{what}: the provider holds it", held, 200, Each(ACCESS_REQUEST))
    report.that(f"{what}: it names the consumer", asked["id"] in [entry["id"] for entry in pending], pending)
    decided = provider.request("PATCH", f"/capabilities/requests/{asked['id']}", {"action": "approve", "note": "Yes"})
    report.shape(f"{what}: PATCH /capabilities/requests/{{id}}", decided, 200, ACCESS_REQUEST)

    entries = report.shape(f"{what}: access again", consumer.request("GET", route), 200, Each(ACCESS))
    entry = next(entry for entry in entries if entry["capability"] == capability)
    report.that(f"{what}: now approved", (entry["status"], entry["decision_note"]) == ("approved", "Yes"), entry)
    reset = {"consumer_id": consumer.client_id, "capability": capability, "action": "reset"}
    report.shape(f"{what}: reset", provider.request("POST", "/capabilities/policy", reset), 200, POLICY)


def closes_cross(run: Run, what: str, one: DataspaceClient, two: DataspaceClient) -> None:
    """Both sides close at once, so each side's rules, sender_applied and kept_step decide. The copies must agree."""
    report = run.report
    opened = run.sent_and_arrived(one, two, performative="request", payload={"summary": what})
    chat = opened["conversation_id"]
    answers: dict[str, Answer] = {}

    def close_to(client: DataspaceClient, peer: str, outcome: str) -> None:
        answers[client.client_id] = run.post(
            client, peer, conversation_id=chat, performative="close", outcome=outcome, payload={}
        )

    # Tokens first, so that the two calls start together.
    one.token(), two.token()
    threads = [
        threading.Thread(target=close_to, args=(one, two.client_id, "resolved")),
        threading.Thread(target=close_to, args=(two, one.client_id, "withdrawn")),
    ]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()
    ids = {}
    for client, peer in ((one, two), (two, one)):
        answer = answers[client.client_id]
        accepted = report.shape(f"{what}: each close is accepted", answer, 202, ACCEPTED)
        ids[client.client_id] = accepted["message_id"]
        state = client.wait_for_status(accepted["message_id"])
        report.that(f"{what}: each close is notified", state["status"] == "notified", state)
        peer.wait_for_message(accepted["message_id"])
    first, second = one.conversation(chat), two.conversation(chat)
    report.that(
        f"{what}: both sides read the same state",
        (first["state"], first["outcome"]) == (second["state"], second["outcome"]),
        (first["state"], second["state"]),
    )
    report.that(f"{what}: closed", first["state"] in {"CLOSED_RESOLVED", "CLOSED_WITHDRAWN"}, first["state"])
    own = {m["message_id"]: m for m in first["messages"]}
    applied = [own[ids[one.client_id]]["applied"], own[ids[two.client_id]]["applied"]]
    report.that(f"{what}: one close moved it, and the other didn't", sorted(applied) == [False, True], applied)


def peer_route_keeps_its_limits(run: Run) -> None:
    """Called as an external adapter calls the public gateway."""
    report, external = run.report, run.external
    builder = external.builder
    caller = DataspaceClient(external.gateway, external.keycloak, builder.client_id, builder.client_secret)
    owner = urllib.parse.quote(run.owner_id, safe=":")
    route = f"/peer/{owner}/internal/capabilities"
    state = caller.request("GET", route)
    report.that("A peer reads the provider through the gateway", state.status == 200, state.status)
    consumers = {entry["consumer_id"] for entry in state.body.get("approvals", [])}
    report.that("It reads only its own approvals", consumers <= {caller.client_id}, consumers)
    other = {"consumer_id": run.builder_id, "capability": "twin:history", "action": "request"}
    answer = caller.request("POST", f"{route}/approvals", other)
    report.shape("A peer can't ask for another participant: 403", answer, 403, STANDARD)
    decide = {"consumer_id": caller.client_id, "capability": "twin:history", "action": "approve"}
    answer = caller.request("POST", f"{route}/approvals", decide)
    report.shape("A peer can't approve itself: 403", answer, 403, STANDARD)
    answer = caller.request("GET", route, authenticated=False)
    report.shape("No token on the peer route: 401", answer, 401, STANDARD)
    answer = caller.request("POST", f"/peer/{owner}/internal/inbox-receive/x", {}, authenticated=False)
    report.shape("Content with no transfer token: 401", answer, 401, STANDARD)
    call = urllib.request.Request(f"{external.gateway}/peer/{owner}/internal/inbox-receive/x", b"{}", method="POST")
    call.add_header("X-Transfer-Token", "a guess")
    status = _status_of(call)
    report.that("Content with a wrong transfer token: 401", status == 401, status)
    call = urllib.request.Request(f"{external.gateway}{route}")
    call.add_header("Authorization", f"Bearer {caller.token()}")
    call.add_header("X-Internal-Key", "a guess")
    status = _status_of(call)
    report.that("A wrong internal key isn't seen by the adapter: it answers as for a peer", status == 200, status)


def _status_of(call: urllib.request.Request) -> int:
    try:
        with urllib.request.urlopen(call, timeout=30) as response:
            return response.status
    except urllib.error.HTTPError as error:
        return error.code


def burst_crosses(run: Run, what: str, sender: DataspaceClient, receiver: DataspaceClient, count: int = 8) -> None:
    """Sent at once, so that a loss under load shows. Each has to arrive exactly once, with its own content."""
    report = run.report
    answers: dict[int, Answer] = {}

    def send(index: int) -> None:
        answers[index] = run.post(sender, receiver.client_id, performative="inform", payload={"index": index})

    sender.token()
    threads = [threading.Thread(target=send, args=(index,)) for index in range(count)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()
    accepted = {index: answer.body["message_id"] for index, answer in answers.items() if answer.status == 202}
    report.that(f"{what}: each is accepted", len(accepted) == count, {i: a.status for i, a in answers.items()})
    arrived = {index: receiver.wait_for_message(message_id)["payload"] for index, message_id in accepted.items()}
    report.that(f"{what}: each arrives with its content", all(arrived[i] == {"index": i} for i in arrived), arrived)
    ids = [entry["message_id"] for entry in receiver.inbox("received") if entry["message_id"] in accepted.values()]
    report.that(f"{what}: exactly once", sorted(ids) == sorted(accepted.values()), len(ids))
    for message_id in accepted.values():
        receiver.ack(message_id)


def unreachable_peer(run: Run) -> None:
    """A failure has to be reported, with nothing left in progress."""
    report, sender = run.report, run.external.builder
    accepted = report.shape(
        "A peer that can't be reached: POST /outbox/messages",
        run.post(sender, run.other, performative="inform", payload={}),
        202,
        ACCEPTED,
    )
    state = sender.wait_for_status(accepted["message_id"], wanted=("error", "rejected", "notified"))
    report.that("A peer that can't be reached: status error", state["status"] == "error", state)
    report.that("It says so", bool(state["error_message"]), state)


def external_flows(run: Run, folder: str) -> None:
    """architecture.md, "Request Flow — External participant ↔ hosted participant"."""
    external = run.external
    external.make_hosted_reachable()
    ext_owner, ext_builder = external.owner, external.builder

    opened = message_crosses(
        run, "External to hosted", ext_builder, run.owner, performative="request", payload={"summary": "From outside"}
    )
    message_crosses(
        run,
        "Hosted to external",
        run.owner,
        ext_builder,
        performative="inform",
        conversation_id=opened["conversation_id"],
        in_reply_to=opened["message_id"],
        payload={"answer": "From the hub"},
    )
    chat = opened["conversation_id"]
    mine, theirs = ext_builder.conversation(chat), run.owner.conversation(chat)
    report = run.report
    report.that(
        "Both sides read the same two messages",
        sorted(m["message_id"] for m in mine["messages"]) == sorted(m["message_id"] for m in theirs["messages"])
        and len(mine["messages"]) == 2,
    )
    report.that(
        "The request is answered on both sides",
        mine["outstanding_requests"] == [] and theirs["outstanding_requests"] == [],
    )
    file_crosses(run, "File, external to hosted", ext_builder, run.owner, folder)
    file_crosses(run, "File, hosted to external", run.owner, ext_builder, folder)

    capability_requested(run, "Capability, external asks hosted", ext_builder, run.owner, "twin:history")
    capability_requested(run, "Capability, hosted asks external", run.builder, ext_owner, "twin:history")
    closes_cross(run, "Crossing closes, external and hosted", ext_builder, run.owner)
    peer_route_keeps_its_limits(run)
    burst_crosses(run, "At once, external to hosted", ext_builder, run.owner)
    burst_crosses(run, "At once, hosted to external", run.owner, ext_builder)
    if run.other:
        unreachable_peer(run)

    message_crosses(run, "External to external", ext_owner, ext_builder, performative="inform", payload={"a": 1})
    file_crosses(run, "File, external to external", ext_builder, ext_owner, folder)


def all_of_it(run: Run) -> None:
    report = run.report
    with tempfile.TemporaryDirectory(prefix="contract-") as folder:
        sections = [
            ("discovery", lambda: discovery(run)),
            ("sending", lambda: sending(run)),
            ("receiving", lambda: receiving(run)),
            ("files", lambda: files(run, folder)),
            ("conversation rules", lambda: rules(run)),
            ("capabilities", lambda: capabilities(run)),
            ("flow.md, the worked example", lambda: flow_worked_example(run, folder)),
            ("flow.md, escalation", lambda: flow_escalation(run)),
            ("flow.md, reopening", lambda: flow_reopening(run)),
            ("the worked scenario", lambda: worked_scenario(run, folder)),
        ]
        if run.external:
            sections.append(("architecture.md, external participants", lambda: external_flows(run, folder)))
        for name, section in sections:
            print(f"\n--- {name}")
            try:
                section()
            except Exception as error:  # the report goes on to the next section, and counts this
                report.note(f"Section {name} stopped", [f"{type(error).__name__}: {error}"[:600]])
                traceback.print_exc(limit=3)
    if not run.external:
        report.not_run.append(
            "flow.md, external participants: none here. With a local environment, run scripts/external-demo.py up. "
            "Otherwise give --external-owner and --external-builder"
        )


# --- A proxy that changes answers, to show that the suite fails ----------------------------------------------
def remove_field(value: object, field: str) -> object:
    if isinstance(value, list):
        return [remove_field(item, field) for item in value]
    if isinstance(value, dict):
        return {key: item for key, item in value.items() if key != field}
    return value


@contextlib.contextmanager
def tamper_proxy(gateway: str, rule: str) -> Iterator[str]:
    """In front of the gateway. Answers on a route matching 'METHOD /path/*:field' lose it."""
    route, _, field = rule.rpartition(":")
    method, _, pattern = route.partition(" ")
    matcher = re.compile(re.escape(pattern).replace(r"\*", "[^/]+") + "$")
    touched = {"count": 0}

    class Handler(http.server.BaseHTTPRequestHandler):
        def _forward(self) -> None:
            length = int(self.headers.get("Content-Length") or 0)
            body = self.rfile.read(length) if length else None
            forwarded = {k: v for k, v in self.headers.items() if k.lower() not in {"host", "content-length"}}
            status, content, headers = watching_for_an_early_answer(gateway, self.command, self.path, forwarded, body)
            if self.command == method and matcher.match(self.path.split("?")[0]) and status < 300:
                content = json.dumps(remove_field(json.loads(content), field)).encode()
                touched["count"] += 1
            self.send_response(status)
            for name, value in headers.items():
                if name.lower() not in {"content-length", "transfer-encoding", "connection"}:
                    self.send_header(name, value)
            self.send_header("Content-Length", str(len(content)))
            self.end_headers()
            self.wfile.write(content)

        do_GET = do_POST = do_PATCH = do_DELETE = _forward

        def log_message(self, *_args) -> None:
            pass

    server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{server.server_address[1]}"
    finally:
        server.shutdown()
        print(f"The proxy changed {touched['count']} answers on {route}")


# --- Participants -----------------------------------------------------------------------------------------------------
def json_call(method: str, url: str, body: object = None, token: str | None = None) -> tuple[int, object]:
    data = None if body is None else json.dumps(body).encode()
    call = urllib.request.Request(url, data, method=method)
    if data:
        call.add_header("Content-Type", "application/json")
    if token:
        call.add_header("Authorization", f"Bearer {token}")
    try:
        with urllib.request.urlopen(call, timeout=420) as response:
            status, content = response.status, response.read()
    except urllib.error.HTTPError as error:
        status, content = error.code, error.read()
    return status, json.loads(content) if content else None


@contextlib.contextmanager
def own_participants(management: str, admin_secret: str, keycloak: str, gateway: str) -> Iterator[tuple]:
    """Create the participants this run uses, through the management API, and remove them whatever happens."""

    def admin_token() -> str:
        # A long run can outlast a token.
        status, answer = json_call(
            "POST", f"{management}/api/admin/token", {"client_id": "dataspace-admin-cli", "client_secret": admin_secret}
        )
        if status != 200:
            raise SystemExit(f"No admin token: {status} {answer}")
        return answer["access_token"]

    token = admin_token()
    tag = uuid.uuid4().hex[:8]
    owner_id, builder_id, other_id = (f"urn:contract:{tag}:{name}" for name in ("owner", "builder", "other"))
    made = []
    try:
        clients = []
        for participant, kind in ((owner_id, "factory_owner"), (builder_id, "machine_builder")):
            status, record = json_call(
                "POST",
                f"{management}/api/participants",
                {"participant_id": participant, "participant_type": kind},
                token,
            )
            if status != 200:
                raise SystemExit(f"Could not register {participant}: {status} {record}")
            made.append(participant)
            clients.append(DataspaceClient(gateway, keycloak, participant, record["client_secret"]))
        # Registered only, with the same role as the owner, so that it is an incompatible peer.
        status, record = json_call(
            "POST",
            f"{management}/api/participants",
            {
                "participant_id": other_id,
                "participant_type": "factory_owner",
                "hosted": False,
                "adapter_url": "http://nowhere.invalid:8000",
                "dsp_url": "http://nowhere.invalid:8082/api/v1/dsp",
            },
            token,
        )
        if status != 200:
            raise SystemExit(f"Could not register {other_id}: {status} {record}")
        made.append(other_id)

        def make_reachable() -> None:
            for participant, kind in ((owner_id, "factory_owner"), (builder_id, "machine_builder")):
                body = {"participant_id": participant, "participant_type": kind, "externally_reachable": True}
                status, record = json_call("POST", f"{management}/api/participants", body, admin_token())
                if status != 200 or not record["peer_notify_url"]:
                    raise AssertionError(f"Could not make {participant} reachable: {status} {record}")

        yield clients[0], clients[1], other_id, make_reachable
    finally:
        token = admin_token()
        for participant in made:
            quoted = urllib.parse.quote(participant, safe=":")
            status, answer = json_call("DELETE", f"{management}/api/participants/{quoted}", None, token)
            print(f"Removed {participant}: {status}")


def run_suite(
    owner: DataspaceClient, builder: DataspaceClient, other: str | None, external: External | None = None
) -> int:
    report = Report()
    all_of_it(Run(report, owner, builder, other, external))
    return report.finish()


def external_client(given: str, keycloak: str) -> DataspaceClient:
    """From ADAPTER_URL,ID,SECRET. An external agent calls its own adapter, not the gateway."""
    url, _, rest = given.partition(",")
    participant, _, secret = rest.rpartition(",")
    return DataspaceClient(url, keycloak, participant, secret)


def main() -> int:
    top = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    top.add_argument("--self-test", action="store_true")
    top.add_argument("--local", action="store_true")
    top.add_argument("--gateway-url")
    top.add_argument("--keycloak-url", help="Including any path such as /auth")
    top.add_argument("--management-url")
    top.add_argument("--admin-secret", default=os.environ.get("DATASPACE_ADMIN_SECRET"))
    top.add_argument("--owner", help="id:secret of a factory owner. The secret comes after the last colon")
    top.add_argument("--builder", help="id:secret of a machine builder")
    top.add_argument("--external-owner", help="adapter_url,id,secret of an external factory owner")
    top.add_argument("--external-builder", help="adapter_url,id,secret of an external machine builder")
    top.add_argument(
        "--tamper", help="METHOD /path/*:field. Remove a field from a route's answers, so the run must fail"
    )
    args = top.parse_args()

    if args.self_test:
        return self_test()

    def against(
        gateway: str, keycloak: str, management: str | None, secret: str | None, externals: tuple | None = None
    ) -> int:
        if args.tamper:
            with tamper_proxy(gateway, args.tamper) as proxied:
                return against_this(proxied, keycloak, management, secret, externals)
        return against_this(gateway, keycloak, management, secret, externals)

    def against_this(
        gateway: str, keycloak: str, management: str | None, secret: str | None, externals: tuple | None
    ) -> int:
        def external(make_reachable: Callable[[], None]) -> External | None:
            if externals is None:
                return None
            return External(externals[0], externals[1], gateway, keycloak, make_reachable)

        if management:
            with own_participants(management, secret, keycloak, gateway) as (owner, builder, other, make_reachable):
                return run_suite(owner, builder, other, external(make_reachable))
        owner_id, _, owner_secret = args.owner.rpartition(":")
        builder_id, _, builder_secret = args.builder.rpartition(":")
        owner = DataspaceClient(gateway, keycloak, owner_id, owner_secret)
        builder = DataspaceClient(gateway, keycloak, builder_id, builder_secret)
        # Existing participants are as they are. They have to be externally reachable already.
        return run_suite(owner, builder, None, external(lambda: None))

    if args.local:
        import local_cluster as lc

        secret = (lc.LOCAL / "admin-client-secret").read_text().strip()
        state_file = lc.LOCAL / "external-demo.json"
        demo = json.loads(state_file.read_text()) if state_file.exists() else None
        with (
            lc.port_forward("dataspace", "gateway", 8080) as gateway,
            lc.port_forward("dataspace", "management", 3000) as management,
            lc.port_forward("iff", "keycloak-service", 8080) as keycloak,
        ):
            if demo is None:
                return against(gateway, f"{keycloak}/auth", management, secret)
            own, build = demo["external-factory-owner"], demo["external-machine-builder"]
            with (
                lc.port_forward("external-factory-owner", "adapter", 8000) as owner_adapter,
                lc.port_forward("external-machine-builder", "adapter", 8000) as builder_adapter,
            ):
                realm = f"{keycloak}/auth"
                externals = (
                    DataspaceClient(owner_adapter, realm, own["participant_id"], own["client_secret"]),
                    DataspaceClient(builder_adapter, realm, build["participant_id"], build["client_secret"]),
                )
                return against(gateway, realm, management, secret, externals)

    if not (args.gateway_url and args.keycloak_url):
        top.error("Give --self-test, --local, or --gateway-url and --keycloak-url")
    if bool(args.external_owner) != bool(args.external_builder):
        top.error("Give both --external-owner and --external-builder, or neither")
    externals = None
    if args.external_owner:
        externals = (
            external_client(args.external_owner, args.keycloak_url),
            external_client(args.external_builder, args.keycloak_url),
        )
    if args.management_url:
        return against(args.gateway_url, args.keycloak_url, args.management_url, args.admin_secret, externals)
    if not (args.owner and args.builder):
        top.error("Give --management-url with --admin-secret, or --owner and --builder")
    return against(args.gateway_url, args.keycloak_url, None, None, externals)


if __name__ == "__main__":
    sys.exit(main())
