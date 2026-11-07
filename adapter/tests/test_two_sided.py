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
"""Two real adapters, each on its own PostgreSQL database, notifying each other. Only the connectors are faked."""

import asyncio
import json
import os
import random
import uuid
from urllib.parse import parse_qs, urlparse

import asyncpg
import httpx
import jwt
import pytest
from conftest import KEY, auth, token
from fastapi import FastAPI
from sqlalchemy import func, select

from app.auth import OwnToken, TokenVerifier
from app.config import Settings
from app.db import Database, InboxMessage, OutboxMessage
from app.delivery import Services
from app.main import create_app
from app.registry import Registry
from app.storage import MemoryStorage

HOST = os.environ.get("TEST_POSTGRES_HOST")
PORT = int(os.environ.get("TEST_POSTGRES_PORT", "5432"))
USER = os.environ.get("TEST_POSTGRES_USER", "postgres")
PASSWORD = os.environ.get("TEST_POSTGRES_PASSWORD", "postgres")
pytestmark = pytest.mark.skipif(not HOST, reason="TEST_POSTGRES_HOST is not set")

FO, MB = "urn:test:fo", "urn:test:mb"
OTHER_FO = "urn:test:other-fo"
INTERNAL_KEY = "test-internal-key"
AUTHORIZATION = {"scope": "conversation", "expires_at": "2026-12-01T10:00:00+00:00", "constraints": {}}


async def admin(statement: str) -> None:
    connection = await asyncpg.connect(host=HOST, port=PORT, user=USER, password=PASSWORD, database="postgres")
    await connection.execute(statement)
    await connection.close()


class PairedConnector:
    """Does what a connector pair does: reads the provider's payload route, and pushes to this adapter."""

    def __init__(self, mesh: "Mesh") -> None:
        self.mesh = mesh

    async def offer(self, asset_id: str, source_url: str, header: tuple[str, str]) -> None:
        self.mesh.source_headers[asset_id] = dict([header])
        # A real connector takes a varying time, which is what could put notifications out of order.
        if self.mesh.varying_offers:
            await asyncio.sleep(random.random() * 0.03)

    async def find_offer(self, asset_id: str, provider_id: str, provider_dsp: str) -> str:
        return asset_id

    async def negotiate(self, offer_id, asset_id, provider_id, provider_dsp) -> str:
        return f"{provider_dsp}|{asset_id}"

    async def wait_for_agreement(self, negotiation_id: str, deadline: float) -> str:
        return negotiation_id

    async def push(self, agreement_id: str, provider_dsp: str, destination_url: str, header: tuple[str, str]) -> str:
        provider, asset = agreement_id.split("|")
        source = await self.mesh.client_at(provider).get(
            f"/internal/payload/{asset}", headers=self.mesh.source_headers[asset]
        )
        target = urlparse(destination_url)
        answer = await self.mesh.clients[target.hostname].post(
            target.path, content=source.content, headers=dict([header])
        )
        assert answer.status_code == 200, answer.text
        return "transfer"

    async def wait_for_transfer(self, transfer_id: str, deadline: float) -> None:
        return None

    async def transfer_for_asset(self, asset_id: str) -> str | None:
        return "transfer"


class Mesh:
    """What each adapter's HTTP client reaches: Keycloak, the registry and the other adapter."""

    def __init__(self) -> None:
        self.clients: dict[str, httpx.AsyncClient] = {}
        self.source_headers: dict[str, dict[str, str]] = {}
        self.held = asyncio.Event()
        self.held.set()
        self.varying_offers = False

    def client_at(self, dsp_url: str) -> httpx.AsyncClient:
        return self.clients[urlparse(dsp_url).hostname.replace("-connector", "")]

    async def handle(self, request: httpx.Request) -> httpx.Response:
        url = str(request.url)
        if url.endswith("/certs"):
            jwk = json.loads(jwt.algorithms.RSAAlgorithm.to_jwk(KEY.public_key()))
            return httpx.Response(200, json={"keys": [{**jwk, "kid": "test", "use": "sig"}]})
        if url.endswith("/token"):
            client_id = parse_qs(request.content.decode())["client_id"][0]
            return httpx.Response(200, json={"access_token": token(client_id), "expires_in": 300})
        if request.url.host == "registry.test":
            return registry_answer(request.url.path)
        await self.held.wait()
        answer = await self.clients[request.url.host].request(
            request.method, request.url.path, content=request.content, headers=request.headers
        )
        return httpx.Response(answer.status_code, content=answer.content)


