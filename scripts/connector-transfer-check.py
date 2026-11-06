#!/usr/bin/env python3
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
"""Shows two connectors completing a negotiation and an HttpData-PUSH transfer.

Needs scripts/local-env.sh up, and the connector image built and loaded into the cluster
with scripts/local-env.sh services.
A small HTTP server stands in for the systems on each side.
"""

import secrets
import sys
import uuid

import local_cluster as lc

EDC = {"@vocab": "https://w3id.org/edc/v0.0.1/ns/"}
PROTOCOL = "dataspace-protocol-http"
PROVIDER, CONSUMER = "urn:check:provider", "urn:check:consumer"
PAYLOAD = '{"check": "connector transfer ' + uuid.uuid4().hex + '"}'
STAND_IN = """
import http.server
received = {}
class Handler(http.server.BaseHTTPRequestHandler):
    def _send(self, code, body=b""):
        self.send_response(code)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)
    def do_GET(self):
        if self.path == "/received":
            self._send(200, received.get("body", b""))
        else:
            self._send(200, open("/data/payload").read().encode())
    def do_POST(self):
        received["encoding"] = self.headers.get("Transfer-Encoding")
        if self.headers.get("Transfer-Encoding") == "chunked":
            body = b""
            while size := int(self.rfile.readline().strip(), 16):
                body += self.rfile.read(size)
                self.rfile.readline()
            self.rfile.readline()
            received["body"] = body
        else:
            received["body"] = self.rfile.read(int(self.headers.get("Content-Length") or 0))
        self._send(200)
http.server.ThreadingHTTPServer(("", 8000), Handler).serve_forever()
"""


def stand_in_manifest() -> str:
    indent = "\n".join("    " + line for line in STAND_IN.strip().splitlines())
    return f"""
apiVersion: v1
kind: ConfigMap
metadata: {{ name: connector-check-stand-in, namespace: {lc.PARTICIPANTS} }}
data:
  server.py: |
{indent}
  payload: '{PAYLOAD}'
---
apiVersion: apps/v1
kind: Deployment
metadata: {{ name: connector-check-stand-in, namespace: {lc.PARTICIPANTS} }}
spec:
  selector: {{ matchLabels: {{ app: connector-check-stand-in }} }}
  template:
    metadata: {{ labels: {{ app: connector-check-stand-in }} }}
    spec:
      containers:
        - name: server
          image: python:3.12-slim
          command: ["python", "/data/server.py"]
          readinessProbe: {{ tcpSocket: {{ port: 8000 }}, periodSeconds: 2 }}
          volumeMounts: [{{ name: data, mountPath: /data }}]
      volumes: [{{ name: data, configMap: {{ name: connector-check-stand-in }} }}]
---
apiVersion: v1
kind: Service
metadata: {{ name: connector-check-stand-in, namespace: {lc.PARTICIPANTS} }}
spec:
  selector: {{ app: connector-check-stand-in }}
  ports: [{{ port: 8000 }}]
"""


def main() -> int:
    key = secrets.token_hex(16)
    try:
        lc.apply(stand_in_manifest())
        provider_service = lc.deploy_connector(PROVIDER, key)
        consumer_service = lc.deploy_connector(CONSUMER, key)
        lc.wait_ready(lc.PARTICIPANTS, "connector-check-stand-in")
        lc.wait_ready(lc.PARTICIPANTS, provider_service)
        lc.wait_ready(lc.PARTICIPANTS, consumer_service)
        return run(provider_service, consumer_service, key)
    finally:
        lc.kubectl(
            "-n", lc.PARTICIPANTS, "delete", "deploy,svc,configmap", "connector-check-stand-in", "--ignore-not-found"
        )
        lc.remove_connector(PROVIDER)
        lc.remove_connector(CONSUMER)


