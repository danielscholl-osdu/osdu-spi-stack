{{/*
Copyright 2026, Microsoft

Licensed under the Apache License, Version 2.0 (the "License");
you may not use this file except in compliance with the License.
*/}}

{{/* Chart name */}}
{{- define "osdu-spi-init.name" -}}
{{- .Chart.Name | trunc 63 | trimSuffix "-" }}
{{- end }}

{{/* Common labels */}}
{{- define "osdu-spi-init.labels" -}}
app.kubernetes.io/name: {{ include "osdu-spi-init.name" . }}
app.kubernetes.io/instance: {{ .Release.Name }}
app.kubernetes.io/managed-by: {{ .Release.Service }}
app.kubernetes.io/part-of: osdu
{{- end }}

{{/* Shared pod-spec fragment used by both Jobs. The Workload Identity webhook
     injects AZURE_TENANT_ID, AZURE_CLIENT_ID, and AZURE_FEDERATED_TOKEN_FILE
     automatically when the pod carries azure.workload.identity/use: "true".
     Auth uses urllib + the v1.0 token endpoint, so no MSAL pip-install step. */}}
{{- define "osdu-spi-init.podSpec" -}}
serviceAccountName: {{ .Values.serviceAccountName }}
restartPolicy: Never
{{- with .Values.nodeSelector }}
nodeSelector:
  {{- toYaml . | nindent 2 }}
{{- end }}
{{- with .Values.tolerations }}
tolerations:
  {{- toYaml . | nindent 2 }}
{{- end }}
securityContext:
  runAsNonRoot: true
  seccompProfile:
    type: RuntimeDefault
volumes:
  - name: scripts
    configMap:
      name: osdu-spi-init-scripts
      defaultMode: 0755
  - name: partition-records
    configMap:
      name: osdu-spi-init-partition-records
{{- end }}
