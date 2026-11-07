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
import threading
import time

import pytest
from botocore.exceptions import ClientError, EndpointConnectionError
from fastapi import HTTPException

from app.config import Settings
from app.storage import StorageIdentities


class FakeIam:
    """As much of the storage's IAM API as this uses. Calls take a moment, as a change is read and written back."""

    def __init__(self) -> None:
        self.users: dict[str, dict] = {"someone-else": {"keys": {"o": "o"}, "policy": None}}
        self.running = 0
        self.overlapped = False
        self.guard = threading.Lock()

    def _step(self):
        with self.guard:
            self.running += 1
            self.overlapped = self.overlapped or self.running > 1
        time.sleep(0.001)
        with self.guard:
            self.running -= 1

    def list_access_keys(self, UserName):  # noqa: N803
        self._step()
        if UserName not in self.users:
            raise ClientError({"Error": {"Code": "NoSuchEntity"}}, "ListAccessKeys")
        return {"AccessKeyMetadata": [{"AccessKeyId": key} for key in self.users[UserName]["keys"]]}

    def create_user(self, UserName):  # noqa: N803
        self._step()
        self.users[UserName] = {"keys": {}, "policy": None}

    def create_access_key(self, UserName):  # noqa: N803
        self._step()
        access, secret = f"k{len(self.users[UserName]['keys'])}{UserName}", f"s{UserName}"
        self.users[UserName]["keys"][access] = secret
        return {"AccessKey": {"AccessKeyId": access, "SecretAccessKey": secret}}

    def put_user_policy(self, UserName, PolicyName, PolicyDocument):  # noqa: N803
        self._step()
        self.users[UserName]["policy"] = json.loads(PolicyDocument)

    def delete_user(self, UserName):  # noqa: N803
        self._step()
        del self.users[UserName]


@pytest.fixture
def iam():
    return FakeIam()


@pytest.fixture
def store(iam, monkeypatch):
    identities = StorageIdentities(Settings(s3_iam_url="http://iam.test", s3_access_key="a", s3_secret_key="b"))
    monkeypatch.setattr(identities, "_client", lambda: iam)
    return identities


def test_an_identity_only_has_its_own_bucket(store, iam):
    access, secret, made = asyncio.run(store.ensure("p1", "bucket-1", None))
    assert made is True
    assert iam.users["p1"]["keys"] == {access: secret}
    statement = iam.users["p1"]["policy"]["Statement"][0]
    assert statement["Resource"] == ["arn:aws:s3:::bucket-1", "arn:aws:s3:::bucket-1/*"]


def test_keys_it_holds_are_kept(store, iam):
    access, secret, _ = asyncio.run(store.ensure("p1", "b", None))
    assert asyncio.run(store.ensure("p1", "b", (access, secret))) == (access, secret, False)
    assert len(iam.users["p1"]["keys"]) == 1


def test_keys_it_lost_are_replaced_without_making_it_new(store, iam):
    access, _, _ = asyncio.run(store.ensure("p1", "b", None))
    again, _, made = asyncio.run(store.ensure("p1", "b", None))
    assert made is False and again != access


def test_keys_it_holds_of_an_identity_that_has_gone_are_replaced(store, iam):
    access, _, made = asyncio.run(store.ensure("p1", "b", ("gone", "gone")))
    assert made is True and access != "gone"


def test_removing_leaves_others(store, iam):
    asyncio.run(store.ensure("p1", "b", None))
    assert asyncio.run(store.remove("p1")) is True
    assert asyncio.run(store.remove("p1")) is False
    assert set(iam.users) == {"someone-else"}


def test_several_at_once_run_one_at_a_time(store, iam):
    async def run():
        await asyncio.gather(*(store.ensure(f"p{n}", f"b{n}", None) for n in range(10)))

    asyncio.run(run())
    assert {f"p{n}" for n in range(10)} <= set(iam.users)
    assert iam.overlapped is False


def test_a_storage_that_refuses_gives_502(store, monkeypatch):
    def refuse():
        raise EndpointConnectionError(endpoint_url="http://iam.test")

    monkeypatch.setattr(store, "_client", refuse)
    with pytest.raises(HTTPException) as refused:
        asyncio.run(store.ensure("p1", "b", None))
    assert refused.value.status_code == 502


def test_off_without_an_address():
    assert StorageIdentities(Settings()).enabled is False