def registry_answer(path: str) -> httpx.Response:
    records = {
        FO: {"participant_id": FO, "adapter_url": "http://fo.test"},
        OTHER_FO: {"participant_id": OTHER_FO, "adapter_url": "http://other-fo.test"},
        MB: {"participant_id": MB, "adapter_url": "http://mb.test"},
    }
    if path.startswith("/participants/compatible/"):
        own = path.removeprefix("/participants/compatible/")
        compatible = [FO, OTHER_FO] if own == MB else [MB] if own in records else None
        if compatible is None:
            return httpx.Response(404, json={})
        return httpx.Response(200, json=[records[name] for name in compatible])
    record = records.get(path.removeprefix("/participants/"))
    return httpx.Response(200, json=record) if record else httpx.Response(404, json={})


class Side:
    def __init__(self, participant: str, client: httpx.AsyncClient, services: Services) -> None:
        self.participant = participant
        self.client = client
        self.services = services

    @property
    def peer(self) -> str:
        return MB if self.participant == FO else FO

    async def post(self, **fields) -> httpx.Response:
        body = {"receiver_participant": self.peer, "payload": {}, **fields}
        return await self.client.post("/outbox/messages", json=body, headers=auth(self.participant))

    async def send(self, **fields) -> dict:
        response = await self.post(**fields)
        assert response.status_code == 202, response.text
        return response.json()

    async def conversation(self, conversation_id: str) -> dict:
        response = await self.client.get(f"/conversations/{conversation_id}", headers=auth(self.participant))
        assert response.status_code == 200, response.text
        return response.json()

    async def status(self, message_id: str) -> dict:
        path = f"/outbox/messages/{message_id}/status"
        return (await self.client.get(path, headers=auth(self.participant))).json()

    async def inbox_message(self, message_id: str) -> dict:
        path = f"/inbox/messages/{message_id}"
        return (await self.client.get(path, headers=auth(self.participant))).json()

    async def count(self, model) -> int:
        async with self.services.db.session() as session:
            return await session.scalar(select(func.count()).select_from(model))


async def settle(*sides: Side) -> None:
    while any(side.services.tasks for side in sides):
        for side in sides:
            await side.services.settle()


async def assert_same(one: Side, other: Side, conversation_id: str, state: str, outcome: str | None = None) -> dict:
    await settle(one, other)
    first, second = await one.conversation(conversation_id), await other.conversation(conversation_id)
    for name in ("state", "outcome", "escalated_by"):
        assert first[name] == second[name], (name, first, second)
    assert (first["state"], first["outcome"]) == (state, outcome)
    return first


def two_sided(scenario) -> None:
    async def main() -> None:
        mesh = Mesh()
        names = {"fo": FO, "mb": MB}
        sides, databases = {}, []
        for short, participant in names.items():
            database = f"adapter_two_{uuid.uuid4().hex[:8]}"
            await admin(f'CREATE DATABASE "{database}"')
            databases.append(database)
            settings = Settings(
                participant_id=participant,
                participant_type="factory_owner" if short == "fo" else "machine_builder",
                adapter_internal_key=INTERNAL_KEY,
                adapter_url=f"http://{short}.test",
                edc_dsp_url=f"http://{short}-connector.test/dsp",
                keycloak_url="http://keycloak.test",
                keycloak_realm="dataspace",
                keycloak_client_secret="unused",
                registry_url="http://registry.test",
                transfer_budget_seconds=5,
            )
            http = httpx.AsyncClient(transport=httpx.MockTransport(mesh.handle))
            services = Services(
                settings=settings,
                db=Database(f"postgresql+asyncpg://{USER}:{PASSWORD}@{HOST}:{PORT}/{database}"),
                storage=MemoryStorage(),
                verifier=TokenVerifier(settings, http),
                own_token=OwnToken(settings, http),
                connector=PairedConnector(mesh),
                registry=Registry(settings.registry_url, http),
                http=http,
            )
            await services.db.ensure_schema()
            application: FastAPI = create_app(services)
            application.state.services = services
            transport = httpx.ASGITransport(app=application)
            client = httpx.AsyncClient(transport=transport, base_url=f"http://{short}.test", timeout=30)
            mesh.clients[f"{short}.test"] = client
            sides[short] = Side(participant, client, services)
        try:
            await scenario(sides["fo"], sides["mb"], mesh)
        finally:
            mesh.held.set()
            for side in sides.values():
                await settle(side)
                await side.client.aclose()
                await side.services.http.aclose()
                await side.services.db.close()
            for database in databases:
                await admin(f'DROP DATABASE "{database}" WITH (FORCE)')

    asyncio.run(main())


