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
"""Renders helm/ with canary secrets and checks what a review would otherwise have to catch.

The default environment, alone and with the values file scripts/local-env.sh writes, must: keep the Ingress body
sizes equal to the services' limits, keep credentials in the Secret, use no fixed cluster addresses, and let each
pod find its settings. Needs bash, helm, helmfile and PyYAML.
"""

import pathlib
import re
import subprocess
import sys
import tempfile

import yaml
from helm_render import CANARY_SECRETS as CANARY
from helm_render import HELM, RELEASES, ROOT
from helm_render import render as render_helmfile
from helm_render import run as run_helmfile

COMPONENTS = RELEASES
IP_ADDRESS = re.compile(r"\b\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3}\b")
BODY_SIZE = "nginx.ingress.kubernetes.io/proxy-body-size"
ALLOWLIST = "nginx.ingress.kubernetes.io/whitelist-source-range"
READ_TIMEOUT = "nginx.ingress.kubernetes.io/proxy-read-timeout"
CERT_MANAGER = "cert-manager.io/cluster-issuer"


def pairs(extra: tuple[str, ...]) -> tuple[str, ...]:
    """The key=value pairs of --set arguments."""
    return tuple(value for flag, value in zip(extra[::2], extra[1::2], strict=True) if flag == "--set")


def render(component: str, values_file: str | None, secrets: str, *extra: str) -> list[dict]:
    return render_helmfile(secrets, release=component, values_file=values_file, state=pairs(extra))


def attempt(component: str, secrets: str, *extra: str) -> subprocess.CompletedProcess:
    return run_helmfile(secrets, release=component, state=pairs(extra))


def env_of(objects: list[dict]) -> dict[str, dict]:
    deployment = next(o for o in objects if o["kind"] == "Deployment")
    return {entry["name"]: entry for entry in deployment["spec"]["template"]["spec"]["containers"][0]["env"]}


def check(environment: str | None, secrets: str) -> list[str]:
    problems = []
    by_component = {
        component: render(component, environment, secrets, "--set", "ingress.enabled=true",
                          "--set", "ingress.gateway.host=g.example", "--set", "ingress.management.host=m.example",
                          "--set", "ingress.management.allowFrom=10.0.0.0/8")
        for component in COMPONENTS
    }  # fmt: skip
    for component, objects in by_component.items():
        for item in objects:
            if not item.get("apiVersion") or not item.get("kind"):
                problems.append(f"{component}: an object has no apiVersion or kind: {sorted(item)}")
                continue
            # An allowlist is addresses by its nature.
            shown = {**item, "metadata": {**item["metadata"], "annotations": {
                key: value for key, value in item["metadata"].get("annotations", {}).items() if key != ALLOWLIST
            }}}  # fmt: skip
            text = yaml.safe_dump(shown)
            if item["kind"] != "Secret" and "canary-" in text:
                problems.append(f"{component}: a credential is in a {item['kind']}")
            if IP_ADDRESS.search(text):
                problems.append(f"{component}: a fixed address is in a {item['kind']}")

    gateway, management = by_component["gateway"], by_component["management"]
    for name, objects in (("gateway", gateway), ("management", management)):
        env = env_of(objects)
        upload, json_limit = env["MAX_UPLOAD_BYTES"]["value"], env["MAX_JSON_BYTES"]["value"]
        ingress = next(o for o in objects if o.get("kind") == "Ingress")
        size = ingress["metadata"]["annotations"][BODY_SIZE]
        wanted = upload if name == "gateway" else json_limit
        if size != wanted:
            problems.append(f"{name}: Ingress body size {size} isn't the limit {wanted}")

    # A management Ingress that is open to whoever reaches it isn't a mistake that can be made.
    open_ingress = attempt(
        "management", secrets, "--set", "ingress.enabled=true", "--set", "ingress.management.host=m.example",
        "--set", "ingress.management.allowFrom=",
    )  # fmt: skip
    if open_ingress.returncode == 0 or "ingress.management.allowFrom" not in open_ingress.stderr:
        problems.append("A management Ingress without an allowlist was accepted")

    # On by default, and each policy where it belongs.
    policies = {
        o["metadata"]["name"]: (component, o)
        for component, objects in by_component.items()
        for o in objects
        if o["kind"] == "NetworkPolicy"
    }
    owners = {name: component for name, (component, _) in policies.items()}
    if owners != {"adapters": "management", "connectors": "management", "registry": "registry"}:
        problems.append(f"The NetworkPolicies and their releases are {owners}")
    elif {policies[name][1]["metadata"].get("namespace") for name in ("adapters", "connectors")} != {
        "dataspace-participants"
    }:
        problems.append("The adapters' and connectors' NetworkPolicies aren't in the participants' namespace")
    for component in ("registry", "management"):
        off = render(component, environment, secrets, "--set", "networkPolicy.enabled=false")
        if any(o["kind"] == "NetworkPolicy" for o in off):
            problems.append(f"{component}: networkPolicy.enabled=false still renders a NetworkPolicy")

    without = render("dsp-gateway", environment, secrets, "--set", "ingress.enabled=true")
    if any(o["kind"] == "Ingress" for o in without):
        problems.append("dsp-gateway: an Ingress is rendered though it isn't enabled")
    with_ingress = render(
        "dsp-gateway", environment, secrets, "--set", "ingress.enabled=true",
        "--set", "ingress.dspGateway.enabled=true", "--set", "ingress.dspGateway.host=d.example",
    )  # fmt: skip
    ingress = next((o for o in with_ingress if o["kind"] == "Ingress"), None)
    if ingress is None or ingress["spec"]["rules"][0]["host"] != "d.example":
        problems.append("dsp-gateway: enabling its Ingress doesn't route its host")
    elif ingress["spec"]["rules"][0]["http"]["paths"][0]["backend"]["service"]["port"]["number"] != 8085:
        problems.append("dsp-gateway: its Ingress doesn't go to its port")
    if "PARTICIPANTS_NAMESPACE" not in env_of(with_ingress):
        problems.append("dsp-gateway: it doesn't know the participants' namespace")

    gateway_env, management_env = env_of(gateway), env_of(management)
    for key in ("MAX_UPLOAD_BYTES", "MAX_JSON_BYTES"):
        if gateway_env[key]["value"] != management_env[key]["value"]:
            problems.append(f"{key} differs between the gateway and management")

    secret_keys = set(next(o for o in by_component["common"] if o["kind"] == "Secret")["stringData"])
    for component in ("registry", "gateway", "management"):
        for entry in env_of(by_component[component]).values():
            reference = entry.get("valueFrom", {}).get("secretKeyRef", {})
            if reference and reference["key"] not in secret_keys:
                problems.append(f"{component}: {entry['name']} reads a key the Secret lacks: {reference['key']}")

    for component in ("registry", "gateway", "dsp-gateway"):
        if env_of_account(by_component[component]) is not None:
            problems.append(f"{component} has a service account it doesn't need")
        pod = next(o for o in by_component[component] if o["kind"] == "Deployment")["spec"]["template"]["spec"]
        if pod.get("automountServiceAccountToken") is not False:
            problems.append(f"{component} mounts a service account token it doesn't need")

    for component, objects in by_component.items():
        for item in objects:
            if item["kind"] in {"ClusterRole", "ClusterRoleBinding"}:
                problems.append(f"{component}: a {item['kind']} reaches outside its namespaces")
    role = next(o for o in by_component["management"] if o["kind"] == "Role")
    if role["metadata"]["namespace"] != "dataspace-participants":
        problems.append("Management's Role isn't limited to the participants' namespace")

    # A registration has one deadline, and its undo up to 50 seconds. The Ingress must not cut that off.
    ready = int(env_of(management)["PROVISION_READY_SECONDS"]["value"])
    timeout = int(next(o for o in management if o["kind"] == "Ingress")["metadata"]["annotations"][READ_TIMEOUT])
    if timeout < ready + 50:
        problems.append(f"management: the Ingress waits {timeout}s for a registration that can take {ready + 50}s")

    tls = ("--set", "ingress.enabled=true", "--set", "ingress.gateway.host=g.example",
           "--set", "ingress.management.host=m.example", "--set", "ingress.management.allowFrom=10.0.0.0/8",
           "--set", "ingress.tls.enabled=true",
           "--set", "ingress.tls.certManagerClusterIssuer=the-issuer")  # fmt: skip
    for component, host in (("gateway", "g.example"), ("management", "m.example")):
        ingress = next(o for o in render(component, environment, secrets, *tls) if o["kind"] == "Ingress")
        if ingress["metadata"]["annotations"].get(CERT_MANAGER) != "the-issuer":
            problems.append(f"{component}: TLS with a cluster issuer has no cert-manager annotation")
        sections = ingress["spec"].get("tls", [])
        if not any(host in entry.get("hosts", []) and entry.get("secretName") for entry in sections):
            problems.append(f"{component}: TLS has no section for its host")
    return problems


