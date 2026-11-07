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
"""File transfer: uploading, bundling, arrival, download and the upload limit."""

import io
import json
import os
import tempfile
import tracemalloc
import zipfile
from dataclasses import replace
from datetime import timedelta

import pytest
from botocore.exceptions import EndpointConnectionError
from conftest import PEER, auth
from sqlalchemy import func, select

from app.bundle import safe_name
from app.db import InboxMessage, OutboxMessage, now
from app.limits import limit_for
from app.retention import purge_expired


def upload(harness, *files, headers=None, settle=True, **fields):
    form = {"receiver_participant": PEER, **fields}
    parts = [("files", item) for item in files]
    response = harness.client.post("/outbox/files", data=form, files=parts, headers=headers or auth())
    if settle:
        harness.settle()
    return response


def unpack(content: bytes) -> dict[str, bytes]:
    with zipfile.ZipFile(io.BytesIO(content)) as archive:
        assert archive.testzip() is None
        return {name: archive.read(name) for name in archive.namelist()}


def stored_bundle(harness, message_id: str) -> bytes:
    return harness.client.get(f"/internal/payload/{message_id}").content


def arrive(harness, message_id: str = "m1", content: bytes = b"zip bytes", **fields) -> None:
    assert harness.notify(message_id, has_files=True, **fields).status_code == 202
    harness.settle()
    answer = harness.client.post(f"/internal/inbox-receive/{message_id}", content=content)
    assert answer.status_code == 200, answer.text


def outbox_count(harness) -> int:
    async def count() -> int:
        async with harness.services.db.session() as session:
            return await session.scalar(select(func.count()).select_from(OutboxMessage))

    return harness.run(count)


def test_several_files_are_accepted_and_offered(harness):
    response = upload(harness, ("a.bin", b"first"), ("b.bin", b"\x00\xff second"))
    assert response.status_code == 202
    body = response.json()
    assert set(body) == {"message_id", "status", "applied", "conversation_state"}
    message_id = body["message_id"]
    assert harness.world.notifications[0]["body"]["has_files"] is True
    assert harness.connector.offered[0][0] == message_id
    status = harness.client.get(f"/outbox/messages/{message_id}/status", headers=auth()).json()
    assert status["status"] == "notified"
    assert f"s3://test/files/{message_id}.zip" in harness.storage.objects


def test_payload_route_serves_the_zip_with_the_same_bytes(harness):
    message_id = upload(harness, ("a.bin", b"first"), ("b.bin", b"\x00\xff second")).json()["message_id"]
    answer = harness.client.get(f"/internal/payload/{message_id}")
    assert answer.headers["content-type"] == "application/zip"
    assert unpack(answer.content) == {"a.bin": b"first", "b.bin": b"\x00\xff second"}


def test_end_to_end_between_routes_gives_the_same_bytes(harness):
    files = {"data.csv": os.urandom(3 * 1024 * 1024), "empty.txt": b"", "notes.txt": "grüße".encode()}
    message_id = upload(harness, *files.items()).json()["message_id"]
    arrive(harness, "received", stored_bundle(harness, message_id))
    answer = harness.client.get("/inbox/messages/received/download", headers=auth())
    assert answer.status_code == 200
    assert answer.headers["content-type"] == "application/zip"
    assert "received.zip" in answer.headers["content-disposition"]
    assert int(answer.headers["content-length"]) == len(answer.content)
    assert unpack(answer.content) == files


@pytest.mark.parametrize(
    "fields, parts",
    [
        ({"receiver_participant": PEER}, []),
        ({"receiver_participant": PEER, "files": "not a file"}, []),
        ({}, [("files", ("a", b"x"))]),
    ],
)
def test_no_files_or_no_receiver_is_invalid_and_stores_nothing(harness, fields, parts):
    response = harness.client.post("/outbox/files", data=fields, files=parts or {"other": ("a", b"x")}, headers=auth())
    assert response.status_code == 422
    assert harness.storage.objects == {}
    assert outbox_count(harness) == 0


def test_a_body_that_is_not_a_form_is_invalid(harness):
    response = harness.client.post("/outbox/files", json={"receiver_participant": PEER}, headers=auth())
    assert response.status_code == 422


