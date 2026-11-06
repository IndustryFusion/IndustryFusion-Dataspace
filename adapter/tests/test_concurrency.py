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

"""Concurrent requests on a real PostgreSQL, named by TEST_POSTGRES_HOST. SQLite can't show these races."""

import asyncio
import os
import uuid

import asyncpg
import httpx
import pytest
from conftest import ME, PEER, FakeConnector, World, auth
from sqlalchemy import func, select

from app.auth import OwnToken, TokenVerifier
from app.config import Settings
from app.db import Conversation, Database, InboxMessage, OutboxMessage
from app.delivery import Services
from app.main import create_app
from app.registry import Registry
from app.storage import MemoryStorage

HOST = os.environ.get("TEST_POSTGRES_HOST")
PORT = int(os.environ.get("TEST_POSTGRES_PORT", "5432"))
USER = os.environ.get("TEST_POSTGRES_USER", "postgres")
PASSWORD = os.environ.get("TEST_POSTGRES_PASSWORD", "postgres")
pytestmark = pytest.mark.skipif(not HOST, reason="TEST_POSTGRES_HOST is not set")


async def admin_execute(statement: str) -> None:
    connection = await asyncpg.connect(host=HOST, port=PORT, user=USER, password=PASSWORD, database="postgres")
    await connection.execute(statement)
    await connection.close()


def with_adapter(scenario) -> None:
    """Run a scenario against a real adapter app, on a database of its own."""

    async def main() -> None:
        database = f"adapter_test_{uuid.uuid4().hex[:8]}"
        await admin_execute(f'CREATE DATABASE "{database}"')
        settings = Settings(
            participant_id=ME,
            adapter_url="http://me.test",
            edc_dsp_url="http://me-connector.test/dsp",
            keycloak_url="http://keycloak.test",
            keycloak_realm="dataspace",
            keycloak_client_secret="unused",
            registry_url="http://registry.test",
            transfer_budget_seconds=5,
        )
        http = httpx.AsyncClient(transport=httpx.MockTransport(World().handle))
        services = Services(
            settings=settings,
            db=Database(f"postgresql+asyncpg://{USER}:{PASSWORD}@{HOST}:{PORT}/{database}"),
            storage=MemoryStorage(),
            verifier=TokenVerifier(settings, http),
            own_token=OwnToken(settings, http),
            connector=FakeConnector(),
            registry=Registry(settings.registry_url, http),
            http=http,
        )
        await services.db.ensure_schema()
        application = create_app(services)
        application.state.services = services
        transport = httpx.ASGITransport(app=application)
        async with httpx.AsyncClient(transport=transport, base_url="http://adapter.test", timeout=30) as client:
            try:
                await scenario(client, services)
            finally:
                await services.settle()
                await services.db.close()
                await admin_execute(f'DROP DATABASE "{database}" WITH (FORCE)')

    asyncio.run(main())


def notification(message_id: str, conversation_id: str) -> dict:
    return {
        "message_id": message_id,
        "conversation_id": conversation_id,
        "sender_participant": PEER,
        "receiver_participant": ME,
        "asset_id": message_id,
        "provider_dsp_url": "http://peer-connector.test/dsp",
    }


async def count(services: Services, model) -> int:
    async with services.db.session() as session:
        return await session.scalar(select(func.count()).select_from(model))


def test_concurrent_messages_on_new_conversations_are_all_kept():
    async def scenario(client: httpx.AsyncClient, services: Services) -> None:
        bodies = [notification(f"{group}-{item}", f"conversation-{group}") for group in range(10) for item in range(5)]
        answers = await asyncio.gather(
            *[client.post("/internal/transfer-request", json=body, headers=auth(PEER)) for body in bodies]
        )
        assert [answer.status_code for answer in answers] == [202] * 50
        assert {answer.json()["status"] for answer in answers} == {"transferring"}
        await services.settle()
        assert await count(services, InboxMessage) == 50
        assert await count(services, Conversation) == 10

    with_adapter(scenario)


def test_concurrent_copies_of_one_message_keep_one_entry():
    async def scenario(client: httpx.AsyncClient, services: Services) -> None:
        pushes = []

        async def record(destination: str) -> None:
            pushes.append(destination)

        services.connector.on_push = record
        body = notification("same", "conversation")
        answers = await asyncio.gather(
            *[client.post("/internal/transfer-request", json=body, headers=auth(PEER)) for _ in range(8)]
        )
        assert [answer.status_code for answer in answers] == [202] * 8
        states = sorted(answer.json()["status"] for answer in answers)
        assert states == ["duplicate"] * 7 + ["transferring"]
        await services.settle()
        assert await count(services, InboxMessage) == 1
        assert len(pushes) == 1

    with_adapter(scenario)


def test_concurrent_sends_on_a_new_conversation_all_succeed():
    async def scenario(client: httpx.AsyncClient, services: Services) -> None:
        # Hold every send at the upload, so that they all reach the database together.
        together = asyncio.Barrier(30)
        real_put = services.storage.put

        async def put(key: str, content: bytes) -> str:
            ref = await real_put(key, content)
            await together.wait()
            return ref

        services.storage.put = put
        body = {"receiver_participant": PEER, "conversation_id": "new-conversation", "payload": {"a": 1}}
        answers = await asyncio.gather(
            *[client.post("/outbox/messages", json=body, headers=auth()) for _ in range(30)]
        )
        assert [answer.status_code for answer in answers] == [202] * 30
        await services.settle()
        assert await count(services, OutboxMessage) == 30
        assert await count(services, Conversation) == 1
        assert len(services.storage.objects) == 30

    with_adapter(scenario)