def env_of_account(objects: list[dict]) -> str | None:
    return next(o for o in objects if o["kind"] == "Deployment")["spec"]["template"]["spec"].get("serviceAccountName")


def main() -> int:
    problems: list[str] = []
    with tempfile.NamedTemporaryFile("w", suffix=".yaml") as secrets:
        yaml.safe_dump(CANARY, secrets)
        secrets.flush()
        with tempfile.TemporaryDirectory() as folder:
            local_values = str(pathlib.Path(folder) / "local-values.yaml")
            subprocess.run([str(ROOT / "scripts" / "local-env.sh"), "helm-values", local_values], check=True,
                           capture_output=True)  # fmt: skip
            for name, values_file in (("default", None), ("default with the local cluster's values", local_values)):
                for problem in check(values_file, secrets.name):
                    problems.append(f"{name}: {problem}")

        # Disagreeing limits have to stop the install.
        limits = attempt(
            "gateway", secrets.name, "--set", "limits.maxUploadBytes=10", "--set", "limits.maxJsonBytes=20"
        )
        if limits.returncode == 0 or "limits.maxUploadBytes must not be below" not in limits.stderr:
            problems.append("An upload limit below the JSON limit was accepted")

    # The committed example has to name every secret the charts read, and nothing else.
    secret_template = (HELM / "charts" / "common" / "templates" / "secret.yaml").read_text()
    read = set(re.findall(r"\.Values\.secrets\.([A-Za-z0-9.]+)", secret_template))
    example_text = yaml.safe_load((HELM / "environment" / "secrets.yaml.example").read_text())["secrets"]

    def leaves(value: dict, prefix: str = "") -> set[str]:
        found = set()
        for key, item in value.items():
            found |= leaves(item, f"{prefix}{key}.") if isinstance(item, dict) else {f"{prefix}{key}"}
        return found

    if leaves(example_text) != read:
        problems.append(f"secrets.yaml.example lists {sorted(leaves(example_text))}, the Secret reads {sorted(read)}")

    # The committed example has to hold no values.
    example = yaml.safe_load((HELM / "environment" / "secrets.yaml.example").read_text())["secrets"]
    if any(value for value in (*example["postgres"].values(), *example["s3"].values(), example["adminClientSecret"])):
        problems.append("secrets.yaml.example holds a value")

    for problem in problems:
        print(f"FAIL {problem}")
    if not problems:
        print("The chart's limits, credentials and addresses are as they should be")
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main())
