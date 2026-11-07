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
import dataclasses
import re
import time

import httpx
import pytest
from conftest import World

from app.config import Settings
from app.ifric import CompanyDirectory
from app.main import app

KNOWN = "urn:ifric:acme"
FULL = {
    "company_ifric_id": KNOWN,
    "company_name": "Acme Machines",
    "company_category": "machine_builder",
    "company_city": "Bengaluru",
    "company_country": "India",
    "company_address": "not shown",
    "company_verified": True,
}
DETAILS = {
    "company_name": "Acme Machines",
    "company_category": "machine_builder",
    "city": "Bengaluru",
    "country": "India",
}


class Clock:
    def __init__(self) -> None:
        self.now = 1000.0

    def __call__(self) -> float:
        return self.now


@pytest.fixture
def clock():
    return Clock()


@pytest.fixture
def world(clock):
    instance = World(
        ifric_backend_url="http://ifric.test",
        ifric_reader_client_id="dataspace-ifric-reader",
        ifric_reader_client_secret="right",
        ifric_lookup_cache_seconds=300,
    )
    instance.services.companies = CompanyDirectory(instance.settings, instance.http, clock)
    instance.ifric.companies = [FULL]
    instance.register(KNOWN, "machine_builder")
    instance.register("urn:other:owner", "factory_owner")
    yield instance
    app.state.services = None


def read(world, participant=KNOWN):
    return world.client.get(f"/api/participants/{participant}", headers=world.admin).json()


def plain(record: dict) -> dict:
    return {key: value for key, value in record.items() if key not in DETAILS}


def test_each_read_has_the_details(world):
    assert {key: read(world)[key] for key in DETAILS} == DETAILS
    listed = {entry["participant_id"]: entry for entry in world.client.get("/api/participants").json()}
    assert {key: listed[KNOWN][key] for key in DETAILS} == DETAILS
    compatible = world.client.get("/api/participants/compatible/urn:other:owner").json()
    assert {key: compatible[0][key] for key in DETAILS} == DETAILS


def test_the_rest_of_the_record_is_unchanged(world):
    record = read(world)
    assert plain(record) == world.registry.records[KNOWN]
    assert "company_address" not in record and "company_ifric_id" not in record


def test_the_token_comes_from_the_reader_client(world):
    read(world)
    assert world.ifric.authorizations[0].startswith("Bearer ")
    assert world.keycloak.seen_tokens, "Admin calls were made for the registration"


def test_a_participant_ifric_does_not_know_has_no_details(world):
    assert not set(DETAILS) & set(read(world, "urn:other:owner"))


def test_details_that_are_missing_are_left_out(world):
    world.ifric.companies = [{"company_ifric_id": KNOWN, "company_name": "Acme", "company_city": None}]
    record = read(world)
    assert record["company_name"] == "Acme"
    assert not {"company_category", "city", "country"} & set(record)


def test_a_write_carries_no_details(world):
    read(world)
    answer = world.register(KNOWN, "machine_builder", externally_reachable=True)
    assert answer.status_code == 200
    assert not set(DETAILS) & set(answer.json())
    assert not set(DETAILS) & set(world.registry.records[KNOWN])


@pytest.mark.parametrize("missing", ["ifric_backend_url", "ifric_reader_client_id", "ifric_reader_client_secret"])
def test_not_configured(world, clock, missing):
    settings = dataclasses.replace(world.settings, **{missing: ""})
    world.services.companies = CompanyDirectory(settings, world.http, clock)
    world.keycloak.fail = None
    calls_before = world.ifric.calls
    assert plain(read(world)) == read(world)
    assert world.ifric.calls == calls_before


def test_nothing_configured_is_the_default():
    world = World()
    world.register(KNOWN, "machine_builder")
    assert not set(DETAILS) & set(world.client.get(f"/api/participants/{KNOWN}").json())
    assert world.ifric.calls == 0
    app.state.services = None


def test_unreachable(world):
    world.ifric.up = False
    answer = world.client.get("/api/participants")
    assert answer.status_code == 200
    assert all(not set(DETAILS) & set(entry) for entry in answer.json())


@pytest.mark.parametrize("status", [401, 403, 500, 503])
def test_an_error_from_ifric(world, status):
    world.ifric.status = status
    world.ifric.companies = {"message": "no"}
    answer = world.client.get(f"/api/participants/{KNOWN}")
    assert answer.status_code == 200
    assert not set(DETAILS) & set(answer.json())


def test_the_readers_token_is_refused(world, clock, caplog):
    settings = dataclasses.replace(world.settings, ifric_reader_client_secret="wrong-secret-value")
    world.services.companies = CompanyDirectory(settings, world.http, clock)
    answer = world.client.get(f"/api/participants/{KNOWN}")
    assert answer.status_code == 200
    assert not set(DETAILS) & set(answer.json())
    assert world.ifric.calls == 0
    assert "wrong-secret-value" not in caplog.text and "wrong-secret-value" not in answer.text


def test_keycloak_down(world):
    world.keycloak.up = False
    assert world.client.get(f"/api/participants/{KNOWN}").status_code == 200


