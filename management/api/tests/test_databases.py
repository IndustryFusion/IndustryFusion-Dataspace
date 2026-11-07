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

"""Needs a real PostgreSQL: set TEST_POSTGRES_HOST, and _PORT, _USER and _PASSWORD if needed."""

import asyncio
import os
from uuid import uuid4

import pytest
from fastapi import HTTPException

from app.config import Settings
from app.databases import Databases

HOST = os.environ.get("TEST_POSTGRES_HOST")
pytestmark = pytest.mark.skipif(not HOST, reason="TEST_POSTGRES_HOST is not set")


def databases() -> Databases:
    return Databases(
        Settings(
            postgres_host=HOST,
            postgres_port=int(os.environ.get("TEST_POSTGRES_PORT", "5432")),
            postgres_user=os.environ.get("TEST_POSTGRES_USER", "postgres"),
            postgres_password=os.environ.get("TEST_POSTGRES_PASSWORD", "postgres"),
        )
    )


def test_create_says_who_made_it_and_drop_says_if_it_was_there():
    name = f"mgmt_{uuid4().hex[:8]}"
    store = databases()

    async def run():
        assert await store.create(name, "postgres") is True
        assert await store.create(name, "postgres") is False
        assert await store.drop(name) is True
        assert await store.drop(name) is False

    asyncio.run(run())


def test_concurrent_creates_have_one_winner():
    name = f"mgmt_{uuid4().hex[:8]}"
    store = databases()

    async def run():
        results = await asyncio.gather(*(store.create(name, "postgres") for _ in range(5)))
        await store.drop(name)
        return results

    assert sorted(asyncio.run(run())) == [False] * 4 + [True]


def test_drop_ends_open_connections():
    import asyncpg

    name = f"mgmt_{uuid4().hex[:8]}"
    store = databases()

    async def run():
        await store.create(name, "postgres")
        settings = store.settings
        open_connection = await asyncpg.connect(
            host=settings.postgres_host,
            port=settings.postgres_port,
            user=settings.postgres_user,
            password=settings.postgres_password,
            database=name,
        )
        assert await store.drop(name) is True
        with pytest.raises((asyncpg.PostgresError, asyncpg.InterfaceError, OSError)):
            await open_connection.fetchval("SELECT 1")

    asyncio.run(run())


def test_an_unreachable_server_gives_503():
    store = Databases(Settings(postgres_host="127.0.0.1", postgres_port=1, postgres_user="x", postgres_password="y"))
    with pytest.raises(HTTPException) as caught:
        asyncio.run(store.create("mgmt_x", "postgres"))
    assert caught.value.status_code == 503


def test_one_participants_user_cannot_connect_to_anothers_database():
    import asyncpg

    tag = uuid4().hex[:8]
    store = databases()
    host = {"host": HOST, "port": int(os.environ.get("TEST_POSTGRES_PORT", "5432"))}

    async def attempt(user: str, password: str, database: str) -> bool:
        try:
            connection = await asyncpg.connect(user=user, password=password, database=database, timeout=5, **host)
        except asyncpg.PostgresError:
            return False
        await connection.close()
        return True

    async def run():
        one, two = f"participant_{tag}a", f"participant_{tag}b"
        assert await store.ensure_user(one, "aaaa") is True
        assert await store.ensure_user(one, "aaaa") is False
        assert await store.ensure_user(two, "bbbb") is True
        await store.create(f"db_{tag}a", one)
        await store.create(f"db_{tag}b", two)
        try:
            assert await attempt(one, "aaaa", f"db_{tag}a") is True
            assert await attempt(two, "bbbb", f"db_{tag}b") is True
            assert await attempt(one, "aaaa", f"db_{tag}b") is False
            assert await attempt(two, "bbbb", f"db_{tag}a") is False
            assert await attempt(one, "wrong", f"db_{tag}a") is False
        finally:
            await store.drop(f"db_{tag}a")
            await store.drop(f"db_{tag}b")
            assert await store.drop_user(one) is True
            assert await store.drop_user(two) is True
            assert await store.drop_user(two) is False

    asyncio.run(run())
