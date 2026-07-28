{{- define "demo-api.name" -}}
{{- default .Chart.Name .Values.nameOverride | trunc 63 | trimSuffix "-" -}}
{{- end -}}

{{- define "demo-api.fullname" -}}
{{- if .Values.fullnameOverride -}}
{{- .Values.fullnameOverride | trunc 63 | trimSuffix "-" -}}
{{- else -}}
{{- $name := default .Chart.Name .Values.nameOverride -}}
{{- if contains $name .Release.Name -}}
{{- .Release.Name | trunc 63 | trimSuffix "-" -}}
{{- else -}}
{{- printf "%s-%s" .Release.Name $name | trunc 63 | trimSuffix "-" -}}
{{- end -}}
{{- end -}}
{{- end -}}

{{- define "demo-api.chart" -}}
{{- printf "%s-%s" .Chart.Name .Chart.Version | replace "+" "_" | trunc 63 | trimSuffix "-" -}}
{{- end -}}

{{- define "demo-api.labels" -}}
helm.sh/chart: {{ include "demo-api.chart" . }}
{{ include "demo-api.selectorLabels" . }}
app.kubernetes.io/version: {{ default .Chart.AppVersion .Values.env.APP_VERSION | quote }}
app.kubernetes.io/managed-by: {{ .Release.Service }}
{{- end -}}

{{- define "demo-api.selectorLabels" -}}
app.kubernetes.io/name: {{ include "demo-api.name" . }}
app.kubernetes.io/instance: {{ .Release.Name }}
{{- end -}}

{{- define "demo-api.deliveryAnnotations" -}}
platform.startup.dev/image-tag: {{ required "image.tag is required" .Values.image.tag | quote }}
platform.startup.dev/application-version: {{ required "env.APP_VERSION is required" .Values.env.APP_VERSION | quote }}
{{- with .Values.image.digest }}
platform.startup.dev/image-digest: {{ . | quote }}
{{- end }}
{{- with .Values.delivery.sourceRepository }}
platform.startup.dev/source-repository: {{ . | quote }}
{{- end }}
{{- with .Values.delivery.sourceCommit }}
platform.startup.dev/source-commit: {{ . | quote }}
{{- end }}
{{- with .Values.delivery.workflowRunId }}
platform.startup.dev/workflow-run-id: {{ . | quote }}
{{- end }}
{{- end -}}

{{- define "demo-api.serviceAccountName" -}}
{{- if .Values.serviceAccount.create -}}
{{- default (include "demo-api.fullname" .) .Values.serviceAccount.name -}}
{{- else -}}
{{- default "default" .Values.serviceAccount.name -}}
{{- end -}}
{{- end -}}

{{- define "demo-api.image" -}}
{{- $repository := required "image.repository is required" .Values.image.repository -}}
{{- $digest := default "" .Values.image.digest -}}
{{- if $digest -}}
{{- if not (regexMatch "^sha256:[0-9a-f]{64}$" $digest) -}}
{{- fail "image.digest must be a lowercase sha256 digest" -}}
{{- end -}}
{{- printf "%s@%s" $repository $digest -}}
{{- else -}}
{{- $tag := required "image.tag is required when image.digest is empty" .Values.image.tag -}}
{{- printf "%s:%s" $repository $tag -}}
{{- end -}}
{{- end -}}
