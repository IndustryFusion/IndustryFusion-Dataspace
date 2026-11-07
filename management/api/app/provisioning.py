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

"""Registering and removing participants. See management-api.md for the steps and their order."""

import asyncio
import base64
import logging
import secrets as token_source
import weakref
from collections.abc import Awaitable, Callable
from contextlib import asynccontextmanager
from dataclasses import dataclass, field

from fastapi import HTTPException

from app import manifests, roles
from app.config import Settings
from app.databases import Databases
from app.keycloak import KeycloakAdmin
from app.kubernetes import Kubernetes
from app.registry import Registry
from app.storage import Buckets

log = logging.getLogger("management.provisioning")



@dataclass
class Registration:
    participant_id: str
    participant_type: str
    hosted: bool = True
    externally_reachable: bool = False
    adapter_url: str | None = None
    dsp_url: str | None = None
    peer_notify_url: str | None = None


@dataclass
class Undo:
    """What to do if a later step fails, latest first."""

    steps: list[tuple[str, Callable[[], Awaitable[object]]]] = field(default_factory=list)

    def add(self, what: str, action: Callable[[], Awaitable[object]]) -> None:
        self.steps.append((what, action))

    async def run(self) -> list[str]:
        failed = []
        for what, action in reversed(self.steps):
            try:
                await action()
            except Exception:
                log.exception("Could not undo: %s", what)
                failed.append(what)
        return failed


def _answer_for(error: Exception) -> tuple[int, str]:
    if isinstance(error, HTTPException):
        return error.status_code, str(error.detail)
    if isinstance(error, TimeoutError):
        return 502, "The participant's pods did not become available in time"
    log.error("Provisioning failed: %r", error)
    return 502, "A provisioning step failed"