def test_request_and_reply():
    async def scenario(fo: Side, mb: Side, _: Mesh) -> None:
        request = await fo.send(conversation_id="c", performative="request", payload={"q": 1})
        await settle(fo, mb)
        reply = await mb.send(conversation_id="c", in_reply_to=request["message_id"], payload={"a": 2})
        shown = await assert_same(fo, mb, "c", "OPEN")
        assert shown["outstanding_requests"] == []
        other = await mb.conversation("c")
        assert other["outstanding_requests"] == []
        assert (await fo.inbox_message(reply["message_id"]))["payload"] == {"a": 2}
        assert [item["direction"] for item in shown["messages"]] == ["sent", "received"]
        assert [item["direction"] for item in other["messages"]] == ["received", "sent"]

    two_sided(scenario)


def test_grant_can_be_read_by_the_receiver():
    async def scenario(fo: Side, mb: Side, _: Mesh) -> None:
        request = await mb.send(conversation_id="c", performative="request", capability="twin:history")
        await settle(fo, mb)
        grant = await fo.send(
            conversation_id="c",
            performative="grant",
            capability="twin:history",
            in_reply_to=request["message_id"],
            authorization=AUTHORIZATION,
        )
        await assert_same(fo, mb, "c", "OPEN")
        received = await mb.inbox_message(grant["message_id"])
        assert received["authorization"] == AUTHORIZATION
        assert (received["performative"], received["status"]) == ("grant", "received")

    two_sided(scenario)


def test_deny_and_cancel():
    async def scenario(fo: Side, mb: Side, _: Mesh) -> None:
        request = await mb.send(conversation_id="c", performative="request", capability="twin:history")
        await settle(fo, mb)
        await fo.send(
            conversation_id="c", performative="deny", capability="twin:history", in_reply_to=request["message_id"]
        )
        await assert_same(fo, mb, "c", "OPEN")
        second = await mb.send(conversation_id="c", performative="request")
        await settle(fo, mb)
        cancel = await mb.send(conversation_id="c", performative="cancel", in_reply_to=second["message_id"])
        await assert_same(fo, mb, "c", "OPEN")
        assert (await fo.inbox_message(cancel["message_id"]))["performative"] == "cancel"

    two_sided(scenario)


@pytest.mark.parametrize("outcome", ["resolved", "withdrawn", "rejected", "failed", "timed_out", "superseded"])
def test_close(outcome):
    async def scenario(fo: Side, mb: Side, _: Mesh) -> None:
        await fo.send(conversation_id="c")
        await settle(fo, mb)
        await mb.send(conversation_id="c", performative="close", outcome=outcome)
        shown = await assert_same(fo, mb, "c", f"CLOSED_{outcome.upper()}", outcome)
        assert shown["closed_at"] is not None
        assert (await fo.conversation("c"))["closed_at"] is not None

    two_sided(scenario)


def test_escalate_and_deescalate():
    async def scenario(fo: Side, mb: Side, _: Mesh) -> None:
        await fo.send(conversation_id="c")
        await settle(fo, mb)
        await mb.send(conversation_id="c", performative="escalate")
        shown = await assert_same(fo, mb, "c", "ESCALATING")
        assert shown["escalated_by"] == MB
        # Ordinary messages still pass, and the other side still can't take over.
        await fo.send(conversation_id="c", performative="inform")
        await assert_same(fo, mb, "c", "ESCALATING")
        assert (await fo.post(conversation_id="c", performative="deescalate")).status_code == 409
        await mb.send(conversation_id="c", performative="deescalate")
        shown = await assert_same(fo, mb, "c", "OPEN")
        assert shown["escalated_by"] is None

    two_sided(scenario)


def test_escalate_then_close_as_escalated_and_no_reopen():
    async def scenario(fo: Side, mb: Side, _: Mesh) -> None:
        await fo.send(conversation_id="c", performative="escalate")
        await assert_same(fo, mb, "c", "ESCALATING")
        await fo.send(conversation_id="c", performative="close", outcome="escalated")
        await assert_same(fo, mb, "c", "CLOSED_ESCALATED", "escalated")
        assert (await mb.post(conversation_id="c", performative="reopen")).status_code == 409
        await assert_same(fo, mb, "c", "CLOSED_ESCALATED", "escalated")

    two_sided(scenario)


