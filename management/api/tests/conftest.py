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

"""In-memory stand-ins for what the service calls. The HTTP clients run for real, against these over a transport."""

import asyncio
import base64
import json
import re
import time
import uuid
from urllib.parse import parse_qs, unquote

import httpx
import jwt
import pytest
from cryptography.hazmat.primitives.asymmetric import rsa
from fastapi import HTTPException
from fastapi.testclient import TestClient
from jwt.algorithms import RSAAlgorithm

from app.config import Settings
from app.kubernetes import Kubernetes
from app.main import app, build_services

KEYCLOAK = "http://keycloak.test/auth"
ISSUER = f"{KEYCLOAK}/realms/dataspace"
REGISTRY = "http://registry.test:19000"
SIGNING_KEY = rsa.generate_private_key(public_exponent=65537, key_size=2048)
OTHER_KEY = rsa.generate_private_key(public_exponent=65537, key_size=2048)


def make_token(roles=("dataspace-admin",), key=SIGNING_KEY, issuer=ISSUER, expires_in=300, kid="k1") -> str:
    claims = {"iss": issuer, "exp": int(time.time()) + expires_in, "realm_access": {"roles": list(roles)}}
    return jwt.encode(claims, key, algorithm="RS256", headers={"kid": kid})


def json_response(status: int, body: object = None) -> httpx.Response:
    return httpx.Response(status, json=body) if body is not None else httpx.Response(status)


class FakeKeycloak:
    def __init__(self) -> None:
        self.roles: dict[str, dict] = {}
        self.clients: dict[str, dict] = {}
        self.assignments: dict[str, list[dict]] = {}
        self.seen_tokens: list[str] = []
        self.fail: re.Pattern | None = None
        self.refuse_admin = False
        self.up = True
        self.token_seconds = 300

    def add_foreign_client(self, client_id: str) -> None:
        self.clients["foreign"] = {"id": "foreign", "clientId": client_id, "attributes": {}, "protocolMappers": []}

    def client_of(self, client_id: str) -> dict | None:
        return next((c for c in self.clients.values() if c["clientId"] == client_id), None)

    def handle(self, request: httpx.Request) -> httpx.Response:
        if not self.up:
            raise httpx.ConnectError("down")
        path = unquote(request.url.raw_path.decode().split("?")[0])
        if path == "/auth/realms/dataspace/protocol/openid-connect/certs":
            public = json.loads(RSAAlgorithm.to_jwk(SIGNING_KEY.public_key()))
            return json_response(200, {"keys": [{**public, "kid": "k1", "use": "sig"}]})
        if path == "/auth/realms/dataspace/protocol/openid-connect/token":
            form = parse_qs(request.content.decode())
            if form.get("client_secret") == ["right"]:
                answer = {"access_token": make_token(), "expires_in": self.token_seconds, "token_type": "Bearer"}
                return json_response(200, answer)
            return json_response(401, {"error": "unauthorized_client"})
        if path == "/auth/realms/dataspace":
            return json_response(200, {"realm": "dataspace"})
        self.seen_tokens.append(request.headers.get("Authorization", ""))
        if self.refuse_admin:
            return json_response(403, {"error": "forbidden"})
        if self.fail and self.fail.search(f"{request.method} {path}"):
            return json_response(500, {"error": "injected"})
        return self._admin(request, path.removeprefix("/auth/admin/realms/dataspace"))

    def _admin(self, request: httpx.Request, path: str) -> httpx.Response:
        body = json.loads(request.content) if request.content else None
        method = request.method
        if path == "/roles" and method == "POST":
            if body["name"] in self.roles:
                return json_response(409, {})
            self.roles[body["name"]] = {"id": uuid.uuid4().hex, "name": body["name"]}
            return json_response(201)
        if match := re.fullmatch(r"/roles/(.+)", path):
            name = match[1]
            if name not in self.roles:
                return json_response(404, {})
            if method == "DELETE":
                del self.roles[name]
                for held in self.assignments.values():
                    held[:] = [role for role in held if role["name"] != name]
                return json_response(204)
            return json_response(200, self.roles[name])
        if path == "/clients" and method == "GET":
            wanted = parse_qs(request.url.query.decode()).get("clientId", [None])[0]
            return json_response(200, [c for c in self.clients.values() if c["clientId"] == wanted])
        if path == "/clients" and method == "POST":
            if self.client_of(body["clientId"]):
                return json_response(409, {})
            uid = uuid.uuid4().hex
            self.clients[uid] = {"id": uid, "secret": f"secret-{uid}", **body}
            self.clients[uid]["protocolMappers"] = [
                {**mapper, "id": uuid.uuid4().hex} for mapper in body.get("protocolMappers", [])
            ]
            return json_response(201)
        if match := re.fullmatch(r"/clients/([^/]+)/protocol-mappers/models(?:/([^/]+))?", path):
            client = self.clients[match[1]]
            if method == "GET":
                return json_response(200, client["protocolMappers"])
            if method == "POST":
                client["protocolMappers"].append({**body, "id": uuid.uuid4().hex})
                return json_response(201)
            client["protocolMappers"] = [body if m["id"] == match[2] else m for m in client["protocolMappers"]]
            return json_response(204)
        if match := re.fullmatch(r"/clients/([^/]+)/service-account-user", path):
            return json_response(200, {"id": f"sa-{match[1]}"})
        if match := re.fullmatch(r"/clients/([^/]+)/client-secret", path):
            return json_response(200, {"value": self.clients[match[1]]["secret"]})
        if match := re.fullmatch(r"/clients/([^/]+)", path):
            if method == "DELETE":
                return json_response(204) if self.clients.pop(match[1], None) else json_response(404, {})
            self.clients[match[1]] = {**self.clients[match[1]], **body}
            return json_response(204)
        if match := re.fullmatch(r"/users/([^/]+)/role-mappings/realm", path):
            held = self.assignments.setdefault(match[1], [])
            if method == "GET":
                return json_response(200, held)
            held.extend(body)
            return json_response(204)
        raise AssertionError(f"Unexpected Keycloak call: {method} {path}")