def run(provider_service: str, consumer_service: str, key: str) -> int:
    stand_in = f"http://connector-check-stand-in.{lc.PARTICIPANTS}:8000"
    provider_dsp = f"http://{provider_service}.{lc.PARTICIPANTS}:8082/api/v1/dsp"
    headers = {"X-Api-Key": key}
    asset = f"check-{uuid.uuid4().hex}"

    with (
        lc.port_forward(lc.PARTICIPANTS, provider_service, 8081) as provider,
        lc.port_forward(lc.PARTICIPANTS, consumer_service, 8081) as consumer,
        lc.port_forward(lc.PARTICIPANTS, "connector-check-stand-in", 8000) as server,
    ):
        for base in (provider, consumer):
            query = {"@context": EDC, "@type": "QuerySpec"}
            lc.poll(
                lambda b=base: lc.http("POST", f"{b}/management/v3/assets/request", query, headers)[0] == 200,
                what="management API",
            )

        status, _ = lc.http("POST", f"{provider}/management/v3/assets/request", {"@context": EDC, "@type": "QuerySpec"})
        print(f"Management API with no key: {status}")
        assert status == 401

        def create(path: str, body: dict) -> None:
            status, answer = lc.http("POST", f"{provider}/management/v3/{path}", body, headers)
            assert status == 200, (path, status, answer)

        create(
            "assets",
            {
                "@context": EDC,
                "@id": asset,
                "properties": {"name": asset},
                "dataAddress": {"type": "HttpData", "baseUrl": f"{stand_in}/payload"},
            },
        )
        create(
            "policydefinitions",
            {
                "@context": EDC,
                "@id": f"policy-{asset}",
                "policy": {"@context": "http://www.w3.org/ns/odrl.jsonld", "@type": "Set", "permission": []},
            },
        )
        create(
            "contractdefinitions",
            {
                "@context": EDC,
                "@id": f"contract-{asset}",
                "accessPolicyId": f"policy-{asset}",
                "contractPolicyId": f"policy-{asset}",
                "assetsSelector": [
                    {
                        "@type": "Criterion",
                        "operandLeft": "https://w3id.org/edc/v0.0.1/ns/id",
                        "operator": "=",
                        "operandRight": asset,
                    }
                ],
            },
        )

        status, catalog = lc.http(
            "POST",
            f"{consumer}/management/v3/catalog/request",
            {
                "@context": EDC,
                "counterPartyAddress": provider_dsp,
                "counterPartyId": PROVIDER,
                "protocol": PROTOCOL,
                "querySpec": {
                    "filterExpression": [
                        {
                            "operandLeft": "https://w3id.org/edc/v0.0.1/ns/id",
                            "operator": "=",
                            "operandRight": asset,
                        }
                    ]
                },
            },
            headers,
        )
        assert status == 200, (status, catalog)
        offer = catalog["dcat:dataset"]["odrl:hasPolicy"]["@id"]
        print(f"Catalog offers the asset. Endpoint: {catalog['dcat:service']['dcat:endpointUrl']}")
        assert ":8083" not in str(catalog)

        status, negotiation = lc.http(
            "POST",
            f"{consumer}/management/v3/contractnegotiations",
            {
                "@context": EDC,
                "counterPartyAddress": provider_dsp,
                "counterPartyId": PROVIDER,
                "protocol": PROTOCOL,
                "policy": {
                    "@context": "http://www.w3.org/ns/odrl.jsonld",
                    "@type": "Offer",
                    "@id": offer,
                    "assigner": PROVIDER,
                    "target": asset,
                },
            },
            headers,
        )
        assert status == 200, (status, negotiation)

        def negotiated():
            address = f"{consumer}/management/v3/contractnegotiations/{negotiation['@id']}"
            _, answer = lc.http("GET", address, headers=headers)
            assert answer["state"] != "TERMINATED", answer
            return answer if answer["state"] == "FINALIZED" else None

        agreement = lc.poll(negotiated, what="negotiation")["contractAgreementId"]
        print("Negotiation finalized")

        status, transfer = lc.http(
            "POST",
            f"{consumer}/management/v3/transferprocesses",
            {
                "@context": EDC,
                "counterPartyAddress": provider_dsp,
                "contractId": agreement,
                "protocol": PROTOCOL,
                "transferType": "HttpData-PUSH",
                "dataDestination": {"type": "HttpData", "baseUrl": f"{stand_in}/sink"},
            },
            headers,
        )
        assert status == 200, (status, transfer)

        def transferred():
            _, answer = lc.http("GET", f"{consumer}/management/v3/transferprocesses/{transfer['@id']}", headers=headers)
            assert answer["state"] != "TERMINATED", answer
            return answer["state"] == "COMPLETED"

        lc.poll(transferred, what="transfer")
        status, received = lc.http("GET", f"{server}/received", raw=True)
        assert received.decode() == PAYLOAD, received
        print(f"Transfer completed, and the same {len(received)} bytes arrived")

    lc.kubectl("-n", lc.PARTICIPANTS, "rollout", "restart", f"deploy/{provider_service}")
    lc.wait_ready(lc.PARTICIPANTS, provider_service)
    with lc.port_forward(lc.PARTICIPANTS, provider_service, 8081) as provider:
        def asset_there():
            status, answer = lc.http("GET", f"{provider}/management/v3/assets/{asset}", headers=headers)
            return status == 200 and answer["@id"] == asset

        lc.poll(asset_there, what="asset after restart")
    print("The asset is still there after a restart")
    print("PASS")
    return 0


if __name__ == "__main__":
    sys.exit(main())