def test_a_malformed_form_is_invalid(harness):
    headers = {**auth(), "Content-Type": "multipart/form-data; boundary=x"}
    response = harness.client.post("/outbox/files", content=b"--x\r\nbroken", headers=headers)
    assert response.status_code == 422


def test_unregistered_receiver(harness):
    response = upload(harness, ("a", b"x"), receiver_participant="urn:test:nobody")
    assert response.status_code == 404
    assert harness.storage.objects == {}
    assert outbox_count(harness) == 0


def test_incompatible_receiver(harness):
    harness.world.compatible = []
    response = upload(harness, ("a", b"x"))
    assert response.status_code == 403
    assert harness.storage.objects == {}
    assert outbox_count(harness) == 0


def test_no_token_is_refused_before_the_body_is_read(harness):
    reads = []

    async def call() -> list[dict]:
        sent = []

        async def receive() -> dict:
            reads.append(1)
            return {"type": "http.request", "body": b"x", "more_body": False}

        async def send(message: dict) -> None:
            sent.append(message)

        scope = {
            "type": "http",
            "asgi": {"version": "3.0"},
            "http_version": "1.1",
            "method": "POST",
            "path": "/outbox/files",
            "raw_path": b"/outbox/files",
            "query_string": b"",
            "root_path": "",
            "scheme": "http",
            "server": ("adapter", 8000),
            "client": ("test", 1),
            "headers": [(b"content-type", b"multipart/form-data; boundary=x")],
        }
        await harness.client.app(scope, receive, send)
        return sent

    sent = harness.run(call)
    assert sent[0]["status"] == 401
    assert reads == []


def test_storage_failure_records_nothing_and_leaves_no_temporary_file(harness, monkeypatch, tmp_path):
    folder = tmp_path / "temporary"
    folder.mkdir()
    monkeypatch.setattr(tempfile, "tempdir", str(folder))

    async def down(_key: str, _path: str) -> None:
        raise EndpointConnectionError(endpoint_url="http://s3.test")

    monkeypatch.setattr(harness.storage, "put_file", down)
    response = upload(harness, ("a", b"x"))
    assert response.status_code == 503
    assert outbox_count(harness) == 0
    assert list(folder.iterdir()) == []


def test_no_temporary_file_is_left_after_success(harness, monkeypatch, tmp_path):
    folder = tmp_path / "temporary"
    folder.mkdir()
    monkeypatch.setattr(tempfile, "tempdir", str(folder))
    message_id = upload(harness, ("a", b"x")).json()["message_id"]
    arrive(harness, "received", stored_bundle(harness, message_id))
    assert list(folder.iterdir()) == []


@pytest.mark.parametrize(
    "raw, expected",
    [
        ("../../etc/passwd", "passwd"),
        ("..\\..\\windows\\system.ini", "system.ini"),
        ("/absolute/path.txt", "path.txt"),
        ("folder/", "file-3"),
        ("..", "file-3"),
        (".", "file-3"),
        ("   ", "file-3"),
        ("", "file-3"),
        ("na\x00me\n.txt", "name.txt"),
        ("plain.csv", "plain.csv"),
    ],
)
def test_safe_names(raw, expected):
    assert safe_name(raw, 3, set()) == expected


def test_a_very_long_name_is_shortened_and_keeps_its_ending():
    name = safe_name("x" * 5000 + ".csv", 1, set())
    assert len(name) == 200
    assert name.endswith(".csv")


def test_names_in_the_bundle_are_safe_and_all_files_are_kept(harness):
    message_id = upload(
        harness,
        ("../../evil.txt", b"one"),
        ("evil.txt", b"two"),
        ("EVIL.txt", b"three"),
        ("sub/evil.txt", b"four"),
    ).json()["message_id"]
    contents = unpack(stored_bundle(harness, message_id))
    assert contents == {"evil.txt": b"one", "evil-2.txt": b"two", "EVIL-3.txt": b"three", "evil-4.txt": b"four"}


