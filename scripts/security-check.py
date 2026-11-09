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
"""Negative tests of what protects participants from each other, from real pods on the local environment.

Registers three participants through the management API, and removes them. Each check says what was tried, and from
where. It needs scripts/local-env.sh up and services. It exits with 0 only if everything was refused that should be,
with 1 if something failed, and with 2 if nothing failed but a known gap is still open, which isn't a pass.
"""

import base64
import json
import sys
import textwrap
import time
import urllib.parse
import uuid

import local_cluster as lc

TAG = uuid.uuid4().hex[:8]
OWNER, OTHER_OWNER, BUILDER = (f"urn:security:{TAG}:{name}" for name in ("owner", "other-owner", "builder"))
OUTSIDE = f"security-check-{TAG}"
NS = lc.PARTICIPANTS
failures = 0
known_gaps: list[str] = []


def result(what: str, passed: bool, detail: object = "") -> None:
    global failures
    failures += not passed
    print(f"{'PASS' if passed else 'FAIL'} {what}{f': {detail}' if detail and not passed else ''}")


def known_gap(what: str, still_open: bool, detail: object = "") -> None:
    """Something documented as not closed. While open it isn't a pass, and once closed the document is wrong."""
    if still_open:
        known_gaps.append(what)
        print(f"KNOWN GAP {what}: {detail}")
    else:
        print(f"PASS {what}. It was a known gap, so correct design.md and helm/README.md")


def in_pod(namespace: str, deployment: str, code: str) -> str:
    """Run Python in a pod that has it, and return what it printed."""
    return lc.kubectl("-n", namespace, "exec", f"deploy/{deployment}", "--", "python", "-c", textwrap.dedent(code))


def http_from(namespace: str, deployment: str, method: str, url: str, headers: dict | None = None, body: bytes = b""):
    """A call from that pod, with what it holds and nothing more. Return its status and body."""
    code = f"""
        import httpx, json
        answer = httpx.request({method!r}, {url!r}, headers={headers or {}!r}, content={body!r}, timeout=20)
        print(json.dumps([answer.status_code, answer.text[:2000]]))
    """
    return json.loads(in_pod(namespace, deployment, code))


def port_open(namespace: str, deployment: str, host: str, port: int) -> bool:
    code = f"""
        import socket
        s = socket.socket(); s.settimeout(4)
        print(s.connect_ex(({host!r}, {port})) == 0)
    """
    return in_pod(namespace, deployment, code).strip() == "True"


def connector_port_open(namespace: str, deployment: str, host: str, port: int) -> bool:
    """A connector's image has no Python."""
    code = f"timeout 4 bash -c 'exec 3<>/dev/tcp/{host}/{port}' && echo open || echo closed"
    return lc.kubectl("-n", namespace, "exec", f"deploy/{deployment}", "--", "bash", "-c", code).strip() == "open"


def credentials_of(participant: str) -> dict[str, str]:
    name = f"participant-{lc.slug(participant)}"
    data = json.loads(lc.kubectl("-n", NS, "get", "secret", name, "-o", "json"))["data"]
    return {key: base64.b64decode(value).decode() for key, value in data.items()}


def adapter(participant: str) -> str:
    return f"adapter-{lc.slug(participant)}"


def adapter_url(participant: str) -> str:
    return f"http://{adapter(participant)}.{NS}:8000"


def connector_host(participant: str) -> str:
    return f"connector-{lc.slug(participant)}.{NS}"


def check_internal_routes(message_id: str) -> None:
    print("\n--- Internal routes, from a pod with no credentials for them")
    answer = http_from(NS, adapter(BUILDER), "GET", f"{adapter_url(OWNER)}/internal/payload/{message_id}")
    result("Reading another participant's payload: 401", answer[0] == 401, answer)
    result("Nothing of it comes back", "secret-payload" not in answer[1], answer)
    answer = http_from(
        NS, adapter(BUILDER), "POST", f"{adapter_url(OWNER)}/internal/inbox-receive/{message_id}", body=b'{"x": 1}'
    )
    result("Injecting a message: 401", answer[0] == 401, answer)
    answer = http_from(
        NS,
        adapter(BUILDER),
        "POST",
        f"{adapter_url(OWNER)}/internal/inbox-receive/{message_id}",
        {"X-Transfer-Token": "a guess"},
        b'{"x": 1}',
    )
    result("Injecting with a guessed token: 401", answer[0] == 401, answer)
    answer = http_from(
        NS,
        adapter(BUILDER),
        "GET",
        f"http://gateway.dataspace:8080/peer/{urllib.parse.quote(OWNER, safe=':')}/internal/payload/{message_id}",
    )
    result("Reading a payload through the gateway: not served", answer[0] in (401, 404), answer)


