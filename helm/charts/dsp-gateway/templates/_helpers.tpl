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
{{- define "dsp-gateway.labels" -}}
app.kubernetes.io/name: dsp-gateway
app.kubernetes.io/instance: {{ .Release.Name }}
app.kubernetes.io/part-of: dataspace
{{- end }}

{{/* The service's image: [<registry>/]<repo>/dsp-gateway:<version>. */}}
{{- define "dsp-gateway.image" -}}
{{- $parts := list -}}
{{- if .Values.images.registry }}{{ $parts = append $parts .Values.images.registry }}{{ end -}}
{{- $parts = append $parts .Values.images.repo -}}
{{- $parts = append $parts "dsp-gateway" -}}
{{ join "/" $parts }}:{{ .Values.images.version }}
{{- end }}

{{/* The service's settings. Credentials come only from the Secret. */}}
{{- define "dsp-gateway.env" -}}
- { name: PARTICIPANTS_NAMESPACE, value: {{ .Values.namespaces.participants | quote }} }
{{- end }}