def test_received_file_message_reads_as_a_bundle(harness):
    assert harness.notify("m1", has_files=True).status_code == 202
    harness.settle()
    before = harness.client.get("/inbox/messages/m1", headers=auth()).json()
    assert before["has_files"] is True
    assert before["payload"] is None

    assert harness.client.post("/internal/inbox-receive/m1", content=b"zip bytes").status_code == 200
    assert "s3://test/files/m1.zip" in harness.storage.objects
    assert "s3://test/messages/m1.json" not in harness.storage.objects
    message = harness.client.get("/inbox/messages/m1", headers=auth()).json()
    assert message["status"] == "received"
    assert message["payload"] == {"_bundle": True}
    listed = harness.client.get("/inbox/messages", headers=auth()).json()
    assert listed[0]["payload"] == {"_bundle": True}


def test_ordinary_message_has_no_download(harness):
    assert harness.notify("m1").status_code == 202
    harness.settle()
    assert harness.client.post("/internal/inbox-receive/m1", json={"a": 1}).status_code == 200
    message = harness.client.get("/inbox/messages/m1", headers=auth()).json()
    assert message["has_files"] is False
    assert harness.client.get("/inbox/messages/m1/download", headers=auth()).status_code == 400


def test_download_before_arrival_is_not_found(harness):
    assert harness.notify("m1", has_files=True).status_code == 202
    harness.settle()
    assert harness.client.get("/inbox/messages/m1/download", headers=auth()).status_code == 404


def test_download_of_unknown_message_is_not_found(harness):
    assert harness.client.get("/inbox/messages/nothing/download", headers=auth()).status_code == 404


def test_download_needs_this_participants_token(harness):
    arrive(harness)
    assert harness.client.get("/inbox/messages/m1/download").status_code == 401
    assert harness.client.get("/inbox/messages/m1/download", headers=auth(PEER)).status_code == 403


def test_download_when_the_object_is_gone_is_not_found(harness):
    arrive(harness)
    harness.storage.objects.clear()
    assert harness.client.get("/inbox/messages/m1/download", headers=auth()).status_code == 404


def test_storage_outage_on_download_is_unavailable(harness, monkeypatch):
    arrive(harness)

    async def down(_ref: str) -> None:
        raise EndpointConnectionError(endpoint_url="http://s3.test")

    monkeypatch.setattr(harness.storage, "read_stream", down)
    assert harness.client.get("/inbox/messages/m1/download", headers=auth()).status_code == 503


def test_reply_file_links_to_the_original(harness):
    response = upload(harness, ("a", b"x"), in_reply_to="original", conversation_id="c7", capability="twin:direct")
    assert response.status_code == 202
    sent = harness.world.notifications[0]["body"]
    assert (sent["in_reply_to"], sent["conversation_id"], sent["capability"]) == ("original", "c7", "twin:direct")
    message = harness.client.get(f"/outbox/messages/{response.json()['message_id']}", headers=auth()).json()
    assert (message["in_reply_to"], message["conversation_id"]) == ("original", "c7")

    arrive(harness, "m1", in_reply_to="original", conversation_id="c7")
    read = harness.client.get("/inbox/messages/m1", headers=auth()).json()
    assert (read["in_reply_to"], read["conversation_id"]) == ("original", "c7")


def limit_to(harness, size: int) -> None:
    harness.services.settings = replace(harness.services.settings, max_upload_bytes=size)


def test_upload_over_the_limit_with_a_stated_length(harness):
    limit_to(harness, 1000)
    response = upload(harness, ("a", b"x" * 2000))
    assert response.status_code == 413
    assert harness.storage.objects == {}
    assert outbox_count(harness) == 0


def test_upload_over_the_limit_without_a_stated_length(harness):
    limit_to(harness, 1000)
    boundary = "x"
    body = f'--{boundary}\r\nContent-Disposition: form-data; name="receiver_participant"\r\n\r\n{PEER}\r\n'.encode()
    body += f'--{boundary}\r\nContent-Disposition: form-data; name="files"; filename="a"\r\n\r\n'.encode()
    body += b"x" * 5000 + f"\r\n--{boundary}--\r\n".encode()

    def parts():
        for start in range(0, len(body), 500):
            yield body[start : start + 500]

    headers = {**auth(), "Content-Type": f"multipart/form-data; boundary={boundary}"}
    response = harness.client.post("/outbox/files", content=parts(), headers=headers)
    assert "content-length" not in {key.lower() for key in response.request.headers}
    assert response.status_code == 413
    assert harness.storage.objects == {}
    assert outbox_count(harness) == 0


