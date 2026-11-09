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

{{/* Labels of this chart's objects. */}}
{{- define "management.labels" -}}
app.kubernetes.io/name: management
app.kubernetes.io/instance: {{ .Release.Name }}
app.kubernetes.io/part-of: dataspace
{{- end }}

{{/* The service's image: [<registry>/]<repo>/management:<version>. */}}
{{- define "management.image" -}}
{{- $parts := list -}}
{{- if .Values.images.registry }}{{ $parts = append $parts .Values.images.registry }}{{ end -}}
{{- $parts = append $parts .Values.images.repo -}}
{{- $parts = append $parts "management" -}}
{{ join "/" $parts }}:{{ .Values.images.version }}
{{- end }}

{{/* A variable read from the shared Secret. */}}
{{- define "management.fromSecret" -}}
- name: {{ .name }}
  valueFrom:
    secretKeyRef:
      name: service-credentials
      key: {{ .key }}
{{- end }}

{{- define "management.postgresEnv" -}}
- { name: POSTGRES_HOST, value: {{ .Values.dependencies.postgres.host | quote }} }
- { name: POSTGRES_PORT, value: {{ .Values.dependencies.postgres.port | quote }} }
{{ include "management.fromSecret" (dict "name" "POSTGRES_USER" "key" "postgres-user") }}
{{ include "management.fromSecret" (dict "name" "POSTGRES_PASSWORD" "key" "postgres-password") }}
{{- end }}

{{- define "management.keycloakEnv" -}}
- { name: KEYCLOAK_URL, value: {{ .Values.dependencies.keycloak.url | quote }} }
- { name: KEYCLOAK_REALM, value: {{ .Values.dependencies.keycloak.realm | quote }} }
{{- end }}

{{/* The limits. values.yaml.gotmpl has checked that the upload limit isn't below the JSON limit. */}}
{{- define "management.limitsEnv" -}}
- { name: MAX_UPLOAD_BYTES, value: {{ int64 .Values.limits.maxUploadBytes | quote }} }
- { name: MAX_JSON_BYTES, value: {{ int64 .Values.limits.maxJsonBytes | quote }} }
{{- end }}

{{/* The service's settings. Credentials come only from the Secret. */}}
{{- define "management.env" -}}
{{- $resources := .Values.participants.resources -}}
{{ include "management.postgresEnv" . }}
{{ include "management.keycloakEnv" . }}
{{ include "management.fromSecret" (dict "name" "MANAGEMENT_CLIENT_SECRET" "key" "admin-client-secret") }}
- { name: KEYCLOAK_HEALTH_URL, value: {{ .Values.dependencies.keycloak.healthUrl | quote }} }
- { name: SEAWEEDFS_ENDPOINT, value: {{ .Values.dependencies.s3.endpoint | quote }} }
{{ include "management.fromSecret" (dict "name" "SEAWEEDFS_ACCESS_KEY" "key" "s3-access-key") }}
{{ include "management.fromSecret" (dict "name" "SEAWEEDFS_SECRET_KEY" "key" "s3-secret-key") }}
- { name: SEAWEEDFS_IAM_URL, value: {{ .Values.dependencies.s3.iamUrl | quote }} }
- { name: REGISTRY_URL, value: {{ .Values.addresses.registry | quote }} }
- { name: GATEWAY_URL, value: {{ .Values.addresses.gateway | quote }} }
- { name: GATEWAY_PEER_URL, value: {{ .Values.participants.gatewayPeerUrl | default .Values.addresses.gateway | quote }} }
- { name: DSP_GATEWAY_URL, value: {{ .Values.addresses.dspGateway | quote }} }
- { name: DSP_GATEWAY_PEER_URL, value: {{ .Values.participants.dspGatewayPeerUrl | default .Values.addresses.dspGateway | quote }} }
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
{{ include "management.fromSecret" (dict "name" "IFRIC_READER_CLIENT_ID" "key" "ifric-reader-client-id") }}
{{ include "management.fromSecret" (dict "name" "IFRIC_READER_CLIENT_SECRET" "key" "ifric-reader-client-secret") }}
{{ include "management.limitsEnv" . }}
{{- end }}
