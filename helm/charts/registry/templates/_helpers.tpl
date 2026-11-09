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
{{- define "registry.labels" -}}
app.kubernetes.io/name: registry
app.kubernetes.io/instance: {{ .Release.Name }}
app.kubernetes.io/part-of: dataspace
{{- end }}

{{/* The service's image: [<registry>/]<repo>/registry:<version>. */}}
{{- define "registry.image" -}}
{{- $parts := list -}}
{{- if .Values.images.registry }}{{ $parts = append $parts .Values.images.registry }}{{ end -}}
{{- $parts = append $parts .Values.images.repo -}}
{{- $parts = append $parts "registry" -}}
{{ join "/" $parts }}:{{ .Values.images.version }}
{{- end }}

{{/* A variable read from the shared Secret. */}}
{{- define "registry.fromSecret" -}}
- name: {{ .name }}
  valueFrom:
    secretKeyRef:
      name: service-credentials
      key: {{ .key }}
{{- end }}

{{- define "registry.postgresEnv" -}}
- { name: POSTGRES_HOST, value: {{ .Values.dependencies.postgres.host | quote }} }
- { name: POSTGRES_PORT, value: {{ .Values.dependencies.postgres.port | quote }} }
{{ include "registry.fromSecret" (dict "name" "POSTGRES_USER" "key" "postgres-user") }}
{{ include "registry.fromSecret" (dict "name" "POSTGRES_PASSWORD" "key" "postgres-password") }}
{{- end }}

{{/* The service's settings. Credentials come only from the Secret. */}}
{{- define "registry.env" -}}
{{ include "registry.postgresEnv" . }}
{{- end }}
