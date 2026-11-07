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
import dataclasses
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
from app.storage import Buckets, StorageIdentities
from app.tokens import fetch_admin_token

log = logging.getLogger("management.provisioning")

# What an undo may add to a registration's deadline, and how much of that may go on waiting for pods to go. Whatever
# sits in front of this service allows for the deadline and a little more. See deploy/README.md.
UNDO_SECONDS = 50
UNDO_PODS_SECONDS = 30


@dataclass
class Registration:
    participant_id: str
    participant_type: str
    hosted: bool = True
    externally_reachable: bool | None = None
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
        """What couldn't be undone, including what there was no time left for."""
        failed = []
        deadline = asyncio.get_running_loop().time() + UNDO_SECONDS
        for what, action in reversed(self.steps):
            try:
                async with asyncio.timeout_at(deadline):
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
        self,
        settings: Settings,
        databases: Databases,
        kubernetes: Kubernetes,
        registry: Registry,
        buckets: Buckets,
        identities: StorageIdentities,
    ) -> None:
        self.settings = settings
        self.databases = databases
        self.kubernetes = kubernetes
        self.registry = registry
        self.buckets = buckets
        self.identities = identities
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

    def _reachability(self, request: Registration) -> tuple[bool, list[str]]:
        """Whether this participant will be reachable from outside, and why not if it was meant to be."""
        if not request.hosted:
            return bool(request.externally_reachable), []
        if request.externally_reachable is False:
            return False, []
        missing = [
            name
            for name, value in (
                ("GATEWAY_PEER_URL", self.settings.gateway_peer_url),
                ("DSP_GATEWAY_PEER_URL", self.settings.dsp_gateway_peer_url),
            )
            if not value
        ]
        if missing:
            warning = (
                "Registered as not reachable from outside, as this service has no "
                f"{' or '.join(missing)}. Set it, and register the participant again to make it reachable"
            )
            return False, [warning]
        return True, []

    def _record(self, request: Registration, reachable: bool) -> dict:
        if request.hosted:
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
            "externally_reachable": reachable,
            "peer_notify_url": notify,
        }

    @staticmethod
    def _refuse_changes(existing: dict, record: dict) -> None:
        if existing["hosted"] != record["hosted"]:
            raise HTTPException(status_code=409, detail="A participant can't change hosting. Delete it first")
        if existing["participant_type"] != record["participant_type"]:
            raise HTTPException(status_code=409, detail="A participant can't change type. Delete it first")

    def _credentials(self, participant_id: str, existing_secret: dict | None) -> manifests.Credentials:
        """A repeated registration keeps what the participant holds. Anything missing is made."""
        data = (existing_secret or {}).get("data", {})

        def kept(key: str) -> str | None:
            return base64.b64decode(data[key]).decode() if key in data else None

        # With identities to manage, the storage makes the keys.
        s3_access_key = kept("s3-access-key") if self.identities.enabled else self.settings.s3_access_key
        s3_secret_key = kept("s3-secret-key") if self.identities.enabled else self.settings.s3_secret_key
        return manifests.Credentials(
            edc_api_key=kept("edc-api-key") or token_source.token_hex(24),
            database_password=kept("db-password") or token_source.token_hex(24),
            internal_key=kept("internal-key") or token_source.token_hex(24),
            s3_access_key=s3_access_key or "",
            s3_secret_key=s3_secret_key or "",
        )

    async def _databases_step(self, participant_id: str, password: str, undo: Undo) -> None:
        user = manifests.database_user(participant_id)
        if await self.databases.ensure_user(user, password):
            undo.add(f"database user {user}", lambda: self.databases.drop_user(user))
        for name in manifests.database_names(participant_id):
            if await self.databases.create(name, user):
                undo.add(f"database {name}", lambda name=name: self.databases.drop(name))

    async def _storage_step(
        self, participant_id: str, credentials: manifests.Credentials, is_new: bool, undo: Undo
    ) -> manifests.Credentials:
        """Without identities to manage, the participant uses the configured one, and its adapter makes the bucket."""
        if not self.identities.enabled:
            return credentials
        name = manifests.storage_identity(participant_id)
        bucket = manifests.bucket_name(participant_id)
        await self.buckets.create(bucket)
        if is_new:
            undo.add("bucket", lambda: self.buckets.remove(bucket))
        held = (credentials.s3_access_key, credentials.s3_secret_key) if credentials.s3_access_key else None
        access_key, secret_key, made = await self.identities.ensure(name, bucket, held)
        if made:
            undo.add(f"storage identity {name}", lambda: self.identities.remove(name))
        await self.buckets.wait_usable(bucket, access_key, secret_key)
        return dataclasses.replace(credentials, s3_access_key=access_key, s3_secret_key=secret_key)

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
        self,
        request: Registration,
        reachable: bool,
        client_secret: str,
        credentials: manifests.Credentials,
        existing_secret: dict | None,
        undo: Undo,
    ) -> None:
        participant_id = request.participant_id
        if existing_secret is None:
            # An adapter that started may have made its bucket.
            undo.add("bucket", lambda: self.buckets.remove(manifests.bucket_name(participant_id)))
            undo.add("pods", lambda: self._wait_gone(participant_id, UNDO_PODS_SECONDS))
        bare_type = roles.bare_name(request.participant_type)
        objects = manifests.all_objects(
            participant_id, bare_type, self.settings, client_secret, credentials, reachable
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

    async def _wait_gone(self, participant_id: str, most_seconds: float | None = None) -> None:
        await self.kubernetes.wait_gone(
            [manifests.adapter_name(participant_id), manifests.connector_name(participant_id)],
            manifests.selector_of(participant_id),
            min(self.settings.ready_seconds, most_seconds or self.settings.ready_seconds),
        )

    async def _use_own_token(self, keycloak: KeycloakAdmin) -> None:
        """The caller's token can have expired during a wait. Without a credential of its own, it is all there is."""
        if not self.settings.management_client_secret:
            return
        try:
            answer = await fetch_admin_token(
                keycloak.http,
                self.settings.issuer,
                self.settings.management_client_id,
                self.settings.management_client_secret,
            )
            keycloak.use_token(answer["access_token"])
        except (HTTPException, KeyError, TypeError) as error:
            log.warning("Could not get this service's own token: %s", type(error).__name__)

    async def register(self, request: Registration, keycloak: KeycloakAdmin) -> dict:
        participant_id = request.participant_id
        async with self._one_at_a_time(participant_id):
            reachable, warnings = self._reachability(request)
            record = self._record(request, reachable)
            deadline = asyncio.get_running_loop().time() + self.settings.ready_seconds
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
                async with asyncio.timeout_at(deadline):
                    credentials = self._credentials(participant_id, existing_secret)
                    if request.hosted:
                        await self._databases_step(participant_id, credentials.database_password, undo)
                    client_secret = await self._keycloak_step(participant_id, keycloak, undo)
                    if request.hosted:
                        credentials = await self._storage_step(
                            participant_id, credentials, existing_secret is None, undo
                        )
                        await self._kubernetes_step(
                            request, reachable, client_secret, credentials, existing_secret, undo
                        )
                    saved = await self.registry.save(record)
            except Exception as error:
                status, detail = _answer_for(error)
                await self._use_own_token(keycloak)
                remaining = await undo.run()
                if remaining:
                    detail = f"{detail}. Some of it could not be undone, so DELETE it: {', '.join(remaining)}"
                raise HTTPException(status_code=status, detail=detail) from error
            return {**saved, "client_id": participant_id, "client_secret": client_secret, "warnings": warnings}

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
            await self._use_own_token(keycloak)
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
        user = manifests.database_user(participant_id)
        await step(f"database user {user}", lambda: self.databases.drop_user(user))
        await step("bucket", lambda: self.buckets.remove(manifests.bucket_name(participant_id)))
        if self.identities.enabled:
            identity = manifests.storage_identity(participant_id)
            await step(f"storage identity {identity}", lambda: self.identities.remove(identity))
