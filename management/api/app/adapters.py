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

"""Capability calls to a hosted participant's adapter, using its internal routes and its own key."""

import base64
from urllib.parse import quote

import httpx
from fastapi import HTTPException

from app import manifests
from app.kubernetes import Kubernetes

PASSED_ON = {400, 403, 404, 409, 422}


class Adapters:
    def __init__(self, http: httpx.AsyncClient, kubernetes: Kubernetes, namespace: str) -> None:
        self.http = http
        self.kubernetes = kubernetes
        self.namespace = namespace

    async def _key_of(self, participant_id: str) -> str:
        secret = await self.kubernetes.get("Secret", manifests.secret_name(participant_id))
        encoded = (secret or {}).get("data", {}).get("internal-key")
        if not encoded:
            raise HTTPException(status_code=503, detail="This participant has no internal key")
        return base64.b64decode(encoded).decode()

    async def call(self, record: dict, method: str, path: str, body: dict | None = None) -> tuple[int, object]:
        """Call the adapter of a registry record, with the key that participant alone has.

        The registry takes writes from any pod, so none of its addresses gets a key. It only goes to the address
        derived from the id, where only this service can have put anything.
        """
        if not record.get("hosted", False):
            raise HTTPException(status_code=409, detail="An external participant runs its own adapter")
        address, _ = manifests.hosted_addresses(record["participant_id"], self.namespace)
        key = await self._key_of(record["participant_id"])
        try:
            answer = await self.http.request(
                method, f"{address}/internal/capabilities{path}", json=body, headers={"X-Internal-Key": key}
            )
        except httpx.HTTPError as error:
            raise HTTPException(status_code=503, detail="The participant's adapter is unavailable") from error
        try:
            content = answer.json()
        except ValueError as error:
            raise HTTPException(status_code=503, detail="The participant's adapter gave an unusable answer") from error
        if answer.status_code in PASSED_ON:
            detail = content.get("detail", "Refused by the adapter") if isinstance(content, dict) else "Refused"
            raise HTTPException(status_code=answer.status_code, detail=detail)
        if answer.status_code == 401:
            raise HTTPException(status_code=502, detail="The participant's adapter refused the internal key")
        if answer.status_code >= 300:
            raise HTTPException(status_code=503, detail="The participant's adapter is unavailable")
        return answer.status_code, content

    async def state(self, record: dict) -> dict:
        _, content = await self.call(record, "GET", "")
        if not isinstance(content, dict) or "capabilities" not in content:
            raise HTTPException(status_code=503, detail="The participant's adapter gave an unusable answer")
        return content

    async def set_default(self, record: dict, capability: str, default_policy: str) -> object:
        path = f"/{quote(capability, safe=':')}"
        return (await self.call(record, "PATCH", path, {"default_policy": default_policy}))[1]

    async def record_decision(self, record: dict, body: dict) -> tuple[int, object]:
        return await self.call(record, "POST", "/approvals", body)

    async def change_decision(self, record: dict, approval_id: str, body: dict) -> object:
        return (await self.call(record, "PATCH", f"/approvals/{quote(approval_id, safe='')}", body))[1]


def policy_entries(provider: dict, consumer_id: str, state: dict) -> list[dict]:
    """One provider's capabilities, as seen for one consumer."""
    approvals = state.get("approvals", [])
    decisions = {entry["capability"]: entry for entry in approvals if entry["consumer_id"] == consumer_id}
    entries = []
    for capability in state["capabilities"]:
        decision = decisions.get(capability["capability"])
        entries.append(
            {
                **capability,
                "provider": provider["participant_id"],
                "consumer": consumer_id,
                "status": decision["status"] if decision else capability["default_policy"],
                "source": "explicit" if decision else "default",
                "approval_id": decision["id"] if decision else None,
                "decision_note": decision["decision_note"] if decision else None,
            }
        )
    return entries
