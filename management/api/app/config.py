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

"""Configuration, read from the environment."""

from dataclasses import dataclass, field
from os import environ


def _env(name: str, default: str = "") -> str:
    return environ.get(name, default)


def _url(name: str) -> str:
    return _env(name).rstrip("/")


def parse_demo_participants(value: str) -> list[tuple[str, str]]:
    """`<id>=<type>` entries, separated by commas."""
    entries = []
    for entry in value.split(","):
        if entry.strip():
            participant_id, separator, participant_type = entry.strip().rpartition("=")
            if not separator or not participant_id:
                raise ValueError(f"DEMO_PARTICIPANTS entry needs <id>=<type>: {entry}")
            entries.append((participant_id, participant_type))
    return entries


@dataclass(frozen=True)
class Settings:
    postgres_host: str = field(default_factory=lambda: _env("POSTGRES_HOST", "acid-cluster.iff"))
    postgres_port: int = field(default_factory=lambda: int(_env("POSTGRES_PORT", "5432")))
    postgres_user: str = field(default_factory=lambda: _env("POSTGRES_USER"))
    postgres_password: str = field(default_factory=lambda: _env("POSTGRES_PASSWORD"))
    s3_endpoint: str = field(default_factory=lambda: _url("SEAWEEDFS_ENDPOINT"))
    s3_access_key: str = field(default_factory=lambda: _env("SEAWEEDFS_ACCESS_KEY"))
    s3_secret_key: str = field(default_factory=lambda: _env("SEAWEEDFS_SECRET_KEY"))
    keycloak_url: str = field(default_factory=lambda: _url("KEYCLOAK_URL"))
    keycloak_health_url: str = field(default_factory=lambda: _env("KEYCLOAK_HEALTH_URL"))
    keycloak_realm: str = field(default_factory=lambda: _env("KEYCLOAK_REALM", "dataspace"))
    management_client_id: str = field(default_factory=lambda: _env("MANAGEMENT_CLIENT_ID", "dataspace-admin-cli"))
    management_client_secret: str = field(default_factory=lambda: _env("MANAGEMENT_CLIENT_SECRET"))
    registry_url: str = field(default_factory=lambda: _url("REGISTRY_URL"))
    gateway_url: str = field(default_factory=lambda: _url("GATEWAY_URL"))
    gateway_peer_url: str = field(default_factory=lambda: _url("GATEWAY_PEER_URL"))
    dsp_gateway_url: str = field(default_factory=lambda: _url("DSP_GATEWAY_URL"))
    adapter_internal_key: str = field(default_factory=lambda: _env("ADAPTER_INTERNAL_KEY"))
    participants_namespace: str = field(
        default_factory=lambda: _env("PARTICIPANTS_NAMESPACE", "dataspace-participants")
    )
    main_registry: str = field(default_factory=lambda: _env("MAIN_REGISTRY").rstrip("/"))
    main_repo: str = field(default_factory=lambda: _env("MAIN_REPO", "dataspace").strip("/"))
    main_version: str = field(default_factory=lambda: _env("MAIN_VERSION", "dev"))
    cpu_request: str = field(default_factory=lambda: _env("RESOURCES_PARTICIPANT_CPU_REQUEST"))
    cpu_limit: str = field(default_factory=lambda: _env("RESOURCES_PARTICIPANT_CPU_LIMIT"))
    memory_request: str = field(default_factory=lambda: _env("RESOURCES_PARTICIPANT_MEMORY_REQUEST"))
    memory_limit: str = field(default_factory=lambda: _env("RESOURCES_PARTICIPANT_MEMORY_LIMIT", "2Gi"))
    demo_participants: list[tuple[str, str]] = field(
        default_factory=lambda: parse_demo_participants(_env("DEMO_PARTICIPANTS"))
    )
    max_upload_bytes: str = field(default_factory=lambda: _env("MAX_UPLOAD_BYTES", str(1024**3)))
    max_json_bytes: str = field(default_factory=lambda: _env("MAX_JSON_BYTES", str(4 * 1024**2)))
    ready_seconds: float = field(default_factory=lambda: float(_env("PROVISION_READY_SECONDS", "300")))
    poll_seconds: float = field(default_factory=lambda: float(_env("PROVISION_POLL_SECONDS", "2")))
    ui_dir: str = field(default_factory=lambda: _env("MANAGEMENT_UI_DIR", "/srv/ui"))

    @property
    def issuer(self) -> str:
        return f"{self.keycloak_url}/realms/{self.keycloak_realm}"

    def image(self, component: str) -> str:
        parts = [part for part in (self.main_registry, self.main_repo, component) if part]
        return f"{'/'.join(parts)}:{self.main_version}"
