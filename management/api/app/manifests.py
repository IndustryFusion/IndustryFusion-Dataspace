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

"""The Kubernetes objects of a hosted participant, and the addresses derived from its id."""

import hashlib
import json
import pathlib
from dataclasses import dataclass
from urllib.parse import quote

from app.config import Settings

PART_OF = "dataspace-management"
SLUG_LABEL = "dataspace.industryfusion.org/slug"
ID_ANNOTATION = "dataspace.industryfusion.org/participant-id"
# What the NetworkPolicies in the participants' namespace select on.
COMPONENT_LABEL = "dataspace.industryfusion.org/component"
ANNOUNCED_ANNOTATION = "dataspace.industryfusion.org/announced-dsp-address"
SECRET_ANNOTATION = "dataspace.industryfusion.org/secret-checksum"
CONNECTOR_PORTS = {"default": 8080, "management": 8081, "dsp": 8082, "control": 8083, "public": 8084}
CONNECTOR_TEMPLATE = pathlib.Path(__file__).parent / "connector.properties.template"


def slug(participant_id: str) -> str:
    return hashlib.sha256(participant_id.encode()).hexdigest()[:8]


def adapter_name(participant_id: str) -> str:
    return f"adapter-{slug(participant_id)}"


def connector_name(participant_id: str) -> str:
    return f"connector-{slug(participant_id)}"


def secret_name(participant_id: str) -> str:
    return f"participant-{slug(participant_id)}"


def database_user(participant_id: str) -> str:
    return f"participant_{slug(participant_id)}"


def storage_identity(participant_id: str) -> str:
    return f"participant-{slug(participant_id)}"


@dataclass(frozen=True)
class Credentials:
    """What a hosted participant holds that no other does, other than its client secret."""

    edc_api_key: str
    database_password: str
    internal_key: str
    s3_access_key: str
    s3_secret_key: str


def database_names(participant_id: str) -> list[str]:
    return [f"adapter_{slug(participant_id)}", f"edc_{slug(participant_id)}"]


def bucket_name(participant_id: str) -> str:
    return f"participant-{slug(participant_id)}"


def selector_of(participant_id: str) -> str:
    return f"{SLUG_LABEL}={slug(participant_id)}"


def hosted_addresses(participant_id: str, namespace: str) -> tuple[str, str]:
    adapter = f"http://{adapter_name(participant_id)}.{namespace}:8000"
    dsp = f"http://{connector_name(participant_id)}.{namespace}:8082/api/v1/dsp"
    return adapter, dsp


def peer_route(gateway_peer_url: str, participant_id: str) -> str:
    return f"{gateway_peer_url}/peer/{quote(participant_id, safe=':')}"


def dsp_gateway_address(settings: Settings, participant_id: str, kind: str) -> str:
    return f"{settings.dsp_gateway_peer_url}/{slug(participant_id)}/api/v1/{kind}"


def announced_dsp(participant_id: str, settings: Settings, reachable: bool) -> str:
    """The address other connectors use. Only the DSP gateway's works from outside the cluster."""
    if reachable:
        return dsp_gateway_address(settings, participant_id, "dsp")
    return hosted_addresses(participant_id, settings.participants_namespace)[1]


def _metadata(participant_id: str, name: str) -> dict:
    return {
        "name": name,
        "labels": {"app.kubernetes.io/managed-by": PART_OF, SLUG_LABEL: slug(participant_id)},
        "annotations": {ID_ANNOTATION: participant_id},
    }


def _resources(settings: Settings) -> dict:
    requests = {"cpu": settings.cpu_request, "memory": settings.memory_request}
    limits = {"cpu": settings.cpu_limit, "memory": settings.memory_limit}
    return {
        section: {key: value for key, value in values.items() if value}
        for section, values in (("requests", requests), ("limits", limits))
        if any(values.values())
    }


def _from_secret(env_name: str, participant_id: str, key: str) -> dict:
    return {"name": env_name, "valueFrom": {"secretKeyRef": {"name": secret_name(participant_id), "key": key}}}


