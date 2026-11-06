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

"""Where participant records are kept."""

import json
import ssl
from typing import Protocol

import asyncpg

from app.config import Settings


class Store(Protocol):
    async def save(self, record: dict) -> None: ...

    async def get(self, participant_id: str) -> dict | None: ...

    async def all(self) -> list[dict]: ...

    async def delete(self, participant_id: str) -> bool: ...


class MemoryStore:
    """Used by tests of the API, which don't need a database."""

    def __init__(self) -> None:
        self.records: dict[str, dict] = {}

    async def save(self, record: dict) -> None:
        self.records[record["participant_id"]] = record

    async def get(self, participant_id: str) -> dict | None:
        return self.records.get(participant_id)

    async def all(self) -> list[dict]:
        return list(self.records.values())

    async def delete(self, participant_id: str) -> bool:
        return self.records.pop(participant_id, None) is not None


def _connection_args(settings: Settings, database: str) -> dict:
    args = {
        "host": settings.postgres_host,
        "port": settings.postgres_port,
        "user": settings.postgres_user,
        "password": settings.postgres_password,
        "database": database,
    }
    if settings.postgres_sslmode in {"require", "verify-ca", "verify-full"}:
        context = ssl.create_default_context()
        if settings.postgres_sslmode != "verify-full":
            context.check_hostname = False
        if settings.postgres_sslmode == "require":
            context.verify_mode = ssl.CERT_NONE
        args["ssl"] = context
    return args


class PostgresStore:
    def __init__(self, pool: asyncpg.Pool) -> None:
        self.pool = pool

    @classmethod
    async def connect(cls, settings: Settings) -> "PostgresStore":
        await _ensure_database(settings)
        args = _connection_args(settings, settings.registry_db)
        pool = await asyncpg.create_pool(**args, min_size=1, max_size=5)
        async with pool.acquire() as connection:
            await connection.execute(
                "CREATE TABLE IF NOT EXISTS participants "
                "(participant_id TEXT PRIMARY KEY, data JSONB NOT NULL)"
            )
        return cls(pool)

    async def close(self) -> None:
        await self.pool.close()

    async def save(self, record: dict) -> None:
        await self.pool.execute(
            "INSERT INTO participants (participant_id, data) VALUES ($1, $2::jsonb) "
            "ON CONFLICT (participant_id) DO UPDATE SET data = EXCLUDED.data",
            record["participant_id"],
            json.dumps(record),
        )

    async def get(self, participant_id: str) -> dict | None:
        row = await self.pool.fetchrow(
            "SELECT data FROM participants WHERE participant_id = $1", participant_id
        )
        return json.loads(row["data"]) if row else None

    async def all(self) -> list[dict]:
        rows = await self.pool.fetch("SELECT data FROM participants ORDER BY participant_id")
        return [json.loads(row["data"]) for row in rows]

    async def delete(self, participant_id: str) -> bool:
        result = await self.pool.execute("DELETE FROM participants WHERE participant_id = $1", participant_id)
        return result.endswith(" 1")


async def _ensure_database(settings: Settings) -> None:
    connection = await asyncpg.connect(**_connection_args(settings, "postgres"))
    try:
        exists = await connection.fetchval(
            "SELECT 1 FROM pg_database WHERE datname = $1", settings.registry_db
        )
        if not exists:
            quoted = settings.registry_db.replace('"', '""')
            try:
                await connection.execute(f'CREATE DATABASE "{quoted}"')
            except asyncpg.DuplicateDatabaseError:
                pass
    finally:
        await connection.close()
