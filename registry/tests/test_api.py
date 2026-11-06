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

import asyncio

import pytest
from fastapi.testclient import TestClient

from app import roles
from app.main import app, connect_with_retry
from app.store import MemoryStore

IRI = roles.ONTOLOGY
FO = {"participant_id": "urn:test:fo", "participant_type": "factory_owner", "adapter_url": "http://fo"}
MB = {"participant_id": "urn:test:mb", "participant_type": "machine_builder", "adapter_url": "http://mb"}


@pytest.fixture
def client():
    app.state.store = MemoryStore()
    with TestClient(app) as test_client:
        yield test_client
    app.state.store = None


def test_create_and_read_has_all_fields(client):
    body = {
        **MB,
        "dsp_url": "http://mb/dsp",
        "hosted": False,
        "externally_reachable": True,
        "peer_notify_url": "http://mb/peer",
    }
    assert client.post("/participants", json=body).status_code == 200
    expected = {**body, "participant_type": IRI + "machine_builder"}
    assert client.get("/participants/urn:test:mb").json() == expected


def test_defaults():
    with_defaults = {"participant_id": "urn:x", "participant_type": "machine_builder"}
    app.state.store = MemoryStore()
    with TestClient(app) as test_client:
        record = test_client.post("/participants", json=with_defaults).json()
    app.state.store = None
    assert record["hosted"] is True
    assert record["externally_reachable"] is False
    assert record["peer_notify_url"] is None


def test_update_keeps_one_record(client):
    client.post("/participants", json=FO)
    client.post("/participants", json={**FO, "adapter_url": "http://new"})
    records = client.get("/participants").json()
    assert len(records) == 1
    assert records[0]["adapter_url"] == "http://new"


@pytest.mark.parametrize("spelling", ["machine_builder", "ds:machine_builder", IRI + "machine_builder"])
def test_three_spellings_store_one_iri(client, spelling):
    client.post("/participants", json={**MB, "participant_type": spelling})
    assert client.get("/participants/urn:test:mb").json()["participant_type"] == IRI + "machine_builder"


def test_unknown_role_is_refused_and_not_stored(client):
    response = client.post("/participants", json={**MB, "participant_type": "plumber"})
    assert response.status_code == 422
    assert client.get("/participants").json() == []


@pytest.mark.parametrize("spelling", ["factory_owner", "ds:factory_owner", IRI + "factory_owner"])
def test_list_by_type(client, spelling):
    client.post("/participants", json=FO)
    client.post("/participants", json=MB)
    found = client.get("/participants", params={"type": spelling}).json()
    assert [record["participant_id"] for record in found] == ["urn:test:fo"]


def test_list_by_unknown_type(client):
    assert client.get("/participants", params={"type": "plumber"}).status_code == 422


def test_unknown_participant(client):
    assert client.get("/participants/urn:none").status_code == 404
    assert client.delete("/participants/urn:none").status_code == 404
    assert client.get("/participants/compatible/urn:none").status_code == 404


def test_delete(client):
    client.post("/participants", json=FO)
    assert client.delete("/participants/urn:test:fo").status_code == 204
    assert client.get("/participants/urn:test:fo").status_code == 404


def test_compatible_excludes_self_and_same_role(client):
    client.post("/participants", json=FO)
    client.post("/participants", json={**FO, "participant_id": "urn:test:fo2"})
    client.post("/participants", json=MB)
    found = client.get("/participants/compatible/urn:test:fo").json()
    assert [record["participant_id"] for record in found] == ["urn:test:mb"]
    found = client.get("/participants/compatible/urn:test:mb").json()
    assert sorted(record["participant_id"] for record in found) == ["urn:test:fo", "urn:test:fo2"]


def test_third_role_can_be_one_directional(client, monkeypatch):
    monkeypatch.setattr(roles, "KNOWN_ROLES", {*roles.KNOWN_ROLES, "auditor"})
    monkeypatch.setattr(roles, "COMPATIBLE_ROLES", {*roles.COMPATIBLE_ROLES, ("factory_owner", "auditor")})
    client.post("/participants", json=FO)
    client.post("/participants", json={"participant_id": "urn:test:a", "participant_type": "auditor"})
    found = client.get("/participants/compatible/urn:test:fo").json()
    assert [record["participant_id"] for record in found] == ["urn:test:a"]
    assert client.get("/participants/compatible/urn:test:a").json() == []


def test_health_needs_no_database_and_routes_say_unavailable():
    app.state.store = None
    client = TestClient(app)
    assert client.get("/health").status_code == 200
    assert client.get("/participants").status_code == 503
    assert client.post("/participants", json=FO).status_code == 503


def test_keeps_trying_until_the_database_answers():
    attempts = []
    store = MemoryStore()

    async def connect():
        attempts.append(1)
        if len(attempts) < 3:
            raise OSError("connection refused")
        return store

    class Holder:
        state = type("State", (), {})()

    asyncio.run(connect_with_retry(Holder, connect, retry_seconds=0))
    assert len(attempts) == 3
    assert Holder.state.store is store