class FakeKubernetes:
    """Available at once, unless a Deployment is listed in `never_available`."""

    PLURALS = {"secrets": "Secret", "configmaps": "ConfigMap", "services": "Service", "deployments": "Deployment"}

    def __init__(self) -> None:
        self.objects: dict[tuple[str, str], dict] = {}
        self.fail: re.Pattern | None = None
        self.never_available: set[str] = set()
        self.calls: list[str] = []
        self.version = 0

    def _store(self, manifest: dict) -> None:
        self.version += 1
        kept = dict(manifest)
        kept["metadata"] = {**manifest["metadata"], "resourceVersion": str(self.version), "generation": 1}
        if manifest["kind"] == "Secret" and "stringData" in manifest:
            encoded = {k: base64.b64encode(v.encode()).decode() for k, v in manifest["stringData"].items()}
            kept["data"] = encoded
            kept.pop("stringData")
        if manifest["kind"] == "Service":
            kept["spec"] = {"clusterIP": "10.0.0.1", **manifest["spec"]}
        if manifest["kind"] == "Deployment":
            name = manifest["metadata"]["name"]
            updating = ("Deployment", name) in self.objects
            if name not in self.never_available:
                status = {"replicas": 1, "updatedReplicas": 1, "availableReplicas": 1}
            elif updating:
                # The old pod still runs, and the new one never becomes available.
                status = {"replicas": 2, "updatedReplicas": 1, "availableReplicas": 1}
            else:
                status = {"replicas": 1, "updatedReplicas": 1, "availableReplicas": 0}
            kept["status"] = {"observedGeneration": 1, **status}
        self.objects[(manifest["kind"], manifest["metadata"]["name"])] = kept

    def handle(self, request: httpx.Request) -> httpx.Response:
        path = request.url.path
        self.calls.append(f"{request.method} {path}")
        if self.fail and self.fail.search(f"{request.method} {path}"):
            return json_response(500, {"message": "injected"})
        match = re.fullmatch(r"/apis?/(?:apps/)?v1/namespaces/dataspace-participants/([a-z]+)(?:/([^/]+))?", path)
        assert match, path
        plural, name = match[1], match[2]
        if plural == "pods":
            return json_response(200, {"items": []})
        kind = self.PLURALS[plural]
        key = (kind, name)
        if request.method == "GET":
            found = self.objects.get(key)
            return json_response(200, found) if found else json_response(404, {})
        if request.method == "POST":
            manifest = json.loads(request.content)
            if (kind, manifest["metadata"]["name"]) in self.objects:
                return json_response(409, {})
            self._store(manifest)
            return json_response(201, {})
        if request.method == "PUT":
            self._store(json.loads(request.content))
            return json_response(200, {})
        if request.method == "DELETE":
            return json_response(200, {}) if self.objects.pop(key, None) else json_response(404, {})
        raise AssertionError(path)