def _deployment(
    participant_id: str,
    name: str,
    container: dict,
    volumes: list[dict] | None = None,
    pod_annotations: dict[str, str] | None = None,
) -> dict:
    metadata = _metadata(participant_id, name)
    pod_spec: dict = {"containers": [container]}
    if volumes:
        pod_spec["volumes"] = volumes
    return {
        "apiVersion": "apps/v1",
        "kind": "Deployment",
        "metadata": metadata,
        "spec": {
            "selector": {"matchLabels": {"app": name}},
            "template": {
                "metadata": {
                    "labels": {**metadata["labels"], "app": name, COMPONENT_LABEL: name.split("-")[0]},
                    "annotations": pod_annotations or {},
                },
                "spec": pod_spec,
            },
        },
    }


def _service(participant_id: str, name: str, ports: dict[str, int]) -> dict:
    return {
        "apiVersion": "v1",
        "kind": "Service",
        "metadata": _metadata(participant_id, name),
        "spec": {
            "selector": {"app": name},
            "ports": [{"name": port_name, "port": port} for port_name, port in ports.items()],
        },
    }


def connector_properties(participant_id: str, settings: Settings, reachable: bool) -> str:
    """Fill in the connector's template. The id goes last, so nothing in it is taken for a placeholder."""
    url = f"http://{connector_name(participant_id)}.{settings.participants_namespace}"
    public = dsp_gateway_address(settings, participant_id, "public") if reachable else f"{url}:8084/api/v1/public"
    text = CONNECTOR_TEMPLATE.read_text().replace("${CONNECTOR_URL}", url)
    text = text.replace("${DSP_ADDRESS}", announced_dsp(participant_id, settings, reachable))
    text = text.replace("${PUBLIC_ADDRESS}", public)
    text = text.replace("${KEYCLOAK_URL}", settings.keycloak_url).replace("${KEYCLOAK_REALM}", settings.keycloak_realm)
    return text.replace("${PARTICIPANT_ID}", participant_id.replace("\\", "\\\\"))


def secret(participant_id: str, settings: Settings, client_secret: str, credentials: Credentials) -> dict:
    user, password = database_user(participant_id), credentials.database_password
    database = database_names(participant_id)[0]
    return {
        "apiVersion": "v1",
        "kind": "Secret",
        "metadata": _metadata(participant_id, secret_name(participant_id)),
        "stringData": {
            "database-url": (
                f"postgresql+asyncpg://{quote(user, safe='')}:{quote(password, safe='')}"
                f"@{settings.postgres_host}:{settings.postgres_port}/{database}"
            ),
            "db-user": user,
            "db-password": password,
            "edc-api-key": credentials.edc_api_key,
            "client-secret": client_secret,
            "s3-access-key": credentials.s3_access_key,
            "s3-secret-key": credentials.s3_secret_key,
            "internal-key": credentials.internal_key,
        },
    }


def config_map(participant_id: str, settings: Settings, reachable: bool) -> dict:
    return {
        "apiVersion": "v1",
        "kind": "ConfigMap",
        "metadata": _metadata(participant_id, connector_name(participant_id)),
        "data": {"connector.properties": connector_properties(participant_id, settings, reachable)},
    }


def connector_deployment(participant_id: str, settings: Settings, reachable: bool, secret_checksum: str = "") -> dict:
    name = connector_name(participant_id)
    database = database_names(participant_id)[1]
    jdbc = f"jdbc:postgresql://{settings.postgres_host}:{settings.postgres_port}/{database}"
    container = {
        "name": "connector",
        "image": settings.image("connector"),
        "imagePullPolicy": "IfNotPresent",
        "ports": [{"containerPort": port} for port in CONNECTOR_PORTS.values()],
        "env": [
            _from_secret("EDC_API_AUTH_KEY", participant_id, "edc-api-key"),
            {"name": "EDC_DATASOURCE_DEFAULT_URL", "value": jdbc},
            _from_secret("EDC_DATASOURCE_DEFAULT_USER", participant_id, "db-user"),
            _from_secret("EDC_DATASOURCE_DEFAULT_PASSWORD", participant_id, "db-password"),
            _from_secret("DATASPACE_KEYCLOAK_CLIENT_SECRET", participant_id, "client-secret"),
        ],
        "volumeMounts": [{"name": "config", "mountPath": "/config"}],
        "readinessProbe": {
            "httpGet": {"path": "/api/check/readiness", "port": 8080},
            "periodSeconds": 3,
            "failureThreshold": 60,
        },
        "resources": _resources(settings),
    }
    # Pods read their Secret when they start, and a connector its addresses, so a change of either restarts them.
    annotations = {
        SECRET_ANNOTATION: secret_checksum,
        ANNOUNCED_ANNOTATION: announced_dsp(participant_id, settings, reachable),
    }
    return _deployment(participant_id, name, container, [{"name": "config", "configMap": {"name": name}}], annotations)