def test_reopen():
    async def scenario(fo: Side, mb: Side, _: Mesh) -> None:
        await fo.send(conversation_id="c")
        await settle(fo, mb)
        await fo.send(conversation_id="c", performative="close", outcome="resolved")
        await assert_same(fo, mb, "c", "CLOSED_RESOLVED", "resolved")
        await mb.send(conversation_id="c", performative="reopen")
        shown = await assert_same(fo, mb, "c", "OPEN")
        assert shown["closed_at"] is None
        await fo.send(conversation_id="c", performative="inform")
        await assert_same(fo, mb, "c", "OPEN")

    two_sided(scenario)


def test_a_late_duplicate_close_changes_nothing_on_either_side():
    async def scenario(fo: Side, mb: Side, _: Mesh) -> None:
        await fo.send(conversation_id="c")
        await settle(fo, mb)
        await fo.send(conversation_id="c", performative="close", outcome="resolved")
        await settle(fo, mb)
        repeat = await mb.send(conversation_id="c", performative="close", outcome="failed")
        assert repeat["applied"] is False
        await assert_same(fo, mb, "c", "CLOSED_RESOLVED", "resolved")
        assert (await fo.inbox_message(repeat["message_id"]))["applied"] is False

    two_sided(scenario)


async def both_at_once(mesh: Mesh, fo: Side, mb: Side, first: dict, second: dict) -> tuple[dict, dict]:
    """Have each side accept its message before either notification goes out."""
    mesh.held.clear()
    answers = await asyncio.gather(fo.send(**first), mb.send(**second))
    mesh.held.set()
    return answers


@pytest.mark.parametrize("same_outcome", [True, False])
def test_simultaneous_close(same_outcome):
    async def scenario(fo: Side, mb: Side, mesh: Mesh) -> None:
        winners = set()
        for round_number in range(16):
            conversation = f"c{round_number}"
            await fo.send(conversation_id=conversation)
            await settle(fo, mb)
            fo_outcome, mb_outcome = "resolved", "resolved" if same_outcome else "withdrawn"
            from_fo, from_mb = await both_at_once(
                mesh,
                fo,
                mb,
                {"conversation_id": conversation, "performative": "close", "outcome": fo_outcome},
                {"conversation_id": conversation, "performative": "close", "outcome": mb_outcome},
            )
            assert from_fo["applied"] and from_mb["applied"]
            fo_won = from_fo["message_id"] < from_mb["message_id"]
            winners.add(fo_won)
            outcome = fo_outcome if fo_won else mb_outcome
            await assert_same(fo, mb, conversation, f"CLOSED_{outcome.upper()}", outcome)

            winner, loser = (from_fo, from_mb) if fo_won else (from_mb, from_fo)
            for side in (fo, mb):
                messages = {item["message_id"]: item for item in (await side.conversation(conversation))["messages"]}
                assert messages[winner["message_id"]]["applied"] is True
                assert messages[loser["message_id"]]["applied"] is False
            assert (await fo.status(from_fo["message_id"]))["status"] == "notified"
            assert (await mb.status(from_mb["message_id"]))["status"] == "notified"
        # With random ids, 16 rounds practically always try both orders.
        assert winners == {True, False}

    two_sided(scenario)


def test_simultaneous_escalate():
    async def scenario(fo: Side, mb: Side, mesh: Mesh) -> None:
        winners = set()
        for round_number in range(16):
            conversation = f"c{round_number}"
            await fo.send(conversation_id=conversation)
            await settle(fo, mb)
            step = {"conversation_id": conversation, "performative": "escalate"}
            from_fo, from_mb = await both_at_once(mesh, fo, mb, step, step)
            fo_won = from_fo["message_id"] < from_mb["message_id"]
            winners.add(fo_won)
            shown = await assert_same(fo, mb, conversation, "ESCALATING")
            assert shown["escalated_by"] == (FO if fo_won else MB)
            # The agreed escalator can finish it, and it reaches the same state on both sides.
            await (fo if fo_won else mb).send(conversation_id=conversation, performative="deescalate")
            await assert_same(fo, mb, conversation, "OPEN")
        assert winners == {True, False}

    two_sided(scenario)


def test_several_steps_without_waiting_apply_in_order():
    async def scenario(fo: Side, mb: Side, mesh: Mesh) -> None:
        mesh.varying_offers = True
        await fo.send(conversation_id="c")
        for number in range(6):
            await fo.send(conversation_id="c", performative="close", outcome="resolved")
            await fo.send(conversation_id="c", performative="reopen")
            await fo.send(conversation_id="c", payload={"number": number})
        await fo.send(conversation_id="c", performative="close", outcome="failed")
        await assert_same(fo, mb, "c", "CLOSED_FAILED", "failed")
        assert await mb.count(InboxMessage) == await fo.count(OutboxMessage) == 20

    two_sided(scenario)