def test_upload_at_the_limit_is_accepted(harness):
    limit_to(harness, 1000)
    boundary = "x"
    start = f'--{boundary}\r\nContent-Disposition: form-data; name="receiver_participant"\r\n\r\n{PEER}\r\n'.encode()
    start += f'--{boundary}\r\nContent-Disposition: form-data; name="files"; filename="a"\r\n\r\n'.encode()
    end = f"\r\n--{boundary}--\r\n".encode()
    body = start + b"x" * (1000 - len(start) - len(end)) + end
    headers = {**auth(), "Content-Type": f"multipart/form-data; boundary={boundary}"}
    assert harness.client.post("/outbox/files", content=body, headers=headers).status_code == 202
    harness.settle()


def test_a_json_message_over_the_limit_is_refused(harness):
    harness.services.settings = replace(harness.services.settings, max_json_bytes=100)
    response = harness.send(payload={"a": "x" * 500})
    assert response.status_code == 413


def test_a_json_message_with_no_stated_length_over_the_limit_is_refused(harness):
    harness.services.settings = replace(harness.services.settings, max_json_bytes=100)

    def parts():
        yield b'{"receiver_participant": "x", "payload": {"a": "'
        yield b"x" * 500
        yield b'"}}'

    headers = {**auth(), "Content-Type": "application/json"}
    assert harness.client.post("/outbox/messages", content=parts(), headers=headers).status_code == 413


@pytest.mark.parametrize("stated", [True, False])
def test_arrival_over_the_limit_marks_the_message(harness, stated):
    assert harness.notify("m1", has_files=True).status_code == 202
    harness.settle()
    limit_to(harness, 0)
    content = b"x" * (1024**2 + 1)

    def parts():
        yield content

    answer = harness.client.post("/internal/inbox-receive/m1", content=content if stated else parts())
    assert answer.status_code == 413
    assert harness.storage.objects == {}
    limit_to(harness, 1024**2)
    message = harness.client.get("/inbox/messages/m1", headers=auth()).json()
    assert message["status"] == "error"
    assert "larger" in message["error_message"]


def test_arrival_may_exceed_the_limit_by_the_zip_margin(harness):
    assert harness.notify("m1", has_files=True).status_code == 202
    harness.settle()
    limit_to(harness, 0)
    assert harness.client.post("/internal/inbox-receive/m1", content=b"x" * 1024**2).status_code == 200


def test_retention_removes_file_content(harness):
    arrive(harness)
    assert harness.client.post("/inbox/messages/m1/ack", headers=auth()).status_code == 204

    async def age() -> None:
        async with harness.services.db.session() as session:
            row = await session.get(InboxMessage, "m1")
            row.created_at = now() - timedelta(hours=25)
            await session.commit()

    harness.run(age)
    harness.run(purge_expired, harness.services)
    assert harness.storage.objects == {}
    message = harness.client.get("/inbox/messages/m1", headers=auth()).json()
    assert message["has_files"] is True
    assert message["payload"] is None
    assert harness.client.get("/inbox/messages/m1/download", headers=auth()).status_code == 404


def test_retention_leaves_unacknowledged_files(harness):
    arrive(harness)

    async def age() -> None:
        async with harness.services.db.session() as session:
            row = await session.get(InboxMessage, "m1")
            row.created_at = now() - timedelta(hours=25)
            await session.commit()

    harness.run(age)
    harness.run(purge_expired, harness.services)
    assert harness.client.get("/inbox/messages/m1/download", headers=auth()).status_code == 200


def test_sender_retention_removes_the_zip(harness):
    message_id = upload(harness, ("a", b"x")).json()["message_id"]

    async def age() -> None:
        async with harness.services.db.session() as session:
            row = await session.get(OutboxMessage, message_id)
            row.created_at = now() - timedelta(hours=25)
            await session.commit()

    harness.run(age)
    harness.run(purge_expired, harness.services)
    assert harness.storage.objects == {}
    assert harness.client.get(f"/internal/payload/{message_id}").status_code == 404


