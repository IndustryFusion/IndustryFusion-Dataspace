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
import json

import httpx
import pytest
from fastapi import HTTPException

from app.config import Settings
from app.storage import StorageIdentities

FILE = "http://filer.test/etc/iam/identity.json"
ADMIN = "the-admin-key"


class Filer:
    def __init__(self, content: dict | None = None) -> None:
        self.content = None if content is None else json.dumps(content).encode()
        self.status = None

    def handle(self, request: httpx.Request) -> httpx.Response:
        assert str(request.url) == FILE
        if self.status:
            return httpx.Response(self.status)
        if request.method == "PUT":
            self.content = request.content
            return httpx.Response(201)
        return httpx.Response(200, content=self.content) if self.content is not None else httpx.Response(404)

    @property
    def names(self) -> list[str]:
        return [entry["name"] for entry in json.loads(self.content)["identities"]]


def identities(filer: Filer) -> StorageIdentities:
    settings = Settings(s3_filer_url="http://filer.test", s3_access_key=ADMIN, s3_secret_key="admin-secret")
    return StorageIdentities(settings, httpx.AsyncClient(transport=httpx.MockTransport(filer.handle)))


def test_an_identity_only_has_its_own_bucket():
    filer = Filer()
    asyncio.run(identities(filer).put("p1", "k1", "s1", "bucket-1"))
    entry = next(e for e in json.loads(filer.content)["identities"] if e["name"] == "p1")
    assert entry["credentials"] == [{"accessKey": "k1", "secretKey": "s1"}]
    assert all(action.endswith(":bucket-1") for action in entry["actions"])
    assert {action.split(":")[0] for action in entry["actions"]} == {"Read", "Write", "List", "Tagging"}


def test_the_administrator_is_never_locked_out():
    filer = Filer()
    asyncio.run(identities(filer).put("p1", "k1", "s1", "b"))
    admin = next(e for e in json.loads(filer.content)["identities"] if e["credentials"][0]["accessKey"] == ADMIN)
    assert "Admin" in admin["actions"]
    asyncio.run(identities(filer).remove("p1"))
    assert [e["credentials"][0]["accessKey"] for e in json.loads(filer.content)["identities"]] == [ADMIN]


def test_other_entries_stay():
    other = {"name": "someone-else", "credentials": [{"accessKey": "o", "secretKey": "o"}], "actions": ["Read"]}
    filer = Filer({"identities": [other]})
    store = identities(filer)
    assert asyncio.run(store.put("p1", "k1", "s1", "b")) is False
    assert asyncio.run(store.put("p1", "k2", "s2", "b")) is True
    assert sorted(filer.names) == ["dataspace-management", "p1", "someone-else"]
    assert asyncio.run(store.remove("p1")) is True
    assert asyncio.run(store.remove("p1")) is False
    assert "someone-else" in filer.names and "p1" not in filer.names


def test_several_at_once_all_keep_theirs():
    filer = Filer()
    store = identities(filer)

    async def run():
        await asyncio.gather(*(store.put(f"p{n}", f"k{n}", "s", "b") for n in range(20)))

    asyncio.run(run())
    assert {f"p{n}" for n in range(20)} <= set(filer.names)


def test_an_unreadable_list_is_not_overwritten():
    filer = Filer()
    filer.content = b"not json"
    with pytest.raises(HTTPException) as refused:
        asyncio.run(identities(filer).put("p1", "k1", "s1", "b"))
    assert refused.value.status_code == 502
    assert filer.content == b"not json"


def test_a_filer_that_refuses_gives_502():
    filer = Filer()
    filer.status = 500
    with pytest.raises(HTTPException) as refused:
        asyncio.run(identities(filer).put("p1", "k1", "s1", "b"))
    assert refused.value.status_code == 502


def test_off_without_an_address():
    assert StorageIdentities(Settings(), httpx.AsyncClient()).enabled is False
