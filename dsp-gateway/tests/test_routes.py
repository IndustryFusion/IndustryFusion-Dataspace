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

import gzip

import httpx
import pytest
from fastapi.testclient import TestClient

from app.main import Settings, create_app

SLUG = "2593a25b"


class World:
    def __init__(self) -> None:
        self.forwarded: list[httpx.Request] = []
        self.answer: httpx.Response | None = None
        self.error: Exception | None = None

    def handle(self, request: httpx.Request) -> httpx.Response:
        if self.error:
            raise self.error
        self.forwarded.append(request)
        return self.answer or httpx.Response(201, json={"at": str(request.url)}, headers={"X-From": "connector"})


@pytest.fixture
def world():
    return World()


@pytest.fixture
def client(world):
    http = httpx.AsyncClient(transport=httpx.MockTransport(world.handle))
    return TestClient(create_app(Settings(participants_namespace="the-participants"), http))


@pytest.mark.parametrize(
    ("kind", "port"),
    [("dsp", 8082), ("public", 8084)],
)
def test_a_call_reaches_the_slugs_port(client, world, kind, port):
    answer = client.post(
        f"/{SLUG}/api/v1/{kind}/catalog/request?a=1",
        content=b"the body",
        headers={"Authorization": "Bearer t", "X-Other": "kept", "Content-Type": "application/json"},
    )
    assert answer.status_code == 201
    assert answer.headers["X-From"] == "connector"
    forwarded = world.forwarded[0]
    assert str(forwarded.url) == (
        f"http://connector-{SLUG}.the-participants:{port}/api/v1/{kind}/catalog/request?a=1"
    )
    assert forwarded.content == b"the body"
    assert forwarded.headers["authorization"] == "Bearer t"
    assert forwarded.headers["x-other"] == "kept"
    assert forwarded.headers["host"] == f"connector-{SLUG}.the-participants:{port}"


@pytest.mark.parametrize("method", ["GET", "POST", "PUT", "DELETE", "PATCH"])
def test_each_method_passes(client, world, method):
    assert client.request(method, f"/{SLUG}/api/v1/public/v2/x").status_code == 201
    assert world.forwarded[0].method == method


def test_an_encoded_part_stays_encoded(client, world):
    client.get(f"/{SLUG}/api/v1/dsp/negotiations/urn%3Aa%2Fb")
    assert world.forwarded[0].url.raw_path.decode() == "/api/v1/dsp/negotiations/urn%3Aa%2Fb"


@pytest.mark.parametrize(
    "slug",
    [
        "2593a25",
        "2593a25bb",
        "2593A25B",
        "2593a25g",
        "evil.example",
        "2593a25b.other",
        "2593a25b%2e",
        "..",
        "%2e%2e",
    ],
)
def test_what_is_not_a_slug_is_refused(client, world, slug):
    assert client.get(f"/{slug}/api/v1/dsp/x").status_code == 404
    assert world.forwarded == []


@pytest.mark.parametrize(
    "path",
    [
        "/{s}/api/v1/dsp/../control",
        "/{s}/api/v1/dsp/%2e%2e/control",
        "/{s}/api/v1/dsp/%2E%2E%2Fcontrol",
        "/{s}/api/v1/dsp/%252e%252e%252fcontrol",
        "/{s}/api/v1/dsp/..%5ccontrol",
        "/{s}/api/v1/dsp/a/..;/..;/control",
        "/{s}/api/v1/public/../../management/v3/assets",
    ],
)
def test_a_path_cannot_leave_its_prefix(client, world, path):
    # The client would tidy a plain "..", so the raw form is sent as it is.
    raw = httpx.URL("http://testserver").copy_with(raw_path=path.format(s=SLUG).encode())
    assert client.get(raw).status_code == 404
    assert world.forwarded == []


@pytest.mark.parametrize(
    "path",
    [
        "/",
        "/{s}",
        "/{s}/api/v1/dsp",
        "/{s}/api/v1/dsp/",
        "/{s}/api/v1/control/x",
        "/{s}/control/x",
        "/{s}/management/v3/assets",
        "/{s}/api/v2/dsp/x",
        "/{s}/x/v1/dsp/y",
        "/api/v1/dsp/x",
    ],
)
def test_only_the_two_prefixes_are_routed(client, world, path):
    assert client.get(path.format(s=SLUG)).status_code == 404
    assert world.forwarded == []


def test_no_address_on_another_port_can_be_made(client, world):
    for kind in ("dsp", "public"):
        client.get(f"/{SLUG}/api/v1/{kind}/x")
    assert {request.url.port for request in world.forwarded} == {8082, 8084}


def test_a_connector_that_is_not_there(client, world):
    world.error = httpx.ConnectError("no such host")
    answer = client.get(f"/{SLUG}/api/v1/dsp/x")
    assert answer.status_code == 503
    assert "detail" in answer.json()


def test_a_connector_that_is_too_slow(client, world):
    world.error = httpx.ReadTimeout("slow")
    assert client.get(f"/{SLUG}/api/v1/dsp/x").status_code == 504


def test_a_connectors_refusal_comes_back_as_it_is(client, world):
    world.answer = httpx.Response(401, json={"dspace:code": "401"})
    answer = client.post(f"/{SLUG}/api/v1/dsp/catalog/request", json={})
    assert answer.status_code == 401
    assert answer.json() == {"dspace:code": "401"}


def test_a_compressed_answer_arrives_decoded_and_says_so(client, world):
    content = gzip.compress(b'{"a": 1}')
    world.answer = httpx.Response(200, content=content, headers={"Content-Encoding": "gzip"})
    answer = client.get(f"/{SLUG}/api/v1/dsp/x")
    assert answer.json() == {"a": 1}
    assert "content-encoding" not in answer.headers


def test_a_large_body_passes_whole(client, world):
    body = b"x" * (5 * 1024 * 1024)
    assert client.post(f"/{SLUG}/api/v1/public/v2/x", content=body).status_code == 201
    assert world.forwarded[0].content == body
