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
"""Checks that the images scripts/build-images.sh names are exactly the ones a deployment uses.

For each set of images.registry, images.repo and images.version, it renders every release of the chart and
collects the images of its pods. It takes MAIN_REGISTRY, MAIN_REPO and MAIN_VERSION from the management
Deployment, and asks the management API's own settings for the adapter and connector images. Together they
must be the six names that build-images.sh --list prints for the same settings. Needs bash, helm and PyYAML.

    check-image-names.py                   Checks scripts/build-images.sh
    check-image-names.py --script <file>   Checks another copy, such as one with a change undone
"""

import argparse
import importlib
import os
import pathlib
import subprocess
import sys
import tempfile

import yaml

ROOT = pathlib.Path(__file__).resolve().parent.parent
HELM = ROOT / "deploy" / "helm"
RELEASES = ["common", "registry", "gateway", "dsp-gateway", "management"]
SETTINGS = [
    ("reg.example:5000", "team/dataspace", "1.2.3"),
    ("k3d-iff.localhost:12345", "dataspace", "latest"),
    ("", "dataspace", "dev"),
]
# Only so the chart renders. Nothing here is used.
SECRETS = {
    "secrets": {
        "postgres": {"user": "check-user", "password": "check-password"},
        "s3": {"accessKey": "check-access", "secretKey": "check-secret"},
        "adminClientSecret": "check-admin-secret",
    }
}


def render(release: str, secrets: str, registry: str, repo: str, version: str) -> list[dict]:
    answer = subprocess.run(
        [
            "helm", "template", f"dataspace-{release}", str(HELM / "charts" / "dataspace"),
            "--namespace", "dataspace",
            "-f", str(HELM / "values" / "common.yaml"), "-f", secrets,
            "--set", f"component={release}",
            "--set-string", f"images.registry={registry}",
            "--set-string", f"images.repo={repo}",
            "--set-string", f"images.version={version}",
        ],  # fmt: skip
        capture_output=True,
        text=True,
    )
    if answer.returncode:
        raise SystemExit(f"helm template failed for {release}: {answer.stderr}")
    return [document for document in yaml.safe_load_all(answer.stdout) if document]


def pod_specs(item: dict) -> list[dict]:
    spec = item.get("spec") or {}
    if item.get("kind") == "Pod":
        return [spec]
    if item.get("kind") == "CronJob":
        return [spec["jobTemplate"]["spec"]["template"]["spec"]]
    template = spec.get("template") or {}
    return [template["spec"]] if "spec" in template else []


def chart_names(secrets: str, registry: str, repo: str, version: str) -> tuple[list[str], dict[str, str]]:
    """The images of the chart's pods, and the management Deployment's MAIN_* settings."""
    images: list[str] = []
    main: dict[str, str] = {}
    for release in RELEASES:
        for item in render(release, secrets, registry, repo, version):
            for spec in pod_specs(item):
                for container in spec.get("initContainers", []) + spec.get("containers", []):
                    images.append(container["image"])
                    if release == "management" and container.get("name") == "management":
                        for entry in container.get("env", []):
                            if entry["name"].startswith("MAIN_"):
                                main[entry["name"]] = entry.get("value", "")
    return images, main


def participant_names(main: dict[str, str]) -> list[str]:
    """The adapter and connector images, as the management API names them from these settings."""
    saved = {key: os.environ.get(key) for key in main}
    os.environ.update(main)
    try:
        sys.path.insert(0, str(ROOT / "management" / "api"))
        config = importlib.import_module("app.config")
        if not pathlib.Path(config.__file__).resolve().is_relative_to(ROOT):
            raise SystemExit(f"The management API's settings came from {config.__file__}, not from this checkout")
        settings = config.Settings()
        return [settings.image("adapter"), settings.image("connector")]
    finally:
        sys.path.pop(0)
        for key, value in saved.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value


def script_names(script: pathlib.Path, registry: str, repo: str, version: str) -> list[str]:
    environment = {
        "PATH": os.environ.get("PATH", ""),
        "REGISTRY": registry,
        "REPO": repo,
        "VERSION": version,
        # So a scripts/build-images.env in the checkout doesn't change what is compared.
        "BUILD_IMAGES_CONFIG": os.devnull,
    }
    answer = subprocess.run(["bash", str(script), "--list"], env=environment, capture_output=True, text=True)
    if answer.returncode:
        raise SystemExit(f"build-images.sh --list failed: {answer.stderr}")
    return answer.stdout.splitlines()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--script", type=pathlib.Path, default=ROOT / "scripts" / "build-images.sh")
    script = parser.parse_args().script.resolve()
    problems = []
    with tempfile.NamedTemporaryFile("w", suffix=".yaml") as secrets:
        yaml.safe_dump(SECRETS, secrets)
        secrets.flush()
        for registry, repo, version in SETTINGS:
            shown = f"registry={registry!r} repo={repo!r} version={version!r}"
            images, main = chart_names(secrets.name, registry, repo, version)
            expected_main = {"MAIN_REGISTRY": registry, "MAIN_REPO": repo, "MAIN_VERSION": version}
            if main != expected_main:
                problems.append(f"{shown}: the management Deployment has {main}, not {expected_main}")
            deployed = images + participant_names(main)
            listed = script_names(script, registry, repo, version)
            if sorted(deployed) != sorted(listed) or len(set(listed)) != len(listed):
                problems.append(f"{shown}: the deployment uses {sorted(deployed)}, the script names {sorted(listed)}")
            else:
                print(f"ok   {shown}: {len(listed)} names match")
    for problem in problems:
        print(f"FAIL {problem}")
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main())
