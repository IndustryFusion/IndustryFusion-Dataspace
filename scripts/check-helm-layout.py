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
"""Checks that helm/ renders the same objects as deploy/helm did at a git revision, apart from labels.

    check-helm-layout.py --before <revision>

It takes deploy/helm from the revision with git archive and renders each of its components as its helmfile did,
then renders helm/ with helmfile. It compares them twice: with default settings, and with the local cluster's
settings, the old local environment against the values file scripts/local-env.sh writes. Objects are matched by
kind, namespace and name, and must be equal once each object's metadata.labels and every app.kubernetes.io/instance
label, which holds the release name, are left out. If the revision has no deploy/helm, there is nothing to compare.
Needs git, bash, helm, helmfile and PyYAML.
"""

import argparse
import io
import pathlib
import subprocess
import sys
import tarfile
import tempfile

import yaml
from helm_render import CANARY_SECRETS, ROOT, render

OLD_COMPONENTS = ["common", "registry", "gateway", "dsp-gateway", "management"]
RELEASE_LABEL = "app.kubernetes.io/instance"


def extract(revision: str, into: pathlib.Path) -> pathlib.Path | None:
    answer = subprocess.run(["git", "archive", revision, "deploy/helm"], cwd=ROOT, capture_output=True)
    if answer.returncode:
        if b"did not match any files" in answer.stderr or b"path not found" in answer.stderr:
            return None
        raise SystemExit(f"git archive {revision} failed: {answer.stderr.decode()}")
    with tarfile.open(fileobj=io.BytesIO(answer.stdout)) as archive:
        archive.extractall(into, filter="data")
    return into / "deploy" / "helm"


def render_old(old: pathlib.Path, environment: str, secrets: str) -> list[dict]:
    """Each component as the old helmfile installed it: release dataspace-<component> in namespace dataspace."""
    objects = []
    for component in OLD_COMPONENTS:
        answer = subprocess.run(
            [
                "helm",
                "template",
                f"dataspace-{component}",
                str(old / "charts" / "dataspace"),
                "--namespace",
                "dataspace",
                "-f",
                str(old / "values" / "common.yaml"),
                "-f",
                str(old / "values" / "environments" / f"{environment}.yaml"),
                "-f",
                secrets,
                "--set",
                f"component={component}",
            ],  # fmt: skip
            capture_output=True,
            text=True,
        )
        if answer.returncode:
            raise SystemExit(f"helm template of the old {component} failed: {answer.stderr}")
        objects += [document for document in yaml.safe_load_all(answer.stdout) if document]
    return objects


def without_labels(value: object, top: bool = False) -> object:
    if isinstance(value, dict):
        kept = {}
        for key, item in value.items():
            if key == RELEASE_LABEL:
                continue
            if top and key == "metadata" and isinstance(item, dict):
                item = {k: v for k, v in item.items() if k != "labels"}
            kept[key] = without_labels(item)
        return kept
    if isinstance(value, list):
        return [without_labels(item) for item in value]
    return value


def keyed(objects: list[dict]) -> dict[tuple[str, str, str], dict]:
    found = {}
    for item in objects:
        metadata = item.get("metadata", {})
        key = (item.get("kind", ""), metadata.get("namespace", "dataspace"), metadata.get("name", ""))
        if key in found:
            raise SystemExit(f"{key} is rendered twice")
        found[key] = without_labels(item, top=True)
    return found


def differences(old: object, new: object, path: str = "") -> list[str]:
    if isinstance(old, dict) and isinstance(new, dict):
        found = []
        for key in sorted(set(old) | set(new), key=str):
            where = f"{path}.{key}" if path else str(key)
            if key not in new:
                found.append(f"{where}: only before")
            elif key not in old:
                found.append(f"{where}: only after")
            else:
                found += differences(old[key], new[key], where)
        return found
    if isinstance(old, list) and isinstance(new, list) and len(old) == len(new):
        found = []
        for index, (a, b) in enumerate(zip(old, new, strict=True)):
            found += differences(a, b, f"{path}[{index}]")
        return found
    return [] if old == new else [f"{path}: {old!r} before, {new!r} after"]


def compare(name: str, before: list[dict], after: list[dict]) -> list[str]:
    old, new = keyed(before), keyed(after)
    problems = [f"{name}: {key} is only before" for key in sorted(set(old) - set(new))]
    problems += [f"{name}: {key} is only after" for key in sorted(set(new) - set(old))]
    for key in sorted(set(old) & set(new)):
        problems += [f"{name}: {key} {difference}" for difference in differences(old[key], new[key])]
    if not problems:
        print(f"ok   {name}: {len(new)} objects are the same, apart from labels")
    return problems


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--before", required=True, help="the git revision whose deploy/helm to compare with")
    revision = parser.parse_args().before
    with tempfile.TemporaryDirectory() as folder:
        work = pathlib.Path(folder)
        # A push that creates a branch has no revision before it.
        old = None if set(revision) <= {"0"} else extract(revision, work / "old")
        if old is None:
            print(f"{revision} has no deploy/helm, so there is nothing to compare")
            return 0
        secrets = work / "secrets.yaml"
        secrets.write_text(yaml.safe_dump(CANARY_SECRETS))
        common = yaml.safe_load((old / "values" / "common.yaml").read_text())
        # The old layout's images and namespaces, given through helm/env.sh's variables.
        settings = {
            "LOCAL_REGISTRY": common["images"]["registry"],
            "MAIN_REPO": common["images"]["repo"],
            "MAIN_VERSION": common["images"]["version"],
            "NAMESPACE": common["namespaces"]["services"],
            "PARTICIPANTS_NAMESPACE": common["namespaces"]["participants"],
        }
        local_values = work / "local-values.yaml"
        subprocess.run([str(ROOT / "scripts" / "local-env.sh"), "helm-values", str(local_values)], check=True,
                       capture_output=True)  # fmt: skip
        problems = compare(
            "default settings",
            render_old(old, "default", str(secrets)),
            render(str(secrets), settings=settings),
        )
        problems += compare(
            "the local cluster's settings",
            render_old(old, "local", str(secrets)),
            render(str(secrets), settings=settings, values_file=str(local_values)),
        )
    for problem in problems:
        print(f"FAIL {problem}")
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main())