def call_with_a_counted_body(harness, path: str, body: bytes, headers: list[tuple[bytes, bytes]]) -> tuple[int, int]:
    """Call the app as a server would, in pieces, and return its status and how much of the body it read."""
    pieces = [body[start : start + 65536] for start in range(0, len(body), 65536)]
    position = {"next": 0, "read": 0}
    sent = []

    async def receive() -> dict:
        index = position["next"]
        if index < len(pieces):
            position["next"] += 1
            position["read"] += len(pieces[index])
            return {"type": "http.request", "body": pieces[index], "more_body": index + 1 < len(pieces)}
        return {"type": "http.disconnect"}

    async def send(message: dict) -> None:
        sent.append(message)

    scope = {
        "type": "http",
        "asgi": {"version": "3.0"},
        "http_version": "1.1",
        "method": "POST",
        "path": path,
        "raw_path": path.encode(),
        "query_string": b"",
        "root_path": "",
        "scheme": "http",
        "server": ("adapter", 8000),
        "client": ("test", 1),
        "headers": headers,
    }

    async def call() -> None:
        await harness.client.app(scope, receive, send)

    harness.run(call)
    return sent[0]["status"], position["read"]


JSON_ROUTES = ["/outbox/messages", "/internal/transfer-request"]


@pytest.mark.parametrize("path", JSON_ROUTES)
def test_other_routes_stop_reading_at_their_limit_without_a_stated_length(harness, path):
    body = b'{"x":"' + b"a" * (8 * 1024**2) + b'"}'
    headers = [(b"content-type", b"application/json"), (b"authorization", b"Bearer not-a-token")]
    status, read = call_with_a_counted_body(harness, path, body, headers)
    assert status == 413
    assert read <= limit_for(path, harness.services.settings) + 65536


@pytest.mark.parametrize("path", JSON_ROUTES)
def test_other_routes_read_nothing_with_a_stated_length_over_their_limit(harness, path):
    body = b"x" * (8 * 1024**2)
    headers = [(b"content-type", b"application/json"), (b"content-length", str(len(body)).encode())]
    assert call_with_a_counted_body(harness, path, body, headers) == (413, 0)


def test_only_the_file_route_has_the_large_limit(harness):
    settings = harness.services.settings
    assert limit_for("/outbox/files", settings) == settings.max_upload_bytes == 1024**3
    assert limit_for("/outbox/messages", settings) == settings.max_json_bytes == 4 * 1024**2
    assert limit_for("/internal/transfer-request", settings) == 256 * 1024
    assert limit_for("/outbox/files/", settings) == 256 * 1024


def test_validation_errors_do_not_repeat_the_input(harness):
    marker = "m" * 5000
    bodies = [
        {"receiver_participant": 1, "payload": {"a": marker}, "expires_at": marker},
        {"receiver_participant": marker * 2, "payload": {}},
    ]
    for body in bodies:
        response = harness.client.post("/outbox/messages", json=body, headers=auth())
        assert response.status_code == 422
        assert marker not in response.text
        assert all(set(item) <= {"loc", "msg", "type"} for item in response.json()["detail"])
    notification = {"message_id": "m1", "conversation_id": marker, "sender_participant": PEER}
    response = harness.client.post("/internal/transfer-request", json=notification)
    assert response.status_code == 422
    assert marker not in response.text


def test_stored_json_is_no_larger_than_its_body(harness):
    text = "é" * 1000 + "\u4e16" * 1000
    body = json.dumps({"receiver_participant": PEER, "payload": {"t": text}}, ensure_ascii=False).encode()
    headers = {**auth(), "Content-Type": "application/json"}
    response = harness.client.post("/outbox/messages", content=body, headers=headers)
    harness.settle()
    assert response.status_code == 202
    stored = harness.storage.objects[f"s3://test/messages/{response.json()['message_id']}.json"]
    assert len(stored) <= len(body)
    assert json.loads(stored) == {"t": text}


def test_a_lone_surrogate_is_stored_as_the_escape_it_came_as(harness):
    body = b'{"receiver_participant": "' + PEER.encode() + b'", "payload": {"t": "\\ud800"}}'
    headers = {**auth(), "Content-Type": "application/json"}
    response = harness.client.post("/outbox/messages", content=body, headers=headers)
    harness.settle()
    assert response.status_code == 202
    assert harness.storage.objects[f"s3://test/messages/{response.json()['message_id']}.json"] == b'{"t":"\\ud800"}'


