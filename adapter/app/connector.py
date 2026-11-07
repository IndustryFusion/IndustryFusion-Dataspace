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

"""The connector's management API."""

import asyncio
import time

import httpx

EDC_CONTEXT = {"@vocab": "https://w3id.org/edc/v0.0.1/ns/"}
ODRL_CONTEXT = "http://www.w3.org/ns/odrl.jsonld"
PROTOCOL = "dataspace-protocol-http"
ID_PROPERTY = "https://w3id.org/edc/v0.0.1/ns/id"
POLL_SECONDS = 0.5


class ConnectorError(Exception):
    pass


class Connector:
    def __init__(self, base_url: str, api_key: str, http: httpx.AsyncClient, poll_seconds: float = POLL_SECONDS):
        self.base = f"{base_url}/v3"
        self.headers = {"X-Api-Key": api_key}
        self.http = http
        self.poll_seconds = poll_seconds

    async def _post(self, path: str, body: dict) -> dict:
        response = await self.http.post(f"{self.base}/{path}", json=body, headers=self.headers)
        if response.status_code >= 300:
            raise ConnectorError(f"POST {path} gave {response.status_code}: {response.text[:300]}")
        return response.json()

    async def _get(self, path: str) -> dict:
        response = await self.http.get(f"{self.base}/{path}", headers=self.headers)
        if response.status_code >= 300:
            raise ConnectorError(f"GET {path} gave {response.status_code}: {response.text[:300]}")
        return response.json()

    async def offer(self, asset_id: str, source_url: str) -> None:
        """Offer an HTTP source to other participants, with its own permit-all policy and contract."""
        policy_id = f"policy-{asset_id}"
        await self._post(
            "assets",
            {
                "@context": EDC_CONTEXT,
                "@id": asset_id,
                "properties": {"name": asset_id},
                "dataAddress": {"type": "HttpData", "baseUrl": source_url},
            },
        )
        await self._post(
            "policydefinitions",
            {
                "@context": EDC_CONTEXT,
                "@id": policy_id,
                "policy": {"@context": ODRL_CONTEXT, "@type": "Set", "permission": []},
            },
        )
        await self._post(
            "contractdefinitions",
            {
                "@context": EDC_CONTEXT,
                "@id": f"contract-{asset_id}",
                "accessPolicyId": policy_id,
                "contractPolicyId": policy_id,
                "assetsSelector": [
                    {"@type": "Criterion", "operandLeft": ID_PROPERTY, "operator": "=", "operandRight": asset_id}
                ],
            },
        )

    async def find_offer(self, asset_id: str, provider_id: str, provider_dsp: str) -> str:
        catalog = await self._post(
            "catalog/request",
            {
                "@context": EDC_CONTEXT,
                "counterPartyAddress": provider_dsp,
                "counterPartyId": provider_id,
                "protocol": PROTOCOL,
                "querySpec": {
                    "filterExpression": [{"operandLeft": ID_PROPERTY, "operator": "=", "operandRight": asset_id}]
                },
            },
        )
        datasets = catalog.get("dcat:dataset") or []
        datasets = datasets if isinstance(datasets, list) else [datasets]
        for dataset in datasets:
            policy = dataset.get("odrl:hasPolicy")
            policy = policy[0] if isinstance(policy, list) else policy
            if policy:
                return policy["@id"]
        raise ConnectorError(f"The provider's catalog doesn't offer {asset_id}")

    async def negotiate(self, offer_id: str, asset_id: str, provider_id: str, provider_dsp: str) -> str:
        answer = await self._post(
            "contractnegotiations",
            {
                "@context": EDC_CONTEXT,
                "counterPartyAddress": provider_dsp,
                "counterPartyId": provider_id,
                "protocol": PROTOCOL,
                "policy": {
                    "@context": ODRL_CONTEXT,
                    "@type": "Offer",
                    "@id": offer_id,
                    "assigner": provider_id,
                    "target": asset_id,
                },
            },
        )
        return answer["@id"]

    async def _wait(self, path: str, done: str, deadline: float, what: str) -> dict:
        while True:
            answer = await self._get(path)
            state = answer.get("state")
            if state == done:
                return answer
            if state == "TERMINATED":
                reason = answer.get("errorDetail", "no reason given")
                raise ConnectorError(f"{what} was terminated: {reason}")
            if time.monotonic() >= deadline:
                raise ConnectorError(f"{what} did not finish in time. Last state: {state}")
            await asyncio.sleep(self.poll_seconds)

    async def wait_for_agreement(self, negotiation_id: str, deadline: float) -> str:
        answer = await self._wait(f"contractnegotiations/{negotiation_id}", "FINALIZED", deadline, "The negotiation")
        return answer["contractAgreementId"]

    async def push(self, agreement_id: str, provider_dsp: str, destination_url: str, header: tuple[str, str]) -> str:
        answer = await self._post(
            "transferprocesses",
            {
                "@context": EDC_CONTEXT,
                "counterPartyAddress": provider_dsp,
                "contractId": agreement_id,
                "protocol": PROTOCOL,
                "transferType": "HttpData-PUSH",
                "dataDestination": {
                    "type": "HttpData",
                    "baseUrl": destination_url,
                    "authKey": header[0],
                    "authCode": header[1],
                },
            },
        )
        return answer["@id"]

    async def wait_for_transfer(self, transfer_id: str, deadline: float) -> None:
        await self._wait(f"transferprocesses/{transfer_id}", "COMPLETED", deadline, "The transfer")

    async def transfer_for_asset(self, asset_id: str) -> str | None:
        """This connector's transfer process for an asset, if it has one."""
        answer = await self._post(
            "transferprocesses/request",
            {
                "@context": EDC_CONTEXT,
                "@type": "QuerySpec",
                "filterExpression": [{"operandLeft": "assetId", "operator": "=", "operandRight": asset_id}],
            },
        )
        return answer[0]["@id"] if answer else None

