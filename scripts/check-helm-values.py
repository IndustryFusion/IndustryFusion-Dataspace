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
"""Renders the Helm chart with the example secrets and checks what a review would otherwise have to catch.

Each environment file must: keep the Ingress body sizes equal to the services' limits, keep credentials
in the Secret, use no fixed cluster addresses, and let each pod find its settings. Needs helm and PyYAML.
"""

import pathlib
import re
import subprocess
import sys
import tempfile

import yaml

ROOT = pathlib.Path(__file__).resolve().parent.parent / "deploy" / "helm"
COMPONENTS = ["common", "registry", "gateway", "dsp-gateway", "management"]
CANARY = {
    "secrets": {
        "postgres": {"user": "canary-pg-user", "password": "canary-pg-password"},
        "s3": {"accessKey": "canary-s3-access", "secretKey": "canary-s3-secret"},
        "adapterInternalKey": "canary-internal-key",
    }
}
IP_ADDRESS = re.compile(r"\b\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3}\b")
BODY_SIZE = "nginx.ingress.kubernetes.io/proxy-body-size"


def render(component: str, environment: pathlib.Path, secrets: str, *extra: str) -> list[dict]:
    answer = subprocess.run(
        [
            "helm", "template", f"dataspace-{component}", str(ROOT / "charts" / "dataspace"),
            "--namespace", "dataspace",
            "-f", str(ROOT / "values" / "common.yaml"), "-f", str(environment), "-f", secrets,
            "--set", f"component={component}", *extra,
        ],  # fmt: skip
        capture_output=True,
        text=True,
    )
    if answer.returncode:
        raise SystemExit(f"helm template failed for {component}: {answer.stderr}")
    return [document for document in yaml.safe_load_all(answer.stdout) if document]


def env_of(objects: list[dict]) -> dict[str, dict]:
    deployment = next(o for o in objects if o["kind"] == "Deployment")
    return {entry["name"]: entry for entry in deployment["spec"]["template"]["spec"]["containers"][0]["env"]}


def check(environment: pathlib.Path, secrets: str) -> list[str]:
    problems = []
    by_component = {
        component: render(component, environment, secrets, "--set", "ingress.enabled=true",
                          "--set", "ingress.gateway.host=g.example", "--set", "ingress.management.host=m.example")
        for component in COMPONENTS
    }  # fmt: skip
    for component, objects in by_component.items():
        for item in objects:
            if not item.get("apiVersion") or not item.get("kind"):
                problems.append(f"{component}: an object has no apiVersion or kind: {sorted(item)}")
                continue
            text = yaml.safe_dump(item)
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
    return problems


def env_of_account(objects: list[dict]) -> str | None:
    return next(o for o in objects if o["kind"] == "Deployment")["spec"]["template"]["spec"].get("serviceAccountName")


def main() -> int:
    problems: list[str] = []
    with tempfile.NamedTemporaryFile("w", suffix=".yaml") as secrets:
        yaml.safe_dump(CANARY, secrets)
        secrets.flush()
        for environment in sorted((ROOT / "values" / "environments").glob("*.yaml")):
            for problem in check(environment, secrets.name):
                problems.append(f"{environment.name}: {problem}")

        # Disagreeing limits have to stop the install.
        extra = ("--set", "limits.maxUploadBytes=10", "--set", "limits.maxJsonBytes=20")
        attempt = subprocess.run(
            [
                "helm", "template", "x", str(ROOT / "charts" / "dataspace"), "-f", str(ROOT / "values" / "common.yaml"),
                "-f", secrets.name, "--set", "component=gateway", *extra,
            ],  # fmt: skip
            capture_output=True,
            text=True,
        )
        if attempt.returncode == 0:
            problems.append("An upload limit below the JSON limit was accepted")

    # The committed example has to name every secret, with no values.
    example = yaml.safe_load((ROOT / "values" / "secrets.yaml.example").read_text())["secrets"]
    if any(value for value in (*example["postgres"].values(), *example["s3"].values(), example["adapterInternalKey"])):
        problems.append("secrets.yaml.example holds a value")

    for problem in problems:
        print(f"FAIL {problem}")
    if not problems:
        print("The chart's limits, credentials and addresses are as they should be")
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main())
