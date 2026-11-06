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


@dataclass(frozen=True)
class Settings:
    participant_id: str = field(default_factory=lambda: _env("PARTICIPANT_ID"))
    participant_type: str = field(default_factory=lambda: _env("PARTICIPANT_TYPE"))
    adapter_url: str = field(default_factory=lambda: _env("ADAPTER_URL").rstrip("/"))
    database_url: str = field(default_factory=lambda: _env("DATABASE_URL"))
    edc_management_url: str = field(default_factory=lambda: _env("EDC_MANAGEMENT_URL").rstrip("/"))
    edc_api_key: str = field(default_factory=lambda: _env("EDC_API_KEY"))
    edc_dsp_url: str = field(default_factory=lambda: _env("EDC_DSP_URL").rstrip("/"))
    registry_url: str = field(default_factory=lambda: _env("REGISTRY_URL").rstrip("/"))
    keycloak_url: str = field(default_factory=lambda: _env("KEYCLOAK_URL").rstrip("/"))
    keycloak_realm: str = field(default_factory=lambda: _env("KEYCLOAK_REALM", "dataspace"))
    keycloak_client_secret: str = field(default_factory=lambda: _env("KEYCLOAK_CLIENT_SECRET"))
    s3_endpoint: str = field(default_factory=lambda: _env("SEAWEEDFS_ENDPOINT"))
    s3_access_key: str = field(default_factory=lambda: _env("SEAWEEDFS_ACCESS_KEY"))
    s3_secret_key: str = field(default_factory=lambda: _env("SEAWEEDFS_SECRET_KEY"))
    s3_bucket: str = field(default_factory=lambda: _env("SEAWEEDFS_BUCKET"))
    adapter_internal_key: str = field(default_factory=lambda: _env("ADAPTER_INTERNAL_KEY"))
    content_retention_hours: float = field(default_factory=lambda: float(_env("CONTENT_RETENTION_HOURS", "24")))
    control_plane_retention_hours: float = field(
        default_factory=lambda: float(_env("CONTROL_PLANE_RETENTION_HOURS", str(30 * 24)))
    )
    retention_interval_seconds: float = field(
        default_factory=lambda: float(_env("RETENTION_INTERVAL_SECONDS", str(30 * 60)))
    )
    schema_check_seconds: float = field(default_factory=lambda: float(_env("SCHEMA_CHECK_SECONDS", "15")))
    transfer_budget_seconds: float = field(default_factory=lambda: float(_env("TRANSFER_BUDGET_SECONDS", "120")))

    @property
    def issuer(self) -> str:
        return f"{self.keycloak_url}/realms/{self.keycloak_realm}"

    @property
    def own_role(self) -> str:
        return role_for(self.participant_id)


def role_for(participant_id: str) -> str:
    return f"participant:{participant_id}"