def check_network(probe: str) -> None:
    print(f"\n--- NetworkPolicies, from a pod in namespace {OUTSIDE}")
    for host, port, what in (
        (f"{adapter(OWNER)}.{NS}", 8000, "an adapter"),
        (connector_host(OWNER), 8082, "a connector's DSP port"),
        (connector_host(OWNER), 8081, "a connector's management port"),
        (connector_host(OWNER), 8083, "a connector's control port"),
        ("registry.dataspace", 19000, "the registry"),
        ("seaweedfs.iff", 8111, "the storage's IAM API"),
        ("seaweedfs.iff", 8888, "the storage's filer"),
    ):
        result(f"Reaching {what}: closed", not port_open(OUTSIDE, probe, host, port))
    result("The public gateway stays open", port_open(OUTSIDE, probe, "gateway.dataspace", 8080))

    print("\n--- NetworkPolicies, between the hub's own components")
    connector = f"connector-{lc.slug(BUILDER)}"
    result("A connector reaches another's DSP port", connector_port_open(NS, connector, connector_host(OWNER), 8082))
    result(
        "A connector can't reach another's management port",
        not connector_port_open(NS, connector, connector_host(OWNER), 8081),
    )
    result(
        "An adapter reaches a connector's management port", port_open(NS, adapter(OWNER), connector_host(OWNER), 8081)
    )
    result("The DSP gateway reaches a DSP port", port_open("dataspace", "dsp-gateway", connector_host(OWNER), 8082))
    result(
        "The DSP gateway can't reach a management port",
        not port_open("dataspace", "dsp-gateway", connector_host(OWNER), 8081),
    )
    result(
        "The DSP gateway can't reach a control port",
        not port_open("dataspace", "dsp-gateway", connector_host(OWNER), 8083),
    )
    result(
        "The DSP gateway can't reach the registry",
        not port_open("dataspace", "dsp-gateway", "registry.dataspace", 19000),
    )
    result("An adapter reaches the registry", port_open(NS, adapter(OWNER), "registry.dataspace", 19000))
    result("An adapter can't reach the storage's IAM API", not port_open(NS, adapter(OWNER), "seaweedfs.iff", 8111))


