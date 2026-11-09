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
"""Renders the helm/ deployment for the checks in scripts/, as helmfile installs it.

Settings come from helm/env.sh, sourced in a shell where the given variables are already set, so they take the
place of its defaults exactly as they would for an operator. Needs bash, helm, helmfile and PyYAML. helmfile is
taken from PATH or from helm/.tools, where `helm/bootstrap.sh tools` puts it.
"""

import os
import pathlib
import shutil
import subprocess

import yaml

ROOT = pathlib.Path(__file__).resolve().parent.parent
HELM = ROOT / "helm"
RELEASES = ["common", "registry", "gateway", "dsp-gateway", "management"]
ENV_VARIABLES = [
    "NAMESPACE", "PARTICIPANTS_NAMESPACE", "LOCAL_REGISTRY", "MAIN_REPO", "MAIN_VERSION",
    "HELM_VERSION", "HELMFILE_VERSION", "HELM_DIFF_PLUGIN",
]  # fmt: skip
# Only so the charts render. Nothing here is used.
CANARY_SECRETS = {
    "secrets": {
        "postgres": {"user": "canary-pg-user", "password": "canary-pg-password"},
        "s3": {"accessKey": "canary-s3-access", "secretKey": "canary-s3-secret"},
        "adminClientSecret": "canary-admin-secret",
        "managementBasicAuth": {"user": "canary-ui-user", "password": "canary-ui-password"},
    }
}


def helmfile() -> str:
    found = shutil.which("helmfile") or (HELM / ".tools" / "helmfile")
    if not pathlib.Path(found).exists():
        raise SystemExit("helmfile is missing. Run helm/bootstrap.sh tools first.")
    return str(found)


def environment(settings: dict[str, str] | None = None, sourced: bool = True) -> dict[str, str]:
    """The process environment after `source helm/env.sh`, with settings exported before it, as an operator would.

    Without sourcing, only the settings given are set, and the others of env.sh are unset.
    """
    base = {key: value for key, value in os.environ.items() if key not in ENV_VARIABLES}
    base.update(settings or {})
    if not sourced:
        return base
    answer = subprocess.run(
        ["bash", "-c", 'source "$1" && env -0', "env", str(HELM / "env.sh")],
        env=base,
        capture_output=True,
        text=True,
        check=True,
    )
    return dict(entry.split("=", 1) for entry in answer.stdout.split("\0") if "=" in entry)


def run(
    secrets: str,
    settings: dict[str, str] | None = None,
    values_file: str | None = None,
    release: str | None = None,
    state: tuple[str, ...] = (),
    sourced: bool = True,
    command: str = "template",
) -> subprocess.CompletedProcess:
    """helmfile -e default <command>, template by default, with key=value pairs in state as --state-values-set."""
    given = environment(settings, sourced)
    given["DATASPACE_SECRETS_FILE"] = secrets
    if values_file:
        given["DATASPACE_VALUES_FILE"] = values_file
    else:
        given.pop("DATASPACE_VALUES_FILE", None)
    arguments = [helmfile(), "-e", "default", command]
    if command == "template":
        arguments.append("--skip-deps")
    if release:
        arguments += ["--selector", f"name={release}"]
    for pair in state:
        arguments += ["--state-values-set", pair]
    return subprocess.run(arguments, cwd=HELM, env=given, capture_output=True, text=True)


def render(secrets: str, **options) -> list[dict]:
    answer = run(secrets, **options)
    if answer.returncode:
        raise SystemExit(f"helmfile template failed: {answer.stderr}")
    return [document for document in yaml.safe_load_all(answer.stdout) if document]


def by_release(secrets: str, **options) -> dict[str, list[dict]]:
    return {release: render(secrets, release=release, **options) for release in RELEASES}
