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

import asyncio
import json
import time

import httpx
import pytest

from app.connector import Connector, ConnectorError


def connector_with(handler) -> Connector:
    http = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    return Connector("http://edc.test/management", "the-key", http, poll_seconds=0)


def run(work):
    return asyncio.run(work)


def test_offer_creates_asset_policy_and_contract_with_the_key():
    calls = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append((request.url.path, request.headers["X-Api-Key"], json.loads(request.content)))
        return httpx.Response(200, json={"@id": "x"})

    run(connector_with(handler).offer("asset-1", "http://me/internal/payload/asset-1"))
    assert [call[0] for call in calls] == [
        "/management/v3/assets",
        "/management/v3/policydefinitions",
        "/management/v3/contractdefinitions",
    ]
    assert {call[1] for call in calls} == {"the-key"}
    assert calls[0][2]["dataAddress"]["baseUrl"] == "http://me/internal/payload/asset-1"
    assert calls[2][2]["accessPolicyId"] == "policy-asset-1"
    assert calls[2][2]["assetsSelector"][0]["operandRight"] == "asset-1"


def test_failure_is_a_connector_error():
    connector = connector_with(lambda _: httpx.Response(500, text="broken"))
    with pytest.raises(ConnectorError, match="500"):
        run(connector.offer("a", "http://x"))


@pytest.mark.parametrize(
    "dataset",
    [
        {"odrl:hasPolicy": {"@id": "offer-1"}},
        [{"odrl:hasPolicy": {"@id": "offer-1"}}],
        {"odrl:hasPolicy": [{"@id": "offer-1"}]},
    ],
)
def test_find_offer_handles_each_catalog_shape(dataset):
    connector = connector_with(lambda _: httpx.Response(200, json={"dcat:dataset": dataset}))
    assert run(connector.find_offer("a", "urn:p", "http://dsp")) == "offer-1"


def test_find_offer_with_empty_catalog():
    connector = connector_with(lambda _: httpx.Response(200, json={"dcat:dataset": []}))
    with pytest.raises(ConnectorError, match="doesn't offer"):
        run(connector.find_offer("a", "urn:p", "http://dsp"))


def test_negotiation_request_names_the_provider_and_asset():
    seen = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen.update(json.loads(request.content))
        return httpx.Response(200, json={"@id": "n1"})

    assert run(connector_with(handler).negotiate("offer-1", "a", "urn:p", "http://dsp")) == "n1"
    assert seen["counterPartyId"] == "urn:p"
    assert seen["policy"]["@id"] == "offer-1"
    assert seen["policy"]["assigner"] == "urn:p"
    assert seen["policy"]["target"] == "a"


def test_polling_continues_until_finalized():
    states = iter(["REQUESTING", "AGREED", "FINALIZED"])

    def handler(_: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"state": next(states), "contractAgreementId": "agreement"})

    assert run(connector_with(handler).wait_for_agreement("n1", time.monotonic() + 5)) == "agreement"


def test_terminated_negotiation_gives_the_reason():
    connector = connector_with(lambda _: httpx.Response(200, json={"state": "TERMINATED", "errorDetail": "refused"}))
    with pytest.raises(ConnectorError, match="refused"):
        run(connector.wait_for_agreement("n1", time.monotonic() + 5))


def test_polling_stops_at_the_deadline():
    connector = connector_with(lambda _: httpx.Response(200, json={"state": "REQUESTING"}))
    with pytest.raises(ConnectorError, match="in time"):
        run(connector.wait_for_agreement("n1", time.monotonic() - 1))


def test_push_requests_an_http_push_to_the_destination():
    seen = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen.update(json.loads(request.content))
        return httpx.Response(200, json={"@id": "t1"})

    assert run(connector_with(handler).push("agreement", "http://dsp", "http://me/in")) == "t1"
    assert seen["transferType"] == "HttpData-PUSH"
    assert seen["contractId"] == "agreement"
    assert seen["dataDestination"] == {"type": "HttpData", "baseUrl": "http://me/in"}


def test_transfer_waits_for_completed():
    states = iter(["STARTED", "COMPLETED"])
    connector = connector_with(lambda _: httpx.Response(200, json={"state": next(states)}))
    run(connector.wait_for_transfer("t1", time.monotonic() + 5))


def test_terminated_transfer_is_an_error():
    connector = connector_with(lambda _: httpx.Response(200, json={"state": "TERMINATED"}))
    with pytest.raises(ConnectorError, match="terminated"):
        run(connector.wait_for_transfer("t1", time.monotonic() + 5))