def check_credentials() -> None:
    print("\n--- Credentials, with one participant's real ones")
    mine, theirs = credentials_of(OWNER), credentials_of(BUILDER)
    for key in ("db-user", "db-password", "internal-key", "s3-access-key", "s3-secret-key", "edc-api-key"):
        result(f"{key} differs between participants", mine[key] != theirs[key])

    host = "acid-cluster.iff"
    code = f"""
        import asyncio, asyncpg
        async def tryit(database):
            try:
                connection = await asyncpg.connect(host={host!r}, user={mine["db-user"]!r},
                                                   password={mine["db-password"]!r}, database=database, timeout=10)
                await connection.close()
                return "connected"
            except Exception as error:
                return type(error).__name__
        own, other = "{lc.slug(OWNER)}", "{lc.slug(BUILDER)}"
        for name in (f"adapter_{{own}}", f"edc_{{own}}", f"adapter_{{other}}", f"edc_{{other}}"):
            print(asyncio.run(tryit(name)))
    """
    own_adapter, own_edc, other_adapter, other_edc = in_pod(NS, adapter(OWNER), code).split()
    result("Its own databases open", (own_adapter, own_edc) == ("connected", "connected"), (own_adapter, own_edc))
    result("Another's adapter database is refused", other_adapter != "connected", other_adapter)
    result("Another's connector database is refused", other_edc != "connected", other_edc)

    own_bucket, other_bucket = f"participant-{lc.slug(OWNER)}", f"participant-{lc.slug(BUILDER)}"
    code = f"""
        import boto3
        from botocore.config import Config
        client = boto3.client("s3", endpoint_url="http://seaweedfs.iff:80", aws_access_key_id={mine["s3-access-key"]!r},
                              aws_secret_access_key={mine["s3-secret-key"]!r}, region_name="us-east-1",
                              config=Config(s3={{"addressing_style": "path"}}, signature_version="s3v4",
                                            retries={{"max_attempts": 1}}))
        def tryit(action):
            try:
                action()
                return "allowed"
            except Exception as error:
                return "refused"
        print(tryit(lambda: client.put_object(Bucket={own_bucket!r}, Key="security-check", Body=b"mine")))
        print(tryit(lambda: client.get_object(Bucket={own_bucket!r}, Key="security-check")))
        print(tryit(lambda: client.delete_object(Bucket={own_bucket!r}, Key="security-check")))
        print(tryit(lambda: client.list_objects_v2(Bucket={other_bucket!r})))
        print(tryit(lambda: client.put_object(Bucket={other_bucket!r}, Key="security-check", Body=b"not mine")))
        print(tryit(lambda: client.get_object(Bucket={other_bucket!r}, Key="messages/anything")))
        print(tryit(lambda: client.create_bucket(Bucket="security-check-{TAG}")))
    """
    answers = in_pod(NS, adapter(OWNER), code).split()
    result("Its own bucket: put, get and delete", answers[:3] == ["allowed"] * 3, answers)
    result("Another's bucket: list is refused", answers[3] == "refused", answers)
    result("Another's bucket: put is refused", answers[4] == "refused", answers)
    result("Another's bucket: get is refused", answers[5] == "refused", answers)
    result("A new bucket is refused", answers[6] == "refused", answers)

    check_copy_from_another(mine, theirs, own_bucket, other_bucket)

    route = "/internal/capabilities"
    own = http_from(NS, adapter(OWNER), "GET", f"{adapter_url(OWNER)}{route}", {"X-Internal-Key": mine["internal-key"]})
    result("Its own internal key is taken", own[0] == 200, own)
    other = http_from(
        NS, adapter(OWNER), "GET", f"{adapter_url(BUILDER)}{route}", {"X-Internal-Key": mine["internal-key"]}
    )
    result("Its internal key is refused by another's adapter", other[0] == 401, other)


def check_copy_from_another(mine: dict, theirs: dict, own_bucket: str, other_bucket: str) -> None:
    """With one participant's keys, take an object out of another's bucket, without reading that bucket directly."""
    code = f"""
        import boto3, json
        from botocore.config import Config

        def client(access, secret):
            return boto3.client("s3", endpoint_url="http://seaweedfs.iff:80", aws_access_key_id=access,
                                aws_secret_access_key=secret, region_name="us-east-1",
                                config=Config(s3={{"addressing_style": "path"}}, signature_version="s3v4",
                                              retries={{"max_attempts": 1}}))

        holder, taker = client({theirs["s3-access-key"]!r}, {theirs["s3-secret-key"]!r}), client(
            {mine["s3-access-key"]!r}, {mine["s3-secret-key"]!r})
        source = {{"Bucket": {other_bucket!r}, "Key": "security-check-copy"}}
        holder.put_object(Body=b"the other participant's bytes", **source)

        def attempt(action):
            try:
                return action()
            except Exception as error:
                return "refused: " + type(error).__name__

        def by_copy():
            taker.copy_object(Bucket={own_bucket!r}, Key="copied", CopySource=source)
            return taker.get_object(Bucket={own_bucket!r}, Key="copied")["Body"].read().decode()

        def by_part():
            started = taker.create_multipart_upload(Bucket={own_bucket!r}, Key="copied-part")
            part = taker.upload_part_copy(Bucket={own_bucket!r}, Key="copied-part", UploadId=started["UploadId"],
                                           PartNumber=1, CopySource=source)
            taker.complete_multipart_upload(
                Bucket={own_bucket!r}, Key="copied-part", UploadId=started["UploadId"],
                MultipartUpload={{"Parts": [{{"PartNumber": 1, "ETag": part["CopyPartResult"]["ETag"]}}]}})
            return taker.get_object(Bucket={own_bucket!r}, Key="copied-part")["Body"].read().decode()

        answers = {{
            "direct": attempt(lambda: taker.get_object(**source)["Body"].read().decode()),
            "copy": attempt(by_copy),
            "part": attempt(by_part),
        }}
        taker.delete_object(Bucket={own_bucket!r}, Key="copied")
        taker.delete_object(Bucket={own_bucket!r}, Key="copied-part")
        holder.delete_object(**source)
        print(json.dumps(answers))
    """
    answers = json.loads(in_pod(NS, adapter(OWNER), code))
    bytes_wanted = "the other participant's bytes"
    result("Another's object: a direct read is refused", answers["direct"].startswith("refused"), answers["direct"])
    for name, what in (("copy", "CopyObject"), ("part", "UploadPartCopy")):
        known_gap(
            f"Another's object copied into its own bucket, with {what}, and read there",
            answers[name] == bytes_wanted,
            "the storage only checks a copy against its destination. See design.md and helm/README.md",
        )


