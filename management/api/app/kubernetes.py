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

"""The Kubernetes API, for the few kinds of object a participant has, in one namespace."""

import asyncio
import pathlib
from collections.abc import Callable
from urllib.parse import quote

import httpx
from fastapi import HTTPException

SERVICE_ACCOUNT = pathlib.Path("/var/run/secrets/kubernetes.io/serviceaccount")
CORE, APPS = "/api/v1", "/apis/apps/v1"
PATHS = {"Secret": (CORE, "secrets"), "ConfigMap": (CORE, "configmaps"), "Service": (CORE, "services"),
         "Deployment": (APPS, "deployments"), "Pod": (CORE, "pods")}  # fmt: skip


def in_cluster_client() -> tuple[httpx.AsyncClient, Callable[[], str]]:
    """A client for this cluster's API, if running in one. The token is read each time, as it is rotated."""
    if not (SERVICE_ACCOUNT / "token").exists():
        return httpx.AsyncClient(base_url="http://kubernetes.invalid", timeout=30), lambda: ""
    client = httpx.AsyncClient(
        base_url="https://kubernetes.default.svc",
        verify=str(SERVICE_ACCOUNT / "ca.crt"),
        timeout=30,
    )
    return client, lambda: (SERVICE_ACCOUNT / "token").read_text()


class Kubernetes:
    def __init__(self, http: httpx.AsyncClient, token: Callable[[], str], namespace: str, poll_seconds: float) -> None:
        self.http = http
        self.token = token
        self.namespace = namespace
        self.poll_seconds = poll_seconds

    def _path(self, kind: str, name: str | None = None) -> str:
        group, plural = PATHS[kind]
        base = f"{group}/namespaces/{self.namespace}/{plural}"
        return f"{base}/{quote(name, safe='')}" if name else base

    async def _call(self, method: str, path: str, allow: tuple[int, ...] = (), **options) -> httpx.Response:
        headers = {"Authorization": f"Bearer {self.token()}"}
        try:
            answer = await self.http.request(method, path, headers=headers, **options)
        except httpx.HTTPError as error:
            raise HTTPException(status_code=502, detail="The Kubernetes API is unavailable") from error
        if answer.status_code >= 300 and answer.status_code not in allow:
            raise HTTPException(status_code=502, detail=f"Kubernetes answered {answer.status_code} to {method}")
        return answer

    async def get(self, kind: str, name: str) -> dict | None:
        answer = await self._call("GET", self._path(kind, name), allow=(404,))
        return None if answer.status_code == 404 else answer.json()

    async def apply(self, manifest: dict) -> dict | None:
        """Create or replace an object. Return what it replaced, if anything."""
        kind, name = manifest["kind"], manifest["metadata"]["name"]
        previous = await self.get(kind, name)
        if previous is None:
            made = await self._call("POST", self._path(kind), allow=(409,), json=manifest)
            if made.status_code != 409:
                return None
            previous = await self.get(kind, name)
            if previous is None:
                raise HTTPException(status_code=502, detail=f"Kubernetes gave conflicting answers about a {kind}")
        await self.put(manifest, previous)
        return previous

    async def put(self, manifest: dict, current: dict) -> None:
        body = {**manifest, "metadata": {**manifest["metadata"]}}
        body["metadata"]["resourceVersion"] = current["metadata"]["resourceVersion"]
        if manifest["kind"] == "Service":
            # A Service keeps the address it was given.
            spec = dict(manifest["spec"])
            for key in ("clusterIP", "clusterIPs"):
                if key in current["spec"]:
                    spec[key] = current["spec"][key]
            body["spec"] = spec
        await self._call("PUT", self._path(manifest["kind"], manifest["metadata"]["name"]), json=body)

    async def restore(self, previous: dict) -> None:
        """Put an object back as it was."""
        current = await self.get(previous["kind"], previous["metadata"]["name"])
        manifest = {**previous, "metadata": {**previous["metadata"]}}
        if current is None:
            manifest["metadata"].pop("resourceVersion", None)
            manifest["metadata"].pop("uid", None)
            await self._call("POST", self._path(previous["kind"]), json=manifest)
        else:
            await self.put(manifest, current)

    async def delete(self, kind: str, name: str) -> bool:
        """Return whether there was such an object."""
        answer = await self._call(
            "DELETE",
            self._path(kind, name),
            allow=(404,),
            params={"propagationPolicy": "Foreground"} if kind == "Deployment" else None,
        )
        return answer.status_code != 404

    async def wait_available(self, name: str, seconds: float) -> None:
        async with asyncio.timeout(seconds):
            while True:
                found = await self.get("Deployment", name)
                if found:
                    status = found.get("status", {})
                    current = status.get("observedGeneration", 0) >= found["metadata"].get("generation", 1)
                    if current and status.get("updatedReplicas", 0) >= 1 and status.get("availableReplicas", 0) >= 1:
                        return
                await asyncio.sleep(self.poll_seconds)

    async def wait_gone(self, deployments: list[str], label_selector: str, seconds: float) -> None:
        """Wait until the Deployments and their pods have gone. A pod still running could recreate what it uses."""
        async with asyncio.timeout(seconds):
            while True:
                pods = (await self._call("GET", self._path("Pod"), params={"labelSelector": label_selector})).json()
                remaining = [name for name in deployments if await self.get("Deployment", name)]
                if not remaining and not pods.get("items"):
                    return
                await asyncio.sleep(self.poll_seconds)
