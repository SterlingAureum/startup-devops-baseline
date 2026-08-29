{{- define "startup-devops-tempo.name" -}}
{{- default .Chart.Name .Values.nameOverride | trunc 63 | trimSuffix "-" -}}
{{- end -}}

{{- define "startup-devops-tempo.fullname" -}}
{{- default "observability-tempo" .Values.fullnameOverride | trunc 63 | trimSuffix "-" -}}
{{- end -}}

{{- define "startup-devops-tempo.labels" -}}
app.kubernetes.io/name: {{ include "startup-devops-tempo.name" . }}
app.kubernetes.io/instance: {{ include "startup-devops-tempo.fullname" . }}
app.kubernetes.io/version: {{ .Chart.AppVersion | quote }}
app.kubernetes.io/managed-by: {{ .Release.Service }}
app.kubernetes.io/part-of: startup-devops-baseline
helm.sh/chart: {{ printf "%s-%s" .Chart.Name .Chart.Version | replace "+" "_" }}
{{- end -}}

{{- define "startup-devops-tempo.selectorLabels" -}}
app.kubernetes.io/name: {{ include "startup-devops-tempo.name" . }}
app.kubernetes.io/instance: {{ include "startup-devops-tempo.fullname" . }}
{{- end -}}
