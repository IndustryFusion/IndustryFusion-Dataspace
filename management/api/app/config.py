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

import json
from dataclasses import dataclass, field
from os import environ
from typing import NamedTuple

from app import roles


def _env(name: str, default: str = "") -> str:
    return environ.get(name, default)


def _url(name: str) -> str:
    return _env(name).rstrip("/")


DEMO_SETTING = "DEMO_PARTICIPANTS"
DEMO_KEYS = {"participant_id", "participant_type", "externally_reachable"}
IFRIC_READER_DEFAULT = "dataspace-ifric-reader"


class ConfigurationError(ValueError):
    """A setting that can't be used. The service doesn't start with one."""


class DemoParticipant(NamedTuple):
    participant_id: str
    participant_type: str
    # None means the registration default.
    externally_reachable: bool | None = None


# The demo companies, by their IFRIC ids: a participant's id is its company's company_ifric_id.
DEFAULT_DEMO = [
    DemoParticipant("urn:ifric:ifx-eur-com-own-42ced491-b35d-41f7-9949-fcbb5fa4dcd9", "factory_owner"),
    DemoParticipant("urn:ifric:ifx-eur-com-nap-37eb511d-49c0-4700-ba17-dee8248f0fb5", "machine_builder"),
    DemoParticipant("urn:ifric:ifx-eur-com-nap-2150a82e-ccbb-47d7-be5a-8059906bc253", "machine_builder"),
]


def _demo_entries(value: str) -> list[DemoParticipant]:
    if value.lstrip().startswith("["):
        try:
            listed = json.loads(value)
        except ValueError as error:
            raise ConfigurationError(f"{DEMO_SETTING} is not valid JSON: {error}") from None
        if not isinstance(listed, list):
            raise ConfigurationError(f"{DEMO_SETTING} must be a JSON list of participants")
        entries = []
        for position, item in enumerate(listed, start=1):
            where = f"{DEMO_SETTING} entry {position}"
            if not isinstance(item, dict):
                raise ConfigurationError(f"{where} must be an object")
            unknown = sorted(set(item) - DEMO_KEYS)
            if unknown:
                raise ConfigurationError(f"{where} has an unknown key: {', '.join(unknown)}")
            participant_id, participant_type = item.get("participant_id"), item.get("participant_type")
            reachable = item.get("externally_reachable")
            if not isinstance(participant_id, str) or not isinstance(participant_type, str):
                raise ConfigurationError(f"{where} needs participant_id and participant_type as strings")
            if reachable is not None and not isinstance(reachable, bool):
                raise ConfigurationError(f"{where} has externally_reachable that is not true or false")
            entries.append(DemoParticipant(participant_id, participant_type, reachable))
        return entries
    entries = []
    for entry in value.split(","):
        if entry.strip():
            participant_id, separator, participant_type = entry.strip().rpartition("=")
            if not separator or not participant_id:
                raise ConfigurationError(f"{DEMO_SETTING} entry needs <id>=<type>: {entry.strip()}")
            entries.append(DemoParticipant(participant_id.strip(), participant_type.strip()))
    return entries


def parse_demo_participants(value: str) -> list[DemoParticipant]:
    """A JSON list of participants, or `<id>=<type>` entries separated by commas. Empty means the default."""
    entries = _demo_entries(value) if value.strip() else list(DEFAULT_DEMO)
    seen: set[str] = set()
    for entry in entries:
        if not roles.id_is_safe(entry.participant_id):
            raise ConfigurationError(f"{DEMO_SETTING} has an id that registration would refuse: {entry.participant_id}")
        if not roles.is_known(entry.participant_type):
            raise ConfigurationError(f"{DEMO_SETTING} has an unknown participant_type: {entry.participant_type}")
        if entry.participant_id in seen:
            raise ConfigurationError(f"{DEMO_SETTING} names {entry.participant_id} twice")
        seen.add(entry.participant_id)
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
    s3_iam_url: str = field(default_factory=lambda: _url("SEAWEEDFS_IAM_URL"))
    keycloak_url: str = field(default_factory=lambda: _url("KEYCLOAK_URL"))
    keycloak_health_url: str = field(default_factory=lambda: _env("KEYCLOAK_HEALTH_URL"))
    keycloak_realm: str = field(default_factory=lambda: _env("KEYCLOAK_REALM", "dataspace"))
    management_client_id: str = field(default_factory=lambda: _env("MANAGEMENT_CLIENT_ID", "dataspace-admin-cli"))
    management_client_secret: str = field(default_factory=lambda: _env("MANAGEMENT_CLIENT_SECRET"))
    registry_url: str = field(default_factory=lambda: _url("REGISTRY_URL"))
    gateway_url: str = field(default_factory=lambda: _url("GATEWAY_URL"))
    gateway_peer_url: str = field(default_factory=lambda: _url("GATEWAY_PEER_URL"))
    dsp_gateway_url: str = field(default_factory=lambda: _url("DSP_GATEWAY_URL"))
    dsp_gateway_peer_url: str = field(default_factory=lambda: _url("DSP_GATEWAY_PEER_URL"))
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
    demo_participants: list[DemoParticipant] = field(
        default_factory=lambda: parse_demo_participants(_env(DEMO_SETTING))
    )
    max_upload_bytes: str = field(default_factory=lambda: _env("MAX_UPLOAD_BYTES", str(1024**3)))
    max_json_bytes: str = field(default_factory=lambda: _env("MAX_JSON_BYTES", str(4 * 1024**2)))
    ready_seconds: float = field(default_factory=lambda: float(_env("PROVISION_READY_SECONDS", "300")))
    poll_seconds: float = field(default_factory=lambda: float(_env("PROVISION_POLL_SECONDS", "2")))
    ifric_backend_url: str = field(default_factory=lambda: _url("IFRIC_BACKEND_URL"))
    ifric_reader_client_id: str = field(
        default_factory=lambda: _env("IFRIC_READER_CLIENT_ID") or IFRIC_READER_DEFAULT
    )
    ifric_reader_client_secret: str = field(default_factory=lambda: _env("IFRIC_READER_CLIENT_SECRET"))
    ifric_lookup_cache_seconds: float = field(default_factory=lambda: float(_env("IFRIC_LOOKUP_CACHE_SECONDS", "300")))
    ui_dir: str = field(default_factory=lambda: _env("MANAGEMENT_UI_DIR", "/srv/ui"))

    @property
    def issuer(self) -> str:
        return f"{self.keycloak_url}/realms/{self.keycloak_realm}"

    def image(self, component: str) -> str:
        parts = [part for part in (self.main_registry, self.main_repo, component) if part]
        return f"{'/'.join(parts)}:{self.main_version}"
