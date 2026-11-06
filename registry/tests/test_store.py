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

"""Persistence tests. They need a PostgreSQL server, named by TEST_POSTGRES_HOST."""

import asyncio
import os
import uuid

import asyncpg
import pytest

from app.config import Settings
from app.store import PostgresStore

HOST = os.environ.get("TEST_POSTGRES_HOST")
pytestmark = pytest.mark.skipif(not HOST, reason="TEST_POSTGRES_HOST is not set")


def settings_for(database: str) -> Settings:
    return Settings(
        postgres_host=HOST,
        postgres_port=int(os.environ.get("TEST_POSTGRES_PORT", "5432")),
        postgres_user=os.environ.get("TEST_POSTGRES_USER", "postgres"),
        postgres_password=os.environ.get("TEST_POSTGRES_PASSWORD", "postgres"),
        registry_db=database,
    )


async def _drop(settings: Settings) -> None:
    connection = await asyncpg.connect(
        host=settings.postgres_host,
        port=settings.postgres_port,
        user=settings.postgres_user,
        password=settings.postgres_password,
        database="postgres",
    )
    await connection.execute(f'DROP DATABASE IF EXISTS "{settings.registry_db}"')
    await connection.close()


def test_creates_database_and_records_survive_restart():
    settings = settings_for(f"registry_test_{uuid.uuid4().hex[:8]}")
    record = {"participant_id": "urn:test:mb", "participant_type": "x", "hosted": True}

    async def scenario():
        first = await PostgresStore.connect(settings)
        await first.save(record)
        await first.save({**record, "hosted": False})
        await first.close()

        second = await PostgresStore.connect(settings)
        assert await second.get("urn:test:mb") == {**record, "hosted": False}
        assert await second.all() == [{**record, "hosted": False}]
        assert await second.delete("urn:test:mb") is True
        assert await second.delete("urn:test:mb") is False
        assert await second.get("urn:test:mb") is None
        await second.close()
        await _drop(settings)

    asyncio.run(scenario())