class FakeRegistry:
    def __init__(self) -> None:
        self.records: dict[str, dict] = {}
        self.up = True
        self.fail_save = False

    def handle(self, request: httpx.Request) -> httpx.Response:
        if not self.up:
            raise httpx.ConnectError("down")
        path = unquote(request.url.raw_path.decode())
        if path == "/health":
            return json_response(200, {"status": "ok"})
        if path == "/participants" and request.method == "GET":
            return json_response(200, list(self.records.values()))
        if path == "/participants":
            if self.fail_save:
                return json_response(500, {})
            record = json.loads(request.content)
            self.records[record["participant_id"]] = record
            return json_response(200, record)
        if path.startswith("/participants/compatible/"):
            me = self.records.get(path.removeprefix("/participants/compatible/"))
            if not me:
                return json_response(404, {"detail": "Participant not found"})
            others = (r for r in self.records.values() if r["participant_type"] != me["participant_type"])
            return json_response(200, list(others))
        participant_id = path.removeprefix("/participants/")
        if request.method == "DELETE":
            return json_response(204) if self.records.pop(participant_id, None) else json_response(404, {})
        found = self.records.get(participant_id)
        return json_response(200, found) if found else json_response(404, {"detail": "Participant not found"})


class FakeAdapters:
    """Answers capability calls at any address, and records the key each was given."""

    def __init__(self) -> None:
        self.calls: list[tuple[str, str, str | None, dict | None]] = []
        self.state = {
            "capabilities": [
                {
                    "capability": "twin:history", "label": "Machine history", "description": "...",
                    "data_classification": "operational", "default_policy": "on-request",
                }
            ],
            "approvals": [],
        }  # fmt: skip
        self.answer: httpx.Response | None = None
        self.up = True

    def handle(self, request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content) if request.content else None
        self.calls.append((request.method, str(request.url), request.headers.get("X-Internal-Key"), body))
        if not self.up:
            raise httpx.ConnectError("down")
        if self.answer is not None:
            return self.answer
        if request.method == "GET":
            return json_response(200, self.state)
        if request.method == "POST":
            return json_response(202 if body["action"] == "request" else 200, {"status": body["action"], **body})
        return json_response(200, {"ok": True, **(body or {})})