def test_arrival_without_files_has_the_json_limit(harness):
    assert harness.notify("plain").status_code == 202
    harness.settle()
    harness.services.settings = replace(harness.services.settings, max_json_bytes=10)
    assert harness.client.post("/internal/inbox-receive/plain", content=b"x" * 11).status_code == 413
    harness.services.settings = replace(harness.services.settings, max_json_bytes=4 * 1024**2)
    assert harness.client.get("/inbox/messages/plain", headers=auth()).json()["status"] == "error"


@pytest.mark.parametrize(
    "raw, expected",
    [
        ("C:evil.exe", "evil.exe"),
        ("C:..", "file-3"),
        ("c:/../x", "x"),
        ("foo\\bar:baz.txt", "baz.txt"),
        ("CON", "_CON"),
        ("con.txt", "_con.txt"),
        ("Lpt1", "_Lpt1"),
        ("CON.", "_CON"),
        ("evil.exe. . ", "evil.exe"),
        ("\u202eevil", "evil"),
        ("console.txt", "console.txt"),
    ],
)
def test_names_with_a_meaning_to_a_file_system(raw, expected):
    assert safe_name(raw, 3, set()) == expected


def test_too_many_files_or_fields_are_invalid(harness):
    many = [("files", (f"f{number}", b"x")) for number in range(257)]
    form = {"receiver_participant": PEER}
    assert harness.client.post("/outbox/files", data=form, files=many, headers=auth()).status_code == 422
    fields = {f"field{number}": "x" for number in range(20)}
    answer = harness.client.post(
        "/outbox/files", data={**form, **fields}, files=[("files", ("a", b"x"))], headers=auth()
    )
    assert answer.status_code == 422
    answer = harness.client.post(
        "/outbox/files", data={**form, "capability": "x" * 70000}, files=[("files", ("a", b"x"))], headers=auth()
    )
    assert answer.status_code == 422
    assert harness.storage.objects == {}


def test_many_small_parts_stay_out_of_memory(harness, monkeypatch):
    """100 parts of 512 KiB each. The body is generated as it is read, and storage discards it."""
    part = b"z" * (512 * 1024)
    boundary = "x"
    chunks = [f'--{boundary}\r\nContent-Disposition: form-data; name="receiver_participant"\r\n\r\n{PEER}\r\n'.encode()]
    for number in range(100):
        start = f'--{boundary}\r\nContent-Disposition: form-data; name="files"; filename="f{number}"\r\n\r\n'
        chunks += [start.encode(), part, b"\r\n"]
    chunks.append(f"--{boundary}--\r\n".encode())
    sent = []

    position = {"next": 0}

    async def next_chunk() -> dict:
        index = position["next"]
        position["next"] += 1
        return {"type": "http.request", "body": chunks[index], "more_body": index + 1 < len(chunks)}

    async def send(message: dict) -> None:
        sent.append(message)

    async def discard(key: str, _path: str) -> str:
        return f"s3://test/{key}"

    monkeypatch.setattr(harness.storage, "put_file", discard)
    scope = {
        "type": "http",
        "asgi": {"version": "3.0"},
        "http_version": "1.1",
        "method": "POST",
        "path": "/outbox/files",
        "raw_path": b"/outbox/files",
        "query_string": b"",
        "root_path": "",
        "scheme": "http",
        "server": ("adapter", 8000),
        "client": ("test", 1),
        "headers": [
            (b"content-type", f"multipart/form-data; boundary={boundary}".encode()),
            (b"authorization", auth()["Authorization"].encode()),
        ],
    }

    async def call() -> int:
        tracemalloc.start()
        try:
            await harness.client.app(scope, next_chunk, send)
            return tracemalloc.get_traced_memory()[1]
        finally:
            tracemalloc.stop()

    peak = harness.run(call)
    harness.settle()
    assert sent[0]["status"] == 202
    assert peak < 20 * 1024**2, f"{peak / 1024**2:.0f} MiB of 50 MiB stayed in memory"


def compact_numbers(total: int) -> bytes:
    """A compact JSON body of about this size, holding numbers."""
    count = (total - 200) // 2
    return b'{"receiver_participant":"' + PEER.encode() + b'","payload":{"n":[' + b"7," * count + b"7]}}"


