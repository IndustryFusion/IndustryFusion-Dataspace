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

{{/* Labels of a component. */}}
{{- define "dataspace.labels" -}}
app.kubernetes.io/name: {{ .Values.component }}
app.kubernetes.io/instance: {{ .Release.Name }}
app.kubernetes.io/part-of: dataspace
{{- end }}

{{/* A variable read from the shared Secret. */}}
{{- define "dataspace.fromSecret" -}}
- name: {{ .name }}
  valueFrom:
    secretKeyRef:
      name: service-credentials
      key: {{ .key }}
{{- end }}

{{/* A component's image. */}}
{{- define "dataspace.image" -}}
{{- $root := .root -}}
{{- $parts := list -}}
{{- if $root.Values.images.registry }}{{ $parts = append $parts $root.Values.images.registry }}{{ end -}}
{{- $parts = append $parts $root.Values.images.repo -}}
{{- $parts = append $parts .component -}}
{{ join "/" $parts }}:{{ $root.Values.images.version }}
{{- end }}

{{/* The limits, checked: the Ingress has to admit the larger, and each service enforces its own. */}}
{{- define "dataspace.limitsEnv" -}}
{{- if lt (int64 .Values.limits.maxUploadBytes) (int64 .Values.limits.maxJsonBytes) -}}
{{- fail "limits.maxUploadBytes must not be below limits.maxJsonBytes" -}}
{{- end -}}
- { name: MAX_UPLOAD_BYTES, value: {{ int64 .Values.limits.maxUploadBytes | quote }} }
- { name: MAX_JSON_BYTES, value: {{ int64 .Values.limits.maxJsonBytes | quote }} }
{{- end }}

{{- define "dataspace.keycloakEnv" -}}
- { name: KEYCLOAK_URL, value: {{ .Values.dependencies.keycloak.url | quote }} }
- { name: KEYCLOAK_REALM, value: {{ .Values.dependencies.keycloak.realm | quote }} }
{{- end }}

{{- define "dataspace.postgresEnv" -}}
- { name: POSTGRES_HOST, value: {{ .Values.dependencies.postgres.host | quote }} }
- { name: POSTGRES_PORT, value: {{ .Values.dependencies.postgres.port | quote }} }
{{ include "dataspace.fromSecret" (dict "name" "POSTGRES_USER" "key" "postgres-user") }}
{{ include "dataspace.fromSecret" (dict "name" "POSTGRES_PASSWORD" "key" "postgres-password") }}
{{- end }}

{{/* Each component's settings. Credentials come only from the Secret. */}}
{{- define "dataspace.env.registry" -}}
{{ include "dataspace.postgresEnv" . }}
{{- end }}

{{- define "dataspace.env.gateway" -}}
{{ include "dataspace.keycloakEnv" . }}
- { name: REGISTRY_URL, value: "http://registry.{{ .Values.namespaces.services }}:19000" }
{{ include "dataspace.limitsEnv" . }}
{{- end }}

{{- define "dataspace.env.dsp-gateway" -}}
[]
{{- end }}

{{- define "dataspace.env.management" -}}
{{- $services := .Values.namespaces.services -}}
{{- $resources := .Values.participants.resources -}}
{{ include "dataspace.postgresEnv" . }}
{{ include "dataspace.keycloakEnv" . }}
{{ include "dataspace.fromSecret" (dict "name" "MANAGEMENT_CLIENT_SECRET" "key" "admin-client-secret") }}
- { name: KEYCLOAK_HEALTH_URL, value: {{ .Values.dependencies.keycloak.healthUrl | quote }} }
- { name: SEAWEEDFS_ENDPOINT, value: {{ .Values.dependencies.s3.endpoint | quote }} }
{{ include "dataspace.fromSecret" (dict "name" "SEAWEEDFS_ACCESS_KEY" "key" "s3-access-key") }}
{{ include "dataspace.fromSecret" (dict "name" "SEAWEEDFS_SECRET_KEY" "key" "s3-secret-key") }}
{{ include "dataspace.fromSecret" (dict "name" "ADAPTER_INTERNAL_KEY" "key" "adapter-internal-key") }}
- { name: REGISTRY_URL, value: "http://registry.{{ $services }}:19000" }
- { name: GATEWAY_URL, value: "http://gateway.{{ $services }}:8080" }
- { name: GATEWAY_PEER_URL, value: {{ .Values.participants.gatewayPeerUrl | default (printf "http://gateway.%s:8080" $services) | quote }} }
- { name: DSP_GATEWAY_URL, value: "http://dsp-gateway.{{ $services }}:8085" }
- { name: PARTICIPANTS_NAMESPACE, value: {{ .Values.namespaces.participants | quote }} }
- { name: MAIN_REGISTRY, value: {{ .Values.images.registry | quote }} }
- { name: MAIN_REPO, value: {{ .Values.images.repo | quote }} }
- { name: MAIN_VERSION, value: {{ .Values.images.version | quote }} }
- { name: RESOURCES_PARTICIPANT_CPU_REQUEST, value: {{ $resources.cpuRequest | quote }} }
- { name: RESOURCES_PARTICIPANT_CPU_LIMIT, value: {{ $resources.cpuLimit | quote }} }
- { name: RESOURCES_PARTICIPANT_MEMORY_REQUEST, value: {{ $resources.memoryRequest | quote }} }
- { name: RESOURCES_PARTICIPANT_MEMORY_LIMIT, value: {{ $resources.memoryLimit | quote }} }
- { name: PROVISION_READY_SECONDS, value: {{ .Values.participants.provisionReadySeconds | quote }} }
- { name: DEMO_PARTICIPANTS, value: {{ .Values.participants.demo | quote }} }
- { name: IFRIC_BACKEND_URL, value: {{ .Values.ifric.backendUrl | quote }} }
- { name: IFRIC_LOOKUP_CACHE_SECONDS, value: {{ .Values.ifric.lookupCacheSeconds | quote }} }
{{ include "dataspace.fromSecret" (dict "name" "IFRIC_READER_CLIENT_ID" "key" "ifric-reader-client-id") }}
{{ include "dataspace.fromSecret" (dict "name" "IFRIC_READER_CLIENT_SECRET" "key" "ifric-reader-client-secret") }}
{{ include "dataspace.limitsEnv" . }}
{{- end }}
