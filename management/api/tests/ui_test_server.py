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

"""Serves the real API and the built UI on a port, for the browser tests, with in-memory stand-ins behind the API.

Usage: ui_test_server.py <port> <built UI folder>. The /test/ routes set up what a test needs, and exist only here.
"""

import asyncio
import dataclasses
import json
import pathlib
import sys
import uuid

import httpx
import uvicorn
from conftest import World, json_response
from starlette.responses import Response
from starlette.routing import Route

from app.main import app

CATALOGUE = {
    "factory_owner": [("twin:history", "Machine history", "on-request")],
    "machine_builder": [("mb:confidential", "Vendor confidential", "on-request")],
}


class Adapters:
    """Keeps each adapter's approvals, and answers as an adapter's internal capability routes do."""

    def __init__(self, world: World) -> None:
        self.world = world
        self.approvals: dict[str, list[dict]] = {}
        self.defaults: dict[tuple[str, str], str] = {}
        self.calls: list = []
        self.refuse = False
        self.down = False
        self.answer = None
        self.up = True

    def _kind_of(self, address: str) -> str:
        for record in self.world.registry.records.values():
            if address.startswith(record["adapter_url"] or "//"):
                return record["participant_type"].split("#")[-1]
        raise AssertionError(address)

    def handle(self, request: httpx.Request) -> httpx.Response:
        if self.down:
            raise httpx.ConnectError("down")
        address = f"{request.url.scheme}://{request.url.host}:{request.url.port}"
        held = self.approvals.setdefault(address, [])
        path = request.url.path.removeprefix("/internal/capabilities")
        body = json.loads(request.content) if request.content else {}
        if request.method == "GET":
            offered = [
                {
                    "capability": name,
                    "label": label,
                    "description": label,
                    "data_classification": "operational",
                    "default_policy": default,
                }
                for name, label, default in CATALOGUE[self._kind_of(address)]
            ]
            return json_response(200, {"capabilities": offered, "approvals": held})
        if request.method == "POST":
            key = (body["consumer_id"], body["capability"])
            held[:] = [a for a in held if (a["consumer_id"], a["capability"]) != key]
            status = {"approve": "approved", "deny": "denied", "request": "pending"}[body["action"]]
            entry = {
                "id": uuid.uuid4().hex,
                "consumer_id": body["consumer_id"],
                "capability": body["capability"],
                "status": status,
                "decision_note": body.get("note"),
            }
            held.append(entry)
            return json_response(200, entry)
        if self.refuse:
            return json_response(404, {"detail": "Request not found"})
        identifier = path.removeprefix("/approvals/")
        held[:] = [a for a in held if a["id"] != identifier]
        return json_response(200, {"status": "reset"})


def setup() -> tuple[World, dict]:
    state: dict = {}

    def fresh() -> None:
        world = World(
            demo_participants=[("urn:demo:fo", "factory_owner"), ("urn:demo:mb", "machine_builder")],
            ui_dir=sys.argv[2],
        )
        world.adapters = Adapters(world)
        assert pathlib.Path(world.settings.ui_dir).is_dir()
        state["world"] = world

    state["fresh"] = fresh
    fresh()
    return state["world"], state


_, STATE = setup()


def world() -> World:
    return STATE["world"]


def pair() -> None:
    world().register("urn:ui:fo", "factory_owner")
    world().register("urn:ui:mb", "machine_builder")


def registry_down() -> None:
    world().registry.up = False


def external_builder() -> None:
    world().register(
        "urn:ui:ext", "machine_builder", hosted=False, adapter_url="http://ext.example:1", dsp_url="http://d.example"
    )


def no_peer_addresses() -> None:
    world().services.provisioner.settings = dataclasses.replace(world().settings, gateway_peer_url="")


def short_tokens() -> None:
    world().keycloak.token_seconds = 40


def foreign_client() -> None:
    world().keycloak.add_foreign_client("urn:ui:taken")


def adapter_refuses() -> None:
    world().adapters.refuse = True


def adapter_down() -> None:
    world().adapters.down = True


def route(action):
    async def endpoint(_):
        await asyncio.to_thread(action)
        return Response(status_code=204)

    return endpoint


ROUTES = {
    "reset": STATE["fresh"],
    "pair": pair,
    "registry-down": registry_down,
    "external-builder": external_builder,
    "no-peer-addresses": no_peer_addresses,
    "short-tokens": short_tokens,
    "foreign-client": foreign_client,
    "adapter-refuses": adapter_refuses,
    "adapter-down": adapter_down,
}
# Ahead of the UI's route, which would otherwise answer these paths.
for position, (name, action) in enumerate(ROUTES.items()):
    app.router.routes.insert(position, Route(f"/test/{name}", route(action), methods=["POST"]))


if __name__ == "__main__":
    uvicorn.run(app, host="127.0.0.1", port=int(sys.argv[1]), log_level="warning")
