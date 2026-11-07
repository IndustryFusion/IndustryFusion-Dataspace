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

"""Reading an external provider's capabilities as the other side of a pair would, through the gateway's peer route.

An external adapter answers its own capability state to a peer that presents that peer's own participant token, with
that peer's approvals only. This reads it with a token of the pair's consumer, for an administrator, and keeps nothing.
"""

import logging
from urllib.parse import quote

import httpx
from fastapi import HTTPException

from app.config import Settings
from app.keycloak import KeycloakAdmin
from app.tokens import fetch_admin_token

log = logging.getLogger("management.peers")

READ_SECONDS = 10


class Unreadable(Exception):
    """Why an external provider's capabilities couldn't be read. Never holds a secret, a token or an address."""


def _usable(content: object) -> dict | None:
    """The answer, if it has the shape of an adapter's capability state."""
    if not isinstance(content, dict):
        return None
    capabilities, approvals = content.get("capabilities"), content.get("approvals")
    if not isinstance(capabilities, list) or not isinstance(approvals, list):
        return None
    for entry in capabilities:
        if not isinstance(entry, dict) or not isinstance(entry.get("capability"), str):
            return None
        if not isinstance(entry.get("default_policy"), str):
            return None
    for entry in approvals:
        if not isinstance(entry, dict) or not all(
            isinstance(entry.get(key), str) for key in ("id", "consumer_id", "capability", "status")
        ):
            return None
    return content


class ExternalPolicies:
    def __init__(self, settings: Settings, http: httpx.AsyncClient) -> None:
        self.settings = settings
        self.http = http

    async def _consumer_token(self, consumer_id: str, keycloak: KeycloakAdmin) -> str:
        try:
            secret = await keycloak.owned_client_secret(consumer_id)
        except HTTPException as error:
            raise Unreadable("Keycloak did not give this service the other participant's credentials") from error
        if secret is None:
            raise Unreadable("The other participant of the pair has no client here, so it has no token to read with")
        try:
            answer = await fetch_admin_token(self.http, self.settings.issuer, consumer_id, secret)
        except HTTPException as error:
            raise Unreadable("Keycloak did not give a token for the other participant of the pair") from error
        token = answer.get("access_token") if isinstance(answer, dict) else None
        if not isinstance(token, str) or not token:
            raise Unreadable("Keycloak did not give a token for the other participant of the pair")
        return token

    async def state(self, provider_id: str, consumer_id: str, keycloak: KeycloakAdmin) -> dict:
        """The provider's capabilities, and the consumer's approvals among them."""
        if not self.settings.gateway_url:
            raise Unreadable("This service has no gateway address to read through")
        token = await self._consumer_token(consumer_id, keycloak)
        address = f"{self.settings.gateway_url}/peer/{quote(provider_id, safe=':')}/internal/capabilities"
        try:
            answer = await self.http.get(address, headers={"Authorization": f"Bearer {token}"}, timeout=READ_SECONDS)
        except httpx.HTTPError as error:
            log.warning("Reading %s's capabilities: %s", provider_id, type(error).__name__)
            raise Unreadable("The gateway could not be reached") from None
        if answer.status_code in (401, 403):
            raise Unreadable(f"The participant's adapter refused the other participant's token ({answer.status_code})")
        if answer.status_code == 404:
            raise Unreadable("The gateway or the participant's adapter did not find this participant")
        if answer.status_code in (502, 503, 504):
            raise Unreadable("The participant's adapter could not be reached through the gateway")
        if answer.status_code != 200:
            raise Unreadable(f"The participant's adapter answered {answer.status_code}")
        try:
            content = _usable(answer.json())
        except ValueError:
            content = None
        if content is None:
            raise Unreadable("The participant's adapter gave an answer that isn't a capability state")
        # Only what concerns this consumer, whatever the adapter sent.
        approvals = [entry for entry in content["approvals"] if entry["consumer_id"] == consumer_id]
        return {"capabilities": content["capabilities"], "approvals": approvals}
