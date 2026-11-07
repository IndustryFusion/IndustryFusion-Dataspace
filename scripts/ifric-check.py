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
"""Checks company details on the local cluster, with real Keycloak tokens and a stand-in for the IFRIC registry.

The stand-in accepts only a token from the reader client. Goes through: not configured, available, a change after
the cache time, unavailable, and available again. It removes what it adds. Needs scripts/local-env.sh up and services.
"""

import json
import sys
import textwrap
import time

import local_cluster as lc

KNOWN, OTHER = "urn:ifric-check:company", "urn:ifric-check:other"
READER = "dataspace-ifric-reader"
NAMESPACE = "dataspace"
STAND_IN = "ifric-standin"
CACHE_SECONDS = 3
DETAILS = {"company_name": "Check Machines", "company_category": "machine_builder", "city": "Pune", "country": "India"}

SERVER = """
import base64, http.server, json
COMPANIES = [{"company_ifric_id": "@KNOWN@", "company_name": "Check Machines", "company_category": "machine_builder",
              "company_city": "Pune", "company_country": "India", "company_address": "not shown"}]
class Handler(http.server.BaseHTTPRequestHandler):
    def do_GET(self):
        status, body = 401, {"message": "wrong token"}
        try:
            payload = self.headers["Authorization"].split(" ")[1].split(".")[1]
            claims = json.loads(base64.urlsafe_b64decode(payload + "=" * (-len(payload) % 4)))
            if claims["azp"] == "@READER@" and self.path == "/company/get-all-companies":
                status, body = 200, COMPANIES
        except Exception:
            pass
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        self.wfile.write(json.dumps(body).encode())
http.server.ThreadingHTTPServer(("", 8080), Handler).serve_forever()
""".replace("@KNOWN@", KNOWN).replace("@READER@", READER)


def deploy_stand_in() -> None:
    manifest = {
        "apiVersion": "apps/v1",
        "kind": "Deployment",
        "metadata": {"name": STAND_IN, "namespace": NAMESPACE},
        "spec": {
            "selector": {"matchLabels": {"app": STAND_IN}},
            "template": {
                "metadata": {"labels": {"app": STAND_IN}},
                "spec": {
                    "containers": [
                        {
                            "name": "server",
                            "image": "python:3.12-slim",
                            "imagePullPolicy": "IfNotPresent",
                            "command": ["python", "-c", textwrap.dedent(SERVER)],
                            "readinessProbe": {"tcpSocket": {"port": 8080}, "periodSeconds": 1},
                        }
                    ]
                },
            },
        },
    }
    service = {
        "apiVersion": "v1",
        "kind": "Service",
        "metadata": {"name": STAND_IN, "namespace": NAMESPACE},
        "spec": {"selector": {"app": STAND_IN}, "ports": [{"port": 8080}]},
    }
    lc.apply(json.dumps(manifest))
    lc.apply(json.dumps(service))
    lc.wait_ready(NAMESPACE, STAND_IN)


def scale_stand_in(replicas: int) -> None:
    lc.kubectl("-n", NAMESPACE, "scale", f"deploy/{STAND_IN}", f"--replicas={replicas}")
    if replicas:
        lc.wait_ready(NAMESPACE, STAND_IN)
    else:
        pods = ("-n", NAMESPACE, "get", "pods", "-l", f"app={STAND_IN}", "-o", "name")
        lc.poll(lambda: not lc.kubectl(*pods).strip(), 60, what="the stand-in to stop")


def set_management(*assignments: str) -> None:
    lc.kubectl("-n", NAMESPACE, "set", "env", "deploy/management", *assignments)
    lc.wait_ready(NAMESPACE, "management")


def reader_secret(keycloak: str) -> str:
    admin = lc.KeycloakAdmin(keycloak)
    if not admin.client_uuid(READER):
        status, answer = admin._call(
            "POST", "/clients", {"clientId": READER, "publicClient": False, "serviceAccountsEnabled": True}
        )
        assert status == 201, answer
    _, secret = admin._call("GET", f"/clients/{admin.client_uuid(READER)}/client-secret")
    return secret["value"]


