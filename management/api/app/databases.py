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

"""Creates and drops participants' databases. Their names come from a hexadecimal slug."""

import asyncpg
from fastapi import HTTPException

from app.config import Settings

UNAVAILABLE = (asyncpg.PostgresError, asyncpg.InterfaceError, OSError)


class Databases:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings

    async def _connect(self) -> asyncpg.Connection:
        return await asyncpg.connect(
            host=self.settings.postgres_host,
            port=self.settings.postgres_port,
            user=self.settings.postgres_user,
            password=self.settings.postgres_password,
            database="postgres",
            timeout=10,
        )

    async def create(self, name: str) -> bool:
        """Return whether this call made the database."""
        try:
            connection = await self._connect()
            try:
                if await connection.fetchval("SELECT 1 FROM pg_database WHERE datname = $1", name):
                    return False
                await connection.execute(f'CREATE DATABASE "{name}"')
                return True
            except (asyncpg.DuplicateDatabaseError, asyncpg.UniqueViolationError):
                return False
            finally:
                await connection.close()
        except UNAVAILABLE as error:
            raise HTTPException(status_code=503, detail="PostgreSQL refused or did not answer") from error

    async def drop(self, name: str) -> bool:
        """Return whether there was such a database."""
        try:
            connection = await self._connect()
            try:
                existed = await connection.fetchval("SELECT 1 FROM pg_database WHERE datname = $1", name)
                await connection.execute(f'DROP DATABASE IF EXISTS "{name}" WITH (FORCE)')
                return bool(existed)
            finally:
                await connection.close()
        except UNAVAILABLE as error:
            raise HTTPException(status_code=503, detail="PostgreSQL refused or did not answer") from error

    async def healthy(self) -> None:
        connection = await self._connect()
        try:
            await connection.fetchval("SELECT 1")
        finally:
            await connection.close()
