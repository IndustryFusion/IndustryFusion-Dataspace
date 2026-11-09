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
{{- define "gateway.labels" -}}
app.kubernetes.io/name: gateway
app.kubernetes.io/instance: {{ .Release.Name }}
app.kubernetes.io/part-of: dataspace
{{- end }}

{{/* The service's image: [<registry>/]<repo>/gateway:<version>. */}}
{{- define "gateway.image" -}}
{{- $parts := list -}}
{{- if .Values.images.registry }}{{ $parts = append $parts .Values.images.registry }}{{ end -}}
{{- $parts = append $parts .Values.images.repo -}}
{{- $parts = append $parts "gateway" -}}
{{ join "/" $parts }}:{{ .Values.images.version }}
{{- end }}

{{- define "gateway.keycloakEnv" -}}
- { name: KEYCLOAK_URL, value: {{ .Values.dependencies.keycloak.url | quote }} }
- { name: KEYCLOAK_REALM, value: {{ .Values.dependencies.keycloak.realm | quote }} }
{{- end }}

{{/* The limits. values.yaml.gotmpl has checked that the upload limit isn't below the JSON limit. */}}
{{- define "gateway.limitsEnv" -}}
- { name: MAX_UPLOAD_BYTES, value: {{ int64 .Values.limits.maxUploadBytes | quote }} }
- { name: MAX_JSON_BYTES, value: {{ int64 .Values.limits.maxJsonBytes | quote }} }
{{- end }}

{{/* The service's settings. Credentials come only from the Secret. */}}
{{- define "gateway.env" -}}
{{ include "gateway.keycloakEnv" . }}
- { name: REGISTRY_URL, value: {{ .Values.addresses.registry | quote }} }
{{ include "gateway.limitsEnv" . }}
{{- end }}
