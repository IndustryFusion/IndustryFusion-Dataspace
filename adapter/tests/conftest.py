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

"""A real adapter app on SQLite and in-memory storage, with its neighbours faked."""

import json
import time

import httpx
import jwt
import pytest
from cryptography.hazmat.primitives.asymmetric import rsa
from fastapi.testclient import TestClient

from app.auth import OwnToken, TokenVerifier
from app.config import Settings, role_for
from app.connector import ConnectorError  # noqa: F401 - imported by tests from here
from app.db import Database
from app.delivery import Services
from app.main import create_app
from app.registry import Registry
from app.storage import MemoryStorage

ME = "urn:test:fo"
PEER = "urn:test:mb"
ISSUER = "http://keycloak.test/realms/dataspace"
KEY = rsa.generate_private_key(public_exponent=65537, key_size=2048)
OTHER_KEY = rsa.generate_private_key(public_exponent=65537, key_size=2048)


def token(participant: str = ME, issuer: str = ISSUER, key=KEY, roles: list[str] | None = None) -> str:
    claims = {
        "iss": issuer,
        "exp": int(time.time()) + 300,
        "participant_id": participant,
        "realm_access": {"roles": roles if roles is not None else [role_for(participant)]},
    }
    return jwt.encode(claims, key, algorithm="RS256", headers={"kid": "test"})


def auth(participant: str = ME) -> dict[str, str]:
    return {"Authorization": f"Bearer {token(participant)}"}


class FakeConnector:
    """Records calls. On a transfer, it pushes content the way a data plane would."""

    def __init__(self) -> None:
        self.offered: list[tuple[str, str]] = []
        self.on_offer = None
        self.transfer_id: str | None = "provider-transfer"
        self.transfer_lookup_error: Exception | None = None
        self.offer_error: Exception | None = None
        self.fetch_error: Exception | None = None
        self.on_push = None
        self.after_push_error: Exception | None = None

    async def offer(self, asset_id: str, source_url: str) -> None:
        if self.offer_error:
            raise self.offer_error
        if self.on_offer:
            await self.on_offer(asset_id)
        self.offered.append((asset_id, source_url))

    async def find_offer(self, asset_id: str, provider_id: str, provider_dsp: str) -> str:
        if self.fetch_error:
            raise self.fetch_error
        return f"offer-{asset_id}"

    async def negotiate(self, offer_id, asset_id, provider_id, provider_dsp) -> str:
        return "negotiation"

    async def wait_for_agreement(self, negotiation_id: str, deadline: float) -> str:
        return "agreement"

    async def push(self, agreement_id: str, provider_dsp: str, destination_url: str) -> str:
        if self.on_push:
            await self.on_push(destination_url)
        return "transfer"

    async def wait_for_transfer(self, transfer_id: str, deadline: float) -> None:
        if self.after_push_error:
            raise self.after_push_error

    async def transfer_for_asset(self, asset_id: str) -> str | None:
        if self.transfer_lookup_error:
            raise self.transfer_lookup_error
        return self.transfer_id


class World:
    """What the adapter's HTTP client can reach: Keycloak, the registry and the peer."""

    def __init__(self) -> None:
        self.registered = {PEER: {"participant_id": PEER, "adapter_url": "http://peer.test"}}
        self.compatible = [PEER]
        self.registry_up = True
        self.peer_status = 202
        self.peer_error: Exception | None = None
        self.notifications: list[dict] = []
        self.calls_to_peer: list[httpx.Request] = []
        self.peer_body: dict | None = None

    def handle(self, request: httpx.Request) -> httpx.Response:
        url = str(request.url)
        if url.endswith("/protocol/openid-connect/certs"):
            jwk = json.loads(jwt.algorithms.RSAAlgorithm.to_jwk(KEY.public_key()))
            return httpx.Response(200, json={"keys": [{**jwk, "kid": "test", "use": "sig"}]})
        if url.endswith("/protocol/openid-connect/token"):
            return httpx.Response(200, json={"access_token": token(), "expires_in": 300})
        if url.startswith("http://registry.test"):
            if not self.registry_up:
                raise httpx.ConnectError("down")
            path = request.url.path
            if path.startswith("/participants/compatible/"):
                return httpx.Response(200, json=[{"participant_id": item} for item in self.compatible])
            record = self.registered.get(path.removeprefix("/participants/"))
            return httpx.Response(200, json=record) if record else httpx.Response(404, json={})
        if url.startswith("http://peer.test"):
            if self.peer_error:
                raise self.peer_error
            self.calls_to_peer.append(request)
            if self.peer_body is not None:
                return httpx.Response(self.peer_status, json=self.peer_body)
            if "/internal/capabilities" in url:
                return httpx.Response(self.peer_status, text="peer answer")
            self.notifications.append(
                {"url": url, "body": json.loads(request.content), "auth": request.headers.get("Authorization")}
            )
            return httpx.Response(self.peer_status, text="peer answer")
        raise AssertionError(f"Unexpected call: {url}")


class Harness:
    def __init__(self, client: TestClient, services: Services, world: World, connector: FakeConnector) -> None:
        self.client = client
        self.services = services
        self.world = world
        self.connector = connector
        self.storage: MemoryStorage = services.storage

    def settle(self) -> None:
        self.client.portal.call(self.services.settle)

    def run(self, function, *args):
        return self.client.portal.call(function, *args)

    def send(self, **body) -> httpx.Response:
        response = self.client.post("/outbox/messages", json={"receiver_participant": PEER, **body}, headers=auth())
        self.settle()
        return response

    def notify(self, message_id: str = "m1", sender: str = PEER, **fields) -> httpx.Response:
        body = {
            "message_id": message_id,
            "conversation_id": "c1",
            "sender_participant": sender,
            "receiver_participant": ME,
            "asset_id": message_id,
            "provider_dsp_url": "http://peer-connector.test/dsp",
            **fields,
        }
        return self.client.post("/internal/transfer-request", json=body, headers=auth(sender))


@pytest.fixture
def harness(tmp_path):
    settings = Settings(
        participant_id=ME,
        participant_type="factory_owner",
        adapter_internal_key="test-internal-key",
        adapter_url="http://me.test",
        edc_dsp_url="http://me-connector.test/dsp",
        keycloak_url="http://keycloak.test",
        keycloak_realm="dataspace",
        keycloak_client_secret="unused",
        registry_url="http://registry.test",
        transfer_budget_seconds=5,
    )
    world = World()
    connector = FakeConnector()
    http = httpx.AsyncClient(transport=httpx.MockTransport(world.handle))
    services = Services(
        settings=settings,
        db=Database(f"sqlite+aiosqlite:///{tmp_path}/adapter.db"),
        storage=MemoryStorage(),
        verifier=TokenVerifier(settings, http),
        own_token=OwnToken(settings, http),
        connector=connector,
        registry=Registry(settings.registry_url, http),
        http=http,
    )
    with TestClient(create_app(services)) as client:
        client.portal.call(services.db.ensure_schema)
        built = Harness(client, services, world, connector)

        async def push_empty_object(destination: str) -> None:
            built.pushed_to = destination

        connector.on_push = push_empty_object
        yield built
        client.portal.call(services.settle)
        client.portal.call(services.db.close)