def test_an_ordinary_message_crossing_a_close_is_refused_and_both_close():
    async def scenario(fo: Side, mb: Side, mesh: Mesh) -> None:
        await fo.send(conversation_id="c")
        await settle(fo, mb)
        closing, informing = await both_at_once(
            mesh,
            fo,
            mb,
            {"conversation_id": "c", "performative": "close", "outcome": "resolved"},
            {"conversation_id": "c", "performative": "inform", "payload": {"late": True}},
        )
        await assert_same(fo, mb, "c", "CLOSED_RESOLVED", "resolved")
        assert (await mb.status(informing["message_id"]))["status"] == "rejected"
        assert (await fo.status(closing["message_id"]))["status"] == "notified"

    two_sided(scenario)


def test_burst_on_one_conversation_from_both_sides():
    async def scenario(fo: Side, mb: Side, _: Mesh) -> None:
        await fo.send(conversation_id="c")
        await settle(fo, mb)
        answers = await asyncio.gather(
            *[fo.post(conversation_id="c", payload={"from": "fo", "n": n}) for n in range(20)],
            *[mb.post(conversation_id="c", payload={"from": "mb", "n": n}) for n in range(20)],
        )
        assert [answer.status_code for answer in answers] == [202] * 40
        shown = await assert_same(fo, mb, "c", "OPEN")
        assert len(shown["messages"]) == 41
        other = await mb.conversation("c")
        assert {item["message_id"] for item in other["messages"]} == {item["message_id"] for item in shown["messages"]}
        for item in shown["messages"] + other["messages"]:
            assert item["status"] in {"notified", "received"}, item
            assert item["payload"] is not None

    two_sided(scenario)


def test_closes_racing_on_one_side():
    async def scenario(fo: Side, mb: Side, _: Mesh) -> None:
        await fo.send(conversation_id="c")
        await settle(fo, mb)
        outcomes = ["resolved", "failed", "withdrawn", "rejected"] * 5
        answers = await asyncio.gather(
            *[fo.post(conversation_id="c", performative="close", outcome=outcome) for outcome in outcomes]
        )
        assert [answer.status_code for answer in answers] == [202] * 20
        applied = [outcome for answer, outcome in zip(answers, outcomes, strict=True) if answer.json()["applied"]]
        assert len(applied) == 1
        outcome = applied[0]
        await assert_same(fo, mb, "c", f"CLOSED_{outcome.upper()}", outcome)
        received = (await mb.conversation("c"))["messages"]
        assert sum(item["applied"] and item["performative"] == "close" for item in received) == 1
        assert await mb.count(InboxMessage) == 21

    two_sided(scenario)


def test_messages_racing_with_a_close_are_each_accepted_or_refused():
    async def scenario(fo: Side, mb: Side, mesh: Mesh) -> None:
        mesh.varying_offers = True
        await fo.send(conversation_id="c")
        await settle(fo, mb)
        calls = [fo.post(conversation_id="c", payload={"n": n}) for n in range(15)]
        calls.append(fo.post(conversation_id="c", performative="close", outcome="resolved"))
        calls += [fo.post(conversation_id="c", payload={"n": n}) for n in range(15, 30)]
        answers = await asyncio.gather(*calls)
        codes = [answer.status_code for answer in answers]
        assert set(codes) <= {202, 409}
        await assert_same(fo, mb, "c", "CLOSED_RESOLVED", "resolved")
        accepted = codes.count(202)
        assert await fo.count(OutboxMessage) == 32
        # Everything the sender accepted before the close reached the receiver, and nothing was refused there.
        assert await mb.count(InboxMessage) == accepted + 1
        for item in (await mb.conversation("c"))["messages"]:
            assert item["status"] == "received", item

    two_sided(scenario)


def test_first_messages_racing_to_open_a_conversation():
    async def scenario(fo: Side, mb: Side, _: Mesh) -> None:
        answers = await asyncio.gather(*[fo.post(conversation_id="new", payload={"n": n}) for n in range(20)])
        assert [answer.status_code for answer in answers] == [202] * 20
        await assert_same(fo, mb, "new", "OPEN")
        assert await mb.count(InboxMessage) == 20

    two_sided(scenario)


def test_both_sides_opening_the_same_conversation():
    async def scenario(fo: Side, mb: Side, mesh: Mesh) -> None:
        await both_at_once(mesh, fo, mb, {"conversation_id": "new"}, {"conversation_id": "new"})
        shown = await assert_same(fo, mb, "new", "OPEN")
        assert len(shown["messages"]) == 2

    two_sided(scenario)