def connector_negotiations(participant: str, provider_dsp: str, provider_id: str) -> list[dict]:
    """A participant's negotiations with this address and counterparty, from its connector's management API."""
    held = credentials_of(participant)
    code = f"""
        import httpx, json
        answer = httpx.post(
            "http://{connector_host(participant)}:8081/management/v3/contractnegotiations/request",
            headers={{"X-Api-Key": {held["edc-api-key"]!r}}},
            json={{"@context": {{"@vocab": "https://w3id.org/edc/v0.0.1/ns/"}}, "@type": "QuerySpec", "limit": 1000}},
            timeout=20,
        )
        answer.raise_for_status()
        print(json.dumps(answer.json()))
    """
    found = json.loads(in_pod(NS, adapter(participant), code))
    return [
        {key: item.get(key) for key in ("state", "contractAgreementId", "errorDetail")}
        for item in found
        if item.get("counterPartyAddress") == provider_dsp and item.get("counterPartyId") == provider_id
    ]


def forged_token(keycloak_realm: str) -> str:
    """A token with the right claims, signed by a key Keycloak doesn't have."""
    code = f"""
        import jwt, time
        from cryptography.hazmat.primitives.asymmetric import rsa
        key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
        print(jwt.encode({{"iss": {keycloak_realm!r}, "exp": int(time.time()) + 300, "participant_id": {OWNER!r},
                          "realm_access": {{"roles": ["participant:{OWNER}"]}}}}, key, algorithm="RS256",
                         headers={{"kid": "forged"}}))
    """
    return in_pod(NS, adapter(OWNER), code).strip()


