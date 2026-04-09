{{/*
Copyright 2026, Microsoft

Licensed under the Apache License, Version 2.0 (the "License");
you may not use this file except in compliance with the License.
You may obtain a copy of the License at

     http://www.apache.org/licenses/LICENSE-2.0
*/}}

{{/* Chart name, truncated to 63 chars */}}
{{- define "osdu-spi-service.name" -}}
{{- .Release.Name | trunc 63 | trimSuffix "-" }}
{{- end }}

{{/* Selector labels */}}
{{- define "osdu-spi-service.selectorLabels" -}}
app.kubernetes.io/name: {{ include "osdu-spi-service.name" . }}
app.kubernetes.io/instance: {{ .Release.Name }}
{{- end }}

{{/* Common labels */}}
{{- define "osdu-spi-service.labels" -}}
{{ include "osdu-spi-service.selectorLabels" . }}
app.kubernetes.io/managed-by: {{ .Release.Service }}
app.kubernetes.io/part-of: osdu
{{- end }}
