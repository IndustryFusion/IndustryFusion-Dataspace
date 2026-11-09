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

For each setting of LOCAL_REGISTRY, MAIN_REPO and MAIN_VERSION, given to helm/env.sh as an operator would, it
renders every release of helm/ with helmfile and collects the images of its pods. It takes MAIN_REGISTRY,
MAIN_REPO and MAIN_VERSION from the management Deployment, and asks the management API's own settings for the
adapter and connector images. Together they must be the six names that build-images.sh --list prints with the
same settings. Needs bash, helm, helmfile and PyYAML.

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
from helm_render import CANARY_SECRETS, RELEASES, ROOT, environment, render

# Each with helm/env.sh sourced after the settings, or, last, without it, where LOCAL_REGISTRY is unset and the
# charts and the script have to fall back to the same default. None is env.sh's defaults.
SETTINGS: list[tuple[dict[str, str] | None, bool]] = [
    (None, True),
    ({"LOCAL_REGISTRY": "reg.example:5000", "MAIN_REPO": "team/dataspace", "MAIN_VERSION": "1.2.3"}, True),
    ({"LOCAL_REGISTRY": "", "MAIN_REPO": "dataspace", "MAIN_VERSION": "dev"}, True),
    (
        {"MAIN_REPO": "dataspace", "MAIN_VERSION": "1.0", "NAMESPACE": "dataspace",
         "PARTICIPANTS_NAMESPACE": "dataspace-participants"},
        False,
    ),
]  # fmt: skip


def pod_specs(item: dict) -> list[dict]:
    spec = item.get("spec") or {}
    if item.get("kind") == "Pod":
        return [spec]
    if item.get("kind") == "CronJob":
        return [spec["jobTemplate"]["spec"]["template"]["spec"]]
    template = spec.get("template") or {}
    return [template["spec"]] if "spec" in template else []


def chart_names(secrets: str, settings: dict[str, str] | None, sourced: bool) -> tuple[list[str], dict[str, str]]:
    """The images of the chart's pods, and the management Deployment's MAIN_* settings."""
    images: list[str] = []
    main: dict[str, str] = {}
    for release in RELEASES:
        for item in render(secrets, settings=settings, release=release, sourced=sourced):
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


def script_names(script: pathlib.Path, settings: dict[str, str] | None, sourced: bool) -> list[str]:
    answer = subprocess.run(
        ["bash", str(script), "--list"], env=environment(settings, sourced), capture_output=True, text=True
    )
    if answer.returncode:
        raise SystemExit(f"build-images.sh --list failed: {answer.stderr}")
    return answer.stdout.splitlines()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--script", type=pathlib.Path, default=ROOT / "scripts" / "build-images.sh")
    script = parser.parse_args().script.resolve()
    problems = []
    with tempfile.NamedTemporaryFile("w", suffix=".yaml") as secrets:
        yaml.safe_dump(CANARY_SECRETS, secrets)
        secrets.flush()
        for settings, sourced in SETTINGS:
            used = environment(settings, sourced)
            registry = used.get("LOCAL_REGISTRY", "k3d-iff.localhost:12345")
            repo, version = used["MAIN_REPO"], used["MAIN_VERSION"]
            shown = (
                f"LOCAL_REGISTRY={used.get('LOCAL_REGISTRY', 'unset')!r} MAIN_REPO={repo!r} MAIN_VERSION={version!r}"
            )
            images, main = chart_names(secrets.name, settings, sourced)
            expected_main = {"MAIN_REGISTRY": registry, "MAIN_REPO": repo, "MAIN_VERSION": version}
            if main != expected_main:
                problems.append(f"{shown}: the management Deployment has {main}, not {expected_main}")
            deployed = images + participant_names(main)
            listed = script_names(script, settings, sourced)
            if sorted(deployed) != sorted(listed) or len(set(listed)) != len(listed):
                problems.append(f"{shown}: the deployment uses {sorted(deployed)}, the script names {sorted(listed)}")
            else:
                print(f"ok   {shown}: {len(listed)} names match")
    for problem in problems:
        print(f"FAIL {problem}")
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main())