def check_connector_identity(admin_token: str, owner_secret: str, management: str, tokens: dict[str, str]) -> None:
    print("\n--- Connector identity, on a real connector's DSP port")
    target = f"http://{connector_host(BUILDER)}:8082/api/v1/dsp/catalog/request"
    body = json.dumps(
        {
            "@context": {"dspace": "https://w3id.org/dspace/v0.8/"},
            "@type": "dspace:CatalogRequestMessage",
            "dspace:filter": {},
        }
    ).encode()
    issuer = "http://keycloak-service.iff:8080/auth/realms/dataspace"
    kinds = {"Content-Type": "application/json"}

    def status(authorization: str | None) -> int:
        headers = {**kinds, **({"Authorization": authorization} if authorization else {})}
        # The DSP gateway is what may reach this port, and it holds no credentials of its own.
        return http_from("dataspace", "dsp-gateway", "POST", target, headers, body)[0]

    mock = json.dumps({"region": "eu", "audience": target, "clientId": OWNER})
    result("A real participant's token is taken", status(tokens[OWNER]) == 200, status(tokens[OWNER]))
    result("No token: refused", status(None) == 401, status(None))
    result("Something that isn't a token: refused", status("nonsense") == 401)
    result("The mock identity's token: refused", status(mock) == 401, status(mock))
    result("A token with the right claims and the wrong key: refused", status(forged_token(issuer)) == 401)
    result(
        "A token from the realm that isn't a participant's: refused", status(admin_token) == 401, status(admin_token)
    )

    print("\n--- A connector claiming to be another participant")
    # The other owner's connector really has this asset. The notification says it is the owner's.
    sent = lc.http(
        "POST",
        f"{GATEWAY}/outbox/messages",
        {"receiver_participant": BUILDER, "payload": {"from": "the other owner"}},
        {"Authorization": f"Bearer {tokens[OTHER_OWNER]}"},
    )
    asset = sent[1]["message_id"]
    # The control: the same connectors and the same asset complete, so that a stall below can't be from anything else.
    honest = None
    deadline = time.monotonic() + 150
    while time.monotonic() < deadline:
        _, honest = lc.http(
            "GET", f"{GATEWAY}/inbox/messages/{asset}", None, {"Authorization": f"Bearer {tokens[BUILDER]}"}
        )
        if isinstance(honest, dict) and honest.get("status") in ("received", "acked", "error"):
            break
        time.sleep(1)
    result(
        "The same asset, sent by its real owner, arrives",
        isinstance(honest, dict) and honest.get("status") == "received",
        honest,
    )
    lying = f"lying-{TAG}"
    provider_dsp = f"http://{connector_host(OTHER_OWNER)}:8082/api/v1/dsp"
    notice = {
        "message_id": lying,
        "conversation_id": f"conversation-{TAG}",
        "sender_participant": OWNER,
        "receiver_participant": BUILDER,
        "asset_id": asset,
        "provider_dsp_url": provider_dsp,
    }
    # The notification itself is honest about who sent it. What it names as the connector is not the sender's.
    answer = http_from(
        NS,
        adapter(OWNER),
        "POST",
        f"{adapter_url(BUILDER)}/internal/transfer-request",
        {"Authorization": f"Bearer {tokens[OWNER]}", "Content-Type": "application/json"},
        json.dumps(notice).encode(),
    )
    result("The notification is accepted", answer[0] == 202, answer)
    deadline = time.monotonic() + 150
    state = None
    while time.monotonic() < deadline:
        _, state = lc.http(
            "GET", f"{GATEWAY}/inbox/messages/{lying}", None, {"Authorization": f"Bearer {tokens[BUILDER]}"}
        )
        if isinstance(state, dict) and state.get("status") in ("received", "acked", "error"):
            break
        time.sleep(1)
    result(
        "The negotiation doesn't complete, and the message ends with status error",
        isinstance(state, dict) and state.get("status") == "error",
        state,
    )
    print(f"     It says: {str(state.get('error_message'))[:160]}" if isinstance(state, dict) else "")
    result("Its content never arrives", isinstance(state, dict) and state.get("payload") is None, state)

    # What stopped it: this connector answers as itself, so its agreement doesn't match the offer, which names the
    # claimed participant, and the consumer refuses it. A stall for any other reason wouldn't show this.
    named = connector_negotiations(BUILDER, provider_dsp, OWNER)
    result("The consumer tried, naming the claimed participant", len(named) >= 1, named)
    result(
        "That negotiation never reached agreement",
        bool(named) and all(item.get("state") != "FINALIZED" and not item.get("contractAgreementId") for item in named),
        named,
    )
    log = lc.kubectl("-n", NS, "logs", f"deploy/connector-{lc.slug(BUILDER)}")
    result("The consumer's connector refused the agreement it got", "Validation failed" in log, log[-500:])


def check_public_reads(management: str, gateway_token: str) -> None:
    print("\n--- Public reads")
    owner = urllib.parse.quote(OWNER, safe=":")
    builder = urllib.parse.quote(BUILDER, safe=":")
    status, _ = lc.http("GET", f"{management}/api/participants/{owner}/capabilities")
    result("A participant's capabilities need an administrator", status == 401, status)
    status, _ = lc.http("GET", f"{management}/api/policy?fo={owner}&mb={builder}")
    result("A pair's policy needs an administrator", status == 401, status)
    for path in ("/api/participants", f"/api/participants/{owner}", f"/api/participants/compatible/{builder}"):
        status, body = lc.http("GET", f"{management}{path}", raw=True)
        result(f"GET {path} holds no internal address", status == 200 and NS.encode() not in body, status)
    status, body = lc.http(
        "GET", f"{GATEWAY}/participants/compatible", None, {"Authorization": f"Bearer {gateway_token}"}, raw=True
    )
    result("GET /participants/compatible holds no internal address", status == 200 and NS.encode() not in body, status)