def expect_details(base: str, participant: str, wanted: bool, what: str) -> None:
    status, record = lc.http("GET", f"{base}/api/participants/{participant}")
    assert status == 200, record
    has = {key: record[key] for key in DETAILS if key in record}
    assert has == (DETAILS if wanted else {}), (what, record)
    print(f"PASS {what}")


def main() -> int:
    secret = (lc.LOCAL / "admin-client-secret").read_text().strip()
    with lc.port_forward("iff", "keycloak-service", 8080) as forwarded:
        keycloak = f"{forwarded}/auth"
        reader = reader_secret(keycloak)
    deploy_stand_in()
    try:
        with lc.port_forward(NAMESPACE, "management", 3000) as base:
            status, token = lc.http(
                "POST", f"{base}/api/admin/token", {"client_id": "dataspace-admin-cli", "client_secret": secret}
            )
            assert status == 200, token
            admin = {"Authorization": f"Bearer {token['access_token']}"}
            for participant, kind in ((KNOWN, "machine_builder"), (OTHER, "factory_owner")):
                body = {
                    "participant_id": participant,
                    "participant_type": kind,
                    "hosted": False,
                    "adapter_url": "http://nowhere.invalid:8000",
                    "dsp_url": "http://nowhere.invalid:8082/api/v1/dsp",
                }
                status, answer = lc.http("POST", f"{base}/api/participants", body, admin)
                assert status == 200, answer
            expect_details(base, KNOWN, False, "not configured: no details, and the read works")

        set_management(
            f"IFRIC_BACKEND_URL=http://{STAND_IN}.{NAMESPACE}:8080",
            f"IFRIC_READER_CLIENT_ID={READER}",
            f"IFRIC_READER_CLIENT_SECRET={reader}",
            f"IFRIC_LOOKUP_CACHE_SECONDS={CACHE_SECONDS}",
        )
        with lc.port_forward(NAMESPACE, "management", 3000) as base:
            expect_details(base, KNOWN, True, "available: details on a known company, through a real reader token")
            expect_details(base, OTHER, False, "available: none on a participant it doesn't know")
            status, listed = lc.http("GET", f"{base}/api/participants")
            known = next(entry for entry in listed if entry["participant_id"] == KNOWN)
            assert known["company_name"] == DETAILS["company_name"], known
            status, compatible = lc.http("GET", f"{base}/api/participants/compatible/{OTHER}")
            assert compatible[0]["city"] == DETAILS["city"], compatible
            print("PASS the list and the compatible read have them too")

            scale_stand_in(0)
            time.sleep(CACHE_SECONDS + 1)
            expect_details(base, KNOWN, False, "unavailable: details left out, and the read works")
            status, health = lc.http("GET", f"{base}/api/health")
            assert status == 200, health
            scale_stand_in(1)
            time.sleep(CACHE_SECONDS + 1)
            expect_details(base, KNOWN, True, "available again: details are back")

        set_management("IFRIC_READER_CLIENT_SECRET=wrong")
        with lc.port_forward(NAMESPACE, "management", 3000) as base:
            expect_details(base, KNOWN, False, "a refused reader token: details left out, and the read works")
            logs = lc.kubectl("-n", NAMESPACE, "logs", "deploy/management", "--tail=200")
            assert "wrong" not in logs.replace("wrong token", ""), "A secret reached the log"
            print("PASS the secret isn't in the log")
    finally:
        set_management(
            "IFRIC_BACKEND_URL-",
            "IFRIC_READER_CLIENT_ID-",
            "IFRIC_READER_CLIENT_SECRET-",
            "IFRIC_LOOKUP_CACHE_SECONDS-",
        )
        with lc.port_forward(NAMESPACE, "management", 3000) as base:
            status, token = lc.http(
                "POST", f"{base}/api/admin/token", {"client_id": "dataspace-admin-cli", "client_secret": secret}
            )
            admin = {"Authorization": f"Bearer {token['access_token']}"}
            for participant in (KNOWN, OTHER):
                lc.http("DELETE", f"{base}/api/participants/{participant}", None, admin)
        lc.kubectl("-n", NAMESPACE, "delete", "deployment,service", STAND_IN, "--ignore-not-found")
    print("All company detail checks passed")
    return 0


if __name__ == "__main__":
    sys.exit(main())
