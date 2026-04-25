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

{{/* Shared pod-spec fragment used by both Jobs. Drops an initContainer that
     pip-installs msal into /deps and the main container sets PYTHONPATH
     accordingly. The Workload Identity webhook injects AZURE_TENANT_ID,
     AZURE_CLIENT_ID, and AZURE_FEDERATED_TOKEN_FILE automatically when the
     pod carries azure.workload.identity/use: "true". */}}
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
  - name: deps
    emptyDir: {}
initContainers:
  - name: install-msal
    image: "{{ .Values.image.repository }}:{{ .Values.image.tag }}"
    imagePullPolicy: {{ .Values.image.pullPolicy }}
    command:
      - sh
      - -c
      - pip install --quiet --target=/deps msal
    volumeMounts:
      - name: deps
        mountPath: /deps
    resources:
      {{- toYaml .Values.resources | nindent 6 }}
    securityContext:
      allowPrivilegeEscalation: false
      runAsUser: 1000
      capabilities:
        drop: [ALL]
{{- end }}