def token_for(keycloak: str, client: str, secret: str) -> str:
    form = {"grant_type": "client_credentials", "client_id": client, "client_secret": secret}
    status, answer = lc.http_form(f"{keycloak}/realms/dataspace/protocol/openid-connect/token", form)
    assert status == 200, answer
    return answer["access_token"]


GATEWAY = ""


def main() -> int:
    global GATEWAY
    version = lc.kubectl(
        "-n", "dataspace", "get", "deploy", "gateway", "-o", "jsonpath={.spec.template.spec.containers[0].image}"
    )
    image = f"dataspace/adapter:{version.rsplit(':', 1)[1]}"
    admin_secret = (lc.LOCAL / "admin-client-secret").read_text().strip()
    with (
        lc.port_forward("dataspace", "management", 3000) as management,
        lc.port_forward("dataspace", "gateway", 8080) as gateway,
        lc.port_forward("iff", "keycloak-service", 8080) as keycloak_port,
    ):
        GATEWAY = gateway
        keycloak = f"{keycloak_port}/auth"
        _, answer = lc.http(
            "POST", f"{management}/api/admin/token", {"client_id": "dataspace-admin-cli", "client_secret": admin_secret}
        )
        admin_token = answer["access_token"]
        admin = {"Authorization": f"Bearer {admin_token}"}
        made, secrets = [], {}
        try:
            lc.apply(_probe_manifest(image))
            lc.wait_ready(OUTSIDE, "probe")
            for participant, kind in (
                (OWNER, "factory_owner"),
                (OTHER_OWNER, "factory_owner"),
                (BUILDER, "machine_builder"),
            ):
                status, record = lc.http(
                    "POST",
                    f"{management}/api/participants",
                    {"participant_id": participant, "participant_type": kind},
                    admin,
                )
                assert status == 200, record
                made.append(participant)
                secrets[participant] = record["client_secret"]
            tokens = {participant: token_for(keycloak, participant, secret) for participant, secret in secrets.items()}
            status, sent = lc.http(
                "POST",
                f"{gateway}/outbox/messages",
                {"receiver_participant": BUILDER, "payload": {"secret-payload": 1}},
                {"Authorization": f"Bearer {tokens[OWNER]}"},
            )
            assert status == 202, sent
            check_internal_routes(sent["message_id"])
            check_network("probe")
            check_credentials()
            check_connector_identity(admin_token, secrets[OWNER], management, tokens)
            check_public_reads(management, tokens[OWNER])
        finally:
            _, answer = lc.http(
                "POST",
                f"{management}/api/admin/token",
                {"client_id": "dataspace-admin-cli", "client_secret": admin_secret},
            )
            admin = {"Authorization": f"Bearer {answer['access_token']}"}
            for participant in made:
                quoted = urllib.parse.quote(participant, safe=":")
                removed = lc.http("DELETE", f"{management}/api/participants/{quoted}", None, admin)[0]
                print(f"Removed {participant}: {removed}")
            lc.kubectl("delete", "namespace", OUTSIDE, "--ignore-not-found")
    print(f"\n{failures} failed, {len(known_gaps)} known gaps")
    for what in known_gaps:
        print(f"KNOWN GAP {what}")
    if failures:
        return 1
    if known_gaps:
        print("Not a pass: the known gaps above are open, and await a maintainer's decision")
        return 2
    return 0


def _probe_manifest(image: str) -> str:
    """A pod holding no credentials, in a namespace of its own."""
    return f"""
apiVersion: v1
kind: Namespace
metadata: {{ name: {OUTSIDE} }}
---
apiVersion: apps/v1
kind: Deployment
metadata: {{ name: probe, namespace: {OUTSIDE} }}
spec:
  selector:
    matchLabels: {{ app: probe }}
  template:
    metadata:
      labels: {{ app: probe }}
    spec:
      containers:
        - name: probe
          image: {image}
          imagePullPolicy: Never
          command: ["sleep", "3600"]
"""


if __name__ == "__main__":
    sys.exit(main())