class Provisioner:
    def __init__(
        self, settings: Settings, databases: Databases, kubernetes: Kubernetes, registry: Registry, buckets: Buckets
    ) -> None:
        self.settings = settings
        self.databases = databases
        self.kubernetes = kubernetes
        self.registry = registry
        self.buckets = buckets
        self._locks: weakref.WeakValueDictionary[str, asyncio.Lock] = weakref.WeakValueDictionary()

    @asynccontextmanager
    async def _one_at_a_time(self, participant_id: str):
        lock = self._locks.get(participant_id)
        if lock is None:
            lock = asyncio.Lock()
            self._locks[participant_id] = lock
        async with lock:
            yield

    async def _slug_holder(self, participant_id: str) -> tuple[str | None, dict | None]:
        """Who holds this id's Kubernetes objects, and their Secret."""
        secret = await self.kubernetes.get("Secret", manifests.secret_name(participant_id))
        if secret is None:
            return None, None
        return secret["metadata"].get("annotations", {}).get(manifests.ID_ANNOTATION), secret

    def _record(self, request: Registration) -> dict:
        if request.hosted:
            reachable = request.externally_reachable
            if reachable and not (self.settings.gateway_peer_url and self.settings.dsp_gateway_peer_url):
                raise HTTPException(
                    status_code=422,
                    detail="externally_reachable needs GATEWAY_PEER_URL and DSP_GATEWAY_PEER_URL on this service",
                )
            adapter_url, _ = manifests.hosted_addresses(request.participant_id, self.settings.participants_namespace)
            dsp_url = manifests.announced_dsp(request.participant_id, self.settings, reachable)
            notify = manifests.peer_route(self.settings.gateway_peer_url, request.participant_id) if reachable else None
        else:
            adapter_url, dsp_url, notify = request.adapter_url, request.dsp_url, request.peer_notify_url
        return {
            "participant_id": request.participant_id,
            "participant_type": roles.full_iri(request.participant_type),
            "adapter_url": adapter_url,
            "dsp_url": dsp_url,
            "hosted": request.hosted,
            "externally_reachable": request.externally_reachable,
            "peer_notify_url": notify,
        }

    @staticmethod
    def _refuse_changes(existing: dict, record: dict) -> None:
        if existing["hosted"] != record["hosted"]:
            raise HTTPException(status_code=409, detail="A participant can't change hosting. Delete it first")
        if existing["participant_type"] != record["participant_type"]:
            raise HTTPException(status_code=409, detail="A participant can't change type. Delete it first")

    async def _databases_step(self, participant_id: str, undo: Undo) -> None:
        for name in manifests.database_names(participant_id):
            if await self.databases.create(name):
                undo.add(f"database {name}", lambda name=name: self.databases.drop(name))

    async def _keycloak_step(self, participant_id: str, keycloak: KeycloakAdmin, undo: Undo) -> str:
        role, made_role = await keycloak.ensure_role(participant_id)
        if made_role:
            undo.add("realm role", lambda: keycloak.delete_role(participant_id))
        client_uuid, made_client = await keycloak.ensure_client(participant_id)
        if made_client:
            undo.add("client", lambda: keycloak.delete_client(client_uuid))
        await keycloak.ensure_claim_mapper(participant_id, client_uuid)
        await keycloak.ensure_role_assignment(client_uuid, role)
        return await keycloak.client_secret(client_uuid)

    async def _kubernetes_step(
        self, request: Registration, client_secret: str, existing_secret: dict | None, undo: Undo
    ) -> None:
        participant_id = request.participant_id
        if existing_secret is None:
            key = token_source.token_hex(24)
            # An adapter that started may have made its bucket.
            undo.add("bucket", lambda: self.buckets.remove(manifests.bucket_name(participant_id)))
            undo.add("pods", lambda: self._wait_gone(participant_id))
        else:
            key = base64.b64decode(existing_secret["data"]["edc-api-key"]).decode()
        bare_type = roles.bare_name(request.participant_type)
        objects = manifests.all_objects(
            participant_id, bare_type, self.settings, client_secret, key, request.externally_reachable
        )
        for manifest in objects:
            previous = await self.kubernetes.apply(manifest)
            kind, name = manifest["kind"], manifest["metadata"]["name"]
            if previous is None:
                undo.add(f"{kind} {name}", lambda kind=kind, name=name: self.kubernetes.delete(kind, name))
            else:
                undo.add(f"{kind} {name}", lambda previous=previous: self.kubernetes.restore(previous))
        for name in (manifests.connector_name(participant_id), manifests.adapter_name(participant_id)):
            await self.kubernetes.wait_available(name, self.settings.ready_seconds)

    async def _wait_gone(self, participant_id: str) -> None:
        await self.kubernetes.wait_gone(
            [manifests.adapter_name(participant_id), manifests.connector_name(participant_id)],
            manifests.selector_of(participant_id),
            self.settings.ready_seconds,
        )

    async def register(self, request: Registration, keycloak: KeycloakAdmin) -> dict:
        participant_id = request.participant_id
        async with self._one_at_a_time(participant_id):
            record = self._record(request)
            # Before anything is changed: is this token allowed, and is the client free to use?
            if await keycloak.client_exists_unowned(participant_id):
                raise HTTPException(status_code=409, detail="A client with this id exists, and isn't a participant's")
            existing = await self.registry.get(participant_id)
            if existing is not None:
                self._refuse_changes(existing, record)
            existing_secret = None
            if request.hosted:
                holder, existing_secret = await self._slug_holder(participant_id)
                if holder is not None and holder != participant_id:
                    raise HTTPException(status_code=409, detail="This id's slug is held by another participant")

            undo = Undo()
            try:
                if request.hosted:
                    await self._databases_step(participant_id, undo)
                client_secret = await self._keycloak_step(participant_id, keycloak, undo)
                if request.hosted:
                    await self._kubernetes_step(request, client_secret, existing_secret, undo)
                saved = await self.registry.save(record)
            except Exception as error:
                status, detail = _answer_for(error)
                remaining = await undo.run()
                if remaining:
                    detail = f"{detail}. Some of it could not be undone, so DELETE it: {', '.join(remaining)}"
                raise HTTPException(status_code=status, detail=detail) from error
            return {**saved, "client_id": participant_id, "client_secret": client_secret}

    async def remove(self, participant_id: str, keycloak: KeycloakAdmin) -> None:
        async with self._one_at_a_time(participant_id):
            # Before anything is removed: a token that can't administer Keycloak is refused here.
            await keycloak.client_exists_unowned(participant_id)
            record = await self.registry.get(participant_id)
            failures: list[str] = []
            found = [record is not None]

            async def step(what: str, action: Callable[[], Awaitable[object]]) -> None:
                try:
                    if await action():
                        found[0] = True
                except Exception as error:
                    failures.append(what)
                    log.warning("Could not remove %s: %s", what, _answer_for(error)[1])

            if record is not None:
                await step("registry entry", lambda: self.registry.delete(participant_id))
            if record is None or record.get("hosted", True):
                try:
                    await self._remove_hosted_parts(participant_id, step)
                except HTTPException:
                    failures.append("Kubernetes objects")
            await step("client", lambda: keycloak.delete_owned_client(participant_id))
            await step("realm role", lambda: keycloak.delete_role(participant_id))

            if failures:
                detail = f"Could not remove: {', '.join(failures)}. Repeat this call"
                raise HTTPException(status_code=502, detail=detail)
            if not found[0]:
                raise HTTPException(status_code=404, detail="Participant not found")

    async def _remove_hosted_parts(self, participant_id: str, step) -> None:
        holder, _ = await self._slug_holder(participant_id)
        if holder is not None and holder != participant_id:
            return  # These belong to the participant that holds the slug.
        for kind, name in manifests.object_names(participant_id):
            await step(f"{kind} {name}", lambda kind=kind, name=name: self.kubernetes.delete(kind, name))
        await step("pods", lambda: self._wait_gone(participant_id))
        for name in manifests.database_names(participant_id):
            await step(f"database {name}", lambda name=name: self.databases.drop(name))
        await step("bucket", lambda: self.buckets.remove(manifests.bucket_name(participant_id)))