@pytest.mark.parametrize(
    "companies",
    [{"not": "a list"}, ["a", 1, None], [{"company_name": "No id"}], [{"company_ifric_id": 5}], None],
    ids=["object", "strings", "no-id", "number-id", "empty-body"],
)
def test_an_answer_that_is_not_companies(world, companies):
    world.ifric.companies = companies
    answer = world.client.get(f"/api/participants/{KNOWN}")
    assert answer.status_code == 200
    assert not set(DETAILS) & set(answer.json())


def test_usable_entries_of_a_mixed_answer_are_kept(world):
    world.ifric.companies = ["junk", {"company_name": "No id"}, FULL]
    assert read(world)["company_name"] == "Acme Machines"


def test_the_cache_holds_within_its_time_and_expires_after(world, clock):
    read(world)
    assert world.ifric.calls == 1
    world.ifric.companies = [{**FULL, "company_name": "Renamed"}]
    clock.now += 299
    assert read(world)["company_name"] == "Acme Machines"
    assert world.ifric.calls == 1
    clock.now += 2
    assert read(world)["company_name"] == "Renamed"
    assert world.ifric.calls == 2


def test_the_cache_time_is_configurable(world, clock):
    settings = dataclasses.replace(world.settings, ifric_lookup_cache_seconds=10)
    world.services.companies = CompanyDirectory(settings, world.http, clock)
    read(world)
    clock.now += 11
    read(world)
    assert world.ifric.calls == 2


def test_the_default_cache_time_is_300(monkeypatch):
    from app.config import Settings

    monkeypatch.delenv("IFRIC_LOOKUP_CACHE_SECONDS", raising=False)
    assert Settings().ifric_lookup_cache_seconds == 300
    monkeypatch.setenv("IFRIC_LOOKUP_CACHE_SECONDS", "42")
    assert Settings().ifric_lookup_cache_seconds == 42


def test_concurrent_reads_make_one_call(world):
    async def many():
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://m") as client:
            return await asyncio.gather(*(client.get(f"/api/participants/{KNOWN}") for _ in range(20)))

    answers = asyncio.run(many())
    assert all(answer.json()["company_name"] == "Acme Machines" for answer in answers)
    assert world.ifric.calls == 1


def test_a_failure_isnt_tried_again_at_once_and_a_later_read_recovers(world, clock):
    world.ifric.up = False
    read(world)
    read(world)
    assert world.ifric.calls == 1
    world.ifric.up = True
    clock.now += 29
    assert "company_name" not in read(world)
    assert world.ifric.calls == 1
    clock.now += 2
    assert read(world)["company_name"] == "Acme Machines"
    assert world.ifric.calls == 2


def test_a_failure_after_a_success_leaves_the_details_out(world, clock):
    read(world)
    world.ifric.up = False
    clock.now += 301
    assert "company_name" not in read(world)


def test_the_token_never_appears_in_a_read(world):
    read(world)
    text = world.client.get(f"/api/participants/{KNOWN}").text
    assert not re.search(r"eyJ[A-Za-z0-9_-]+\.", text)


def test_a_company_field_that_is_not_text_is_left_out(world):
    world.ifric.companies = [{"company_ifric_id": KNOWN, "company_name": {"html": "<b>"}, "company_city": ["a"]}]
    record = read(world)
    assert "company_name" not in record and "city" not in record


def test_a_bad_address_leaves_details_out(world, clock):
    settings = dataclasses.replace(world.settings, ifric_backend_url="http://ifric:notaport")
    world.services.companies = CompanyDirectory(settings, world.http, clock)
    answer = world.client.get("/api/participants")
    assert answer.status_code == 200
    assert not set(DETAILS) & set(answer.json()[0])


class Dripping:
    """Answers a piece at a time, each within any timeout per call, and never finishes."""

    def __init__(self) -> None:
        self.fetches = 0
        self.started = asyncio.Event()

    async def get(self, url, **_):
        self.fetches += 1
        await asyncio.sleep(3600)

    async def post(self, url, **_):
        return httpx.Response(200, json={"access_token": "t"}, request=httpx.Request("POST", url))


def test_a_dripping_registry_holds_up_no_read_for_long(monkeypatch, clock):
    from app import ifric

    monkeypatch.setattr(ifric, "READ_WAIT_SECONDS", 0.05)
    monkeypatch.setattr(ifric, "FETCH_SECONDS", 0.2)
    settings = Settings(
        ifric_backend_url="http://ifric.test", ifric_reader_client_id="r", ifric_reader_client_secret="s"
    )
    dripping = Dripping()
    directory = CompanyDirectory(settings, dripping, clock)

    async def scenario():
        began = time.monotonic()
        first = await directory.add_details([{"participant_id": KNOWN}])
        second = await directory.add_details([{"participant_id": KNOWN}])
        took = time.monotonic() - began
        await directory.fetching
        return first, second, took

    first, second, took = asyncio.run(scenario())
    assert first == second == [{"participant_id": KNOWN}]
    assert took < 0.15
    assert dripping.fetches == 1, "Reads during a fetch share it"
    assert directory.good_until == clock() + ifric.SECONDS_AFTER_A_FAILURE, "It was given up, and counts as failed"


def test_a_read_gets_what_a_quick_fetch_found(world):
    assert read(world)["company_name"] == FULL["company_name"]

