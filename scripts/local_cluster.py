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

"""Helpers for scripts that act on the local environment. Uses only .local/kubeconfig."""

import contextlib
import hashlib
import json
import pathlib
import socket
import subprocess
import textwrap
import time
import urllib.error
import urllib.request
from collections.abc import Iterator

ROOT = pathlib.Path(__file__).resolve().parent.parent
LOCAL = ROOT / ".local"
KUBECONFIG = LOCAL / "kubeconfig"
PARTICIPANTS = "dataspace-participants"
CLUSTER = "dataspace-local"


def slug(participant_id: str) -> str:
    return hashlib.sha256(participant_id.encode()).hexdigest()[:8]


def credentials() -> dict[str, str]:
    lines = (LOCAL / "credentials.env").read_text().splitlines()
    return dict(line.split("=", 1) for line in lines if "=" in line)


def kubectl(*args: str, stdin: str | None = None) -> str:
    result = subprocess.run(
        ["kubectl", "--kubeconfig", str(KUBECONFIG), *args],
        input=stdin,
        text=True,
        capture_output=True,
    )
    if result.returncode:
        raise RuntimeError(f"kubectl {' '.join(args)} failed: {result.stderr.strip()}")
    return result.stdout


def apply(manifest: str) -> None:
    kubectl("apply", "-f", "-", stdin=manifest)


def render(template: str, **values: str) -> str:
    text = (ROOT / "deploy" / "local" / template).read_text()
    for key, value in values.items():
        text = text.replace("${" + key + "}", value)
    return text


def ensure_database(name: str) -> None:
    user = credentials()["POSTGRES_USER"]
    found = kubectl(
        "-n", "iff", "exec", "deploy/acid-cluster", "--", "psql", "-U", user, "-d", "postgres", "-Atc",
        f"SELECT 1 FROM pg_database WHERE datname = '{name}'",
    )
    if not found.strip():
        kubectl(
            "-n", "iff", "exec", "deploy/acid-cluster", "--", "psql", "-U", user, "-d", "postgres", "-c",
            f'CREATE DATABASE "{name}"',
        )


def drop_database(name: str) -> None:
    user = credentials()["POSTGRES_USER"]
    kubectl(
        "-n", "iff", "exec", "deploy/acid-cluster", "--", "psql", "-U", user, "-d", "postgres", "-c",
        f'DROP DATABASE IF EXISTS "{name}" WITH (FORCE)',
    )


def deploy_connector(participant_id: str, api_key: str) -> str:
    """Deploy one participant's connector, and return its Service name."""
    name = slug(participant_id)
    ensure_database(f"edc_{name}")
    url = f"http://connector-{name}.{PARTICIPANTS}"
    properties = (ROOT / "connector" / "connector.properties.template").read_text()
    properties = properties.replace("${PARTICIPANT_ID}", participant_id).replace("${CONNECTOR_URL}", url)
    secrets = credentials()
    apply(
        render(
            "connector.yaml.template",
            SLUG=name,
            CONNECTOR_PROPERTIES=textwrap.indent(properties, "    "),
            EDC_API_KEY=api_key,
            POSTGRES_USER=secrets["POSTGRES_USER"],
            POSTGRES_PASSWORD=secrets["POSTGRES_PASSWORD"],
        )
    )
    return f"connector-{name}"


def remove_connector(participant_id: str) -> None:
    name = slug(participant_id)
    for kind in ("deployment", "service", "configmap", "secret"):
        kubectl("-n", PARTICIPANTS, "delete", kind, f"connector-{name}", "--ignore-not-found")
    drop_database(f"edc_{name}")


def wait_ready(namespace: str, deployment: str, timeout: int = 300) -> None:
    kubectl("-n", namespace, "rollout", "status", f"deploy/{deployment}", f"--timeout={timeout}s")


def _free_port() -> int:
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        return probe.getsockname()[1]


@contextlib.contextmanager
def port_forward(namespace: str, service: str, port: int) -> Iterator[str]:
    """Forward a Service port, and yield its local base URL."""
    local = _free_port()
    process = subprocess.Popen(
        ["kubectl", "--kubeconfig", str(KUBECONFIG), "-n", namespace, "port-forward", f"svc/{service}", f"{local}:{port}"],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    try:
        for _ in range(60):
            with socket.socket() as probe:
                if probe.connect_ex(("127.0.0.1", local)) == 0:
                    break
            time.sleep(0.5)
        yield f"http://127.0.0.1:{local}"
    finally:
        process.terminate()
        process.wait()


def http(method: str, url: str, body: object = None, headers: dict | None = None, raw: bool = False):
    """Make a request and return (status, parsed body)."""
    data = None if body is None else (body if isinstance(body, bytes) else json.dumps(body).encode())
    request = urllib.request.Request(url, data, method=method)
    if body is not None and not isinstance(body, bytes):
        request.add_header("Content-Type", "application/json")
    for key, value in (headers or {}).items():
        request.add_header(key, value)
    try:
        with urllib.request.urlopen(request, timeout=130) as response:
            status, content = response.status, response.read()
    except urllib.error.HTTPError as error:
        status, content = error.code, error.read()
    if raw:
        return status, content
    try:
        return status, json.loads(content) if content else None
    except ValueError:
        return status, content.decode(errors="replace")


def poll(check, timeout: float = 120, interval: float = 1, what: str = "condition"):
    """Call check() until it returns something true, and return that."""
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        value = check()
        if value:
            return value
        time.sleep(interval)
    raise TimeoutError(f"Timed out waiting for {what}")