class FakeIfric:
    def __init__(self) -> None:
        self.companies: object = []
        self.status = 200
        self.up = True
        self.calls = 0
        self.authorizations: list[str] = []

    def handle(self, request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/company/get-all-companies"
        self.calls += 1
        self.authorizations.append(request.headers.get("Authorization", ""))
        if not self.up:
            raise httpx.ConnectError("down")
        return json_response(self.status, self.companies)


class FakeDatabases:
    def __init__(self) -> None:
        self.names: set[str] = set()
        self.fail_create: str | None = None
        self.fail_drop = False

    async def create(self, name: str) -> bool:
        if self.fail_create and name.startswith(self.fail_create):
            raise HTTPException(status_code=503, detail="PostgreSQL refused or did not answer")
        if name in self.names:
            return False
        self.names.add(name)
        return True

    async def drop(self, name: str) -> bool:
        if self.fail_drop:
            raise HTTPException(status_code=503, detail="PostgreSQL refused or did not answer")
        existed = name in self.names
        self.names.discard(name)
        return existed

    async def healthy(self) -> None:
        return None


class FakeBuckets:
    def __init__(self) -> None:
        self.names: set[str] = set()
        self.removed: list[str] = []

    async def remove(self, bucket: str) -> bool:
        self.removed.append(bucket)
        existed = bucket in self.names
        self.names.discard(bucket)
        return existed


class World:
    def __init__(self, **settings) -> None:
        self.keycloak, self.kubernetes, self.registry = FakeKeycloak(), FakeKubernetes(), FakeRegistry()
        self.adapters = FakeAdapters()
        self.ifric = FakeIfric()
        self.settings = Settings(
            keycloak_url=KEYCLOAK,
            registry_url=REGISTRY,
            postgres_user="dataspace",
            postgres_password="p@ss/word",
            s3_endpoint="http://storage.test",
            s3_access_key="s3-access",
            s3_secret_key="hidden-s3-value",
            adapter_internal_key="the-internal-key",
            gateway_peer_url="http://gateway.test:8080",
            gateway_url="http://gateway.test:8080",
            dsp_gateway_url="http://dsp.test:8085",
            dsp_gateway_peer_url="http://dsp-public.test:8085",
            ready_seconds=0.2,
            poll_seconds=0.01,
            **settings,
        )

        async def route(request: httpx.Request) -> httpx.Response:
            # A real call lets other requests run, and concurrency tests depend on that.
            await asyncio.sleep(0)
            host = request.url.host
            if host == "keycloak.test":
                return self.keycloak.handle(request)
            if host == "registry.test":
                return self.registry.handle(request)
            if host == "ifric.test":
                return self.ifric.handle(request)
            if host in ("gateway.test", "dsp.test", "storage.test"):
                return json_response(200, {})
            return self.adapters.handle(request)

        async def kube_route(request: httpx.Request) -> httpx.Response:
            await asyncio.sleep(0)
            return self.kubernetes.handle(request)

        self.http = httpx.AsyncClient(transport=httpx.MockTransport(route))
        kube_http = httpx.AsyncClient(
            base_url="https://kubernetes.test", transport=httpx.MockTransport(kube_route)
        )
        kube = Kubernetes(kube_http, lambda: "service-account", "dataspace-participants", 0.01)
        self.services = build_services(self.settings, self.http, kube)
        self.databases, self.buckets = FakeDatabases(), FakeBuckets()
        self.services.databases = self.databases
        self.services.provisioner.databases = self.databases
        self.services.provisioner.buckets = self.buckets
        app.state.services = self.services
        self.client = TestClient(app)
        self.admin = {"Authorization": f"Bearer {make_token()}"}

    def register(self, participant_id="urn:test:fo", participant_type="factory_owner", **fields) -> httpx.Response:
        body = {"participant_id": participant_id, "participant_type": participant_type, **fields}
        return self.client.post("/api/participants", json=body, headers=self.admin)

    def nothing_of(self, participant_id: str) -> None:
        """Assert that nothing of this participant is left anywhere."""
        from app import manifests

        name = manifests.slug(participant_id)
        assert not [key for key in self.kubernetes.objects if name in key[1]]
        assert not [db for db in self.databases.names if name in db]
        assert f"participant:{participant_id}" not in self.keycloak.roles
        assert self.keycloak.client_of(participant_id) is None
        assert participant_id not in self.registry.records


@pytest.fixture
def world():
    instance = World()
    yield instance
    app.state.services = None