def test_a_compact_numeric_array_under_the_limit_arrives_whole(harness):
    limit = harness.services.settings.max_json_bytes
    body = compact_numbers(limit)
    assert len(body) <= limit
    response = harness.client.post(
        "/outbox/messages", content=body, headers={**auth(), "Content-Type": "application/json"}
    )
    harness.settle()
    assert response.status_code == 202
    message_id = response.json()["message_id"]
    assert harness.client.get(f"/outbox/messages/{message_id}/status", headers=auth()).json()["status"] == "notified"
    stored = harness.storage.objects[f"s3://test/messages/{message_id}.json"]
    assert len(stored) <= limit, "The stored size has to fit the limit on arrival"
    assert harness.notify("arrived", conversation_id="other").status_code == 202
    harness.settle()
    assert harness.client.post("/internal/inbox-receive/arrived", content=stored).status_code == 200


def test_a_payload_that_grows_past_the_limit_when_stored_is_refused(harness):
    limit = harness.services.settings.max_json_bytes
    count = (limit - 200) // 4
    body = b'{"receiver_participant":"' + PEER.encode() + b'","payload":{"n":[' + b"1e5," * count + b"1e5]}}"
    assert len(body) <= limit
    before = len(harness.storage.objects)
    response = harness.client.post(
        "/outbox/messages", content=body, headers={**auth(), "Content-Type": "application/json"}
    )
    assert response.status_code == 413
    assert "payload" in response.json()["detail"]
    harness.settle()
    assert len(harness.storage.objects) == before
    assert harness.world.notifications == []


def test_an_authorization_a_notification_cannot_carry_is_refused(harness):
    big = {"scope": "conversation", "constraints": {"machines": ["m" * 100] * 3000}}
    response = harness.send(performative="grant", capability="twin:direct", in_reply_to="x", authorization=big)
    assert response.status_code == 413
    assert "authorization" in response.json()["detail"]
    assert harness.world.notifications == []


def test_the_largest_authorization_fits_the_notification_route(harness):
    from app.routes.outbox import LONGEST_AUTHORIZATION_BYTES

    filler = "m" * (LONGEST_AUTHORIZATION_BYTES - 100)
    response = harness.send(
        performative="grant",
        capability="twin:direct",
        in_reply_to="x",
        authorization={"scope": "conversation", "note": filler},
    )
    assert response.status_code == 202, response.text
    harness.settle()
    notification = harness.world.notifications[-1]["body"]
    assert len(json.dumps(notification).encode()) < 256 * 1024


def test_a_too_long_form_field_is_named(harness):
    response = upload(harness, ("a.txt", b"x"), capability="c" * 513, settle=False)
    assert response.status_code == 422
    assert response.json()["detail"] == "capability is too long"


def test_a_missing_form_field_is_named(harness):
    response = harness.client.post("/outbox/files", data={}, files={"files": ("a.txt", b"x")}, headers=auth())
    assert response.status_code == 422
    assert response.json()["detail"] == "receiver_participant is required"


@pytest.mark.parametrize(
    "name", ["a" * 199 + " " + "b" * 50, "a" * 199 + "." + "b" * 50, "x" * 180 + " .abcdefghijklmnopqrs tuv"]
)
def test_shortening_a_name_leaves_no_trailing_space_or_dot(name):
    result = safe_name(name, 1, set())
    assert result == result.rstrip(". ")
    assert not os.path.splitext(result)[0].endswith((" ", "."))
    assert len(result) <= 220


@pytest.mark.parametrize(
    "fields",
    [{"asset_id": "a" * 513}, {"provider_dsp_url": "http://x/" + "a" * 2048}],
    ids=["asset_id", "provider_dsp_url"],
)
def test_a_notification_with_too_long_an_address_is_refused(harness, fields):
    assert harness.notify("m", **fields).status_code == 422
    assert harness.client.get("/inbox/messages/m", headers=auth()).status_code == 404


def test_a_content_reference_with_too_long_an_address_is_refused(harness):
    answer = harness.send(content_ref={"asset_id": "a" * 513, "dsp_url": "http://x"}, payload=None)
    assert answer.status_code == 422
