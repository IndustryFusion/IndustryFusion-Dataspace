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

"""A participant's objects in Keycloak, reached with the calling administrator's token, or the service's own."""

from urllib.parse import quote

import httpx
from fastapi import HTTPException

OWNER_ATTRIBUTE = "dataspace.participant_id"
CLAIM = "participant_id"


def role_name(participant_id: str) -> str:
    return f"participant:{participant_id}"


def _claim_mapper(participant_id: str) -> dict:
    return {
        "name": CLAIM,
        "protocol": "openid-connect",
        "protocolMapper": "oidc-hardcoded-claim-mapper",
        "config": {
            "claim.name": CLAIM,
            "claim.value": participant_id,
            "jsonType.label": "String",
            "access.token.claim": "true",
            "id.token.claim": "false",
            "userinfo.token.claim": "false",
        },
    }


def _client_settings(participant_id: str) -> dict:
    return {
        "clientId": participant_id,
        "protocol": "openid-connect",
        "publicClient": False,
        "serviceAccountsEnabled": True,
        "standardFlowEnabled": False,
        "implicitFlowEnabled": False,
        "directAccessGrantsEnabled": False,
        "attributes": {OWNER_ATTRIBUTE: participant_id},
    }


class KeycloakAdmin:
    def __init__(self, http: httpx.AsyncClient, base_url: str, realm: str, token: str) -> None:
        self.http = http
        self.base = f"{base_url}/admin/realms/{realm}"
        self.use_token(token)

    def use_token(self, token: str) -> None:
        self.headers = {"Authorization": f"Bearer {token}"}

    async def _call(self, method: str, path: str, body: object = None, allow: tuple[int, ...] = ()) -> httpx.Response:
        try:
            answer = await self.http.request(method, f"{self.base}{path}", json=body, headers=self.headers)
        except httpx.HTTPError as error:
            raise HTTPException(status_code=502, detail="Keycloak is unavailable") from error
        if answer.status_code in (401, 403):
            raise HTTPException(status_code=403, detail="This token may not administer Keycloak")
        if answer.status_code >= 300 and answer.status_code not in allow:
            raise HTTPException(status_code=502, detail=f"Keycloak answered {answer.status_code} to {method}")
        return answer

    async def _client(self, participant_id: str) -> dict | None:
        answer = await self._call("GET", f"/clients?clientId={quote(participant_id, safe='')}")
        return next((client for client in answer.json() if client.get("clientId") == participant_id), None)

    @staticmethod
    def _is_owned(client: dict, participant_id: str) -> bool:
        return (client.get("attributes") or {}).get(OWNER_ATTRIBUTE) == participant_id

    async def _owned_client(self, participant_id: str) -> dict | None:
        client = await self._client(participant_id)
        return client if client and self._is_owned(client, participant_id) else None

    async def client_exists_unowned(self, participant_id: str) -> bool:
        client = await self._client(participant_id)
        return client is not None and not self._is_owned(client, participant_id)

    async def ensure_role(self, participant_id: str) -> tuple[dict, bool]:
        """Return the realm role, and whether this call made it."""
        path = f"/roles/{quote(role_name(participant_id), safe='')}"
        found = await self._call("GET", path, allow=(404,))
        if found.status_code != 404:
            return found.json(), False
        made = await self._call("POST", "/roles", {"name": role_name(participant_id)}, allow=(409,))
        return (await self._call("GET", path)).json(), made.status_code != 409

    async def ensure_client(self, participant_id: str) -> tuple[str, bool]:
        """Return the client's internal id, and whether this call made it. An unfinished one has its settings fixed."""
        client = await self._client(participant_id)
        if client is None:
            body = {**_client_settings(participant_id), "protocolMappers": [_claim_mapper(participant_id)]}
            made = await self._call("POST", "/clients", body, allow=(409,))
            client = await self._client(participant_id)
            if client is None:
                raise HTTPException(status_code=502, detail="Keycloak did not keep the new client")
            if made.status_code != 409:
                return client["id"], True
        if not self._is_owned(client, participant_id):
            raise HTTPException(status_code=409, detail="A client with this id exists, and isn't a participant's")
        wanted = _client_settings(participant_id)
        if any(client.get(key) != value for key, value in wanted.items() if key != "attributes"):
            client.update({key: value for key, value in wanted.items() if key != "attributes"})
            await self._call("PUT", f"/clients/{client['id']}", client)
        return client["id"], False

    async def ensure_claim_mapper(self, participant_id: str, client_uuid: str) -> None:
        path = f"/clients/{client_uuid}/protocol-mappers/models"
        wanted = _claim_mapper(participant_id)
        for mapper in (await self._call("GET", path)).json():
            if mapper.get("name") == CLAIM:
                if mapper.get("config", {}).get("claim.value") != participant_id:
                    await self._call("PUT", f"{path}/{mapper['id']}", {**wanted, "id": mapper["id"]})
                return
        await self._call("POST", path, wanted)

    async def ensure_role_assignment(self, client_uuid: str, role: dict) -> None:
        account = (await self._call("GET", f"/clients/{client_uuid}/service-account-user")).json()
        path = f"/users/{account['id']}/role-mappings/realm"
        held = (await self._call("GET", path)).json()
        if role["name"] not in {entry["name"] for entry in held}:
            await self._call("POST", path, [role])

    async def client_secret(self, client_uuid: str) -> str:
        return (await self._call("GET", f"/clients/{client_uuid}/client-secret")).json()["value"]

    async def owned_client_secret(self, participant_id: str) -> str | None:
        client = await self._owned_client(participant_id)
        return await self.client_secret(client["id"]) if client else None

    async def delete_client(self, client_uuid: str) -> None:
        await self._call("DELETE", f"/clients/{client_uuid}", allow=(404,))

    async def delete_role(self, participant_id: str) -> bool:
        answer = await self._call("DELETE", f"/roles/{quote(role_name(participant_id), safe='')}", allow=(404,))
        return answer.status_code != 404

    async def delete_owned_client(self, participant_id: str) -> bool:
        client = await self._owned_client(participant_id)
        if client is None:
            return False
        await self.delete_client(client["id"])
        return True