def adapter_deployment(
    participant_id: str, participant_type: str, settings: Settings, reachable: bool, secret_checksum: str = ""
) -> dict:
    namespace = settings.participants_namespace
    adapter_url, _ = hosted_addresses(participant_id, namespace)
    plain = {
        "PARTICIPANT_ID": participant_id,
        "PARTICIPANT_TYPE": participant_type,
        "ADAPTER_URL": adapter_url,
        "EDC_MANAGEMENT_URL": f"http://{connector_name(participant_id)}.{namespace}:8081/management",
        "EDC_DSP_URL": announced_dsp(participant_id, settings, reachable),
        "PEER_NOTIFY_URL": peer_route(settings.gateway_peer_url, participant_id) if reachable else "",
        "REGISTRY_URL": settings.registry_url,
        "MAX_UPLOAD_BYTES": settings.max_upload_bytes,
        "MAX_JSON_BYTES": settings.max_json_bytes,
        "KEYCLOAK_URL": settings.keycloak_url,
        "KEYCLOAK_REALM": settings.keycloak_realm,
        "SEAWEEDFS_ENDPOINT": settings.s3_endpoint,
        "SEAWEEDFS_BUCKET": bucket_name(participant_id),
    }
    container = {
        "name": "adapter",
        "image": settings.image("adapter"),
        "imagePullPolicy": "IfNotPresent",
        "ports": [{"containerPort": 8000}],
        "env": [
            *({"name": key, "value": value} for key, value in plain.items()),
            _from_secret("DATABASE_URL", participant_id, "database-url"),
            _from_secret("EDC_API_KEY", participant_id, "edc-api-key"),
            _from_secret("KEYCLOAK_CLIENT_SECRET", participant_id, "client-secret"),
            _from_secret("SEAWEEDFS_ACCESS_KEY", participant_id, "s3-access-key"),
            _from_secret("SEAWEEDFS_SECRET_KEY", participant_id, "s3-secret-key"),
            _from_secret("ADAPTER_INTERNAL_KEY", participant_id, "internal-key"),
        ],
        "readinessProbe": {"httpGet": {"path": "/health", "port": 8000}, "periodSeconds": 3},
        "resources": _resources(settings),
    }
    annotations = {SECRET_ANNOTATION: secret_checksum}
    return _deployment(participant_id, adapter_name(participant_id), container, pod_annotations=annotations)


def connector_service(participant_id: str) -> dict:
    return _service(participant_id, connector_name(participant_id), CONNECTOR_PORTS)


def adapter_service(participant_id: str) -> dict:
    return _service(participant_id, adapter_name(participant_id), {"http": 8000})


def all_objects(
    participant_id: str,
    participant_type: str,
    settings: Settings,
    client_secret: str,
    credentials: Credentials,
    reachable: bool,
) -> list:
    """Dependencies first: a pod that starts needs its Secret and ConfigMap to be there."""
    held = secret(participant_id, settings, client_secret, credentials)
    checksum = hashlib.sha256(json.dumps(held["stringData"], sort_keys=True).encode()).hexdigest()
    return [
        held,
        config_map(participant_id, settings, reachable),
        connector_deployment(participant_id, settings, reachable, checksum),
        connector_service(participant_id),
        adapter_deployment(participant_id, participant_type, settings, reachable, checksum),
        adapter_service(participant_id),
    ]


def object_names(participant_id: str) -> list[tuple[str, str]]:
    return [
        ("Deployment", adapter_name(participant_id)),
        ("Service", adapter_name(participant_id)),
        ("Deployment", connector_name(participant_id)),
        ("Service", connector_name(participant_id)),
        ("ConfigMap", connector_name(participant_id)),
        ("Secret", secret_name(participant_id)),
    ]
