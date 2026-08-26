{{- define "demo-api.name" -}}
{{- default .Chart.Name .Values.nameOverride | trunc 63 | trimSuffix "-" -}}
{{- end -}}

{{- define "demo-api.deliveryEnvironment" -}}
- name: PLATFORM_RELEASE_ID
  valueFrom:
    fieldRef:
      fieldPath: metadata.annotations['platform.startup.dev/release-id']
- name: PLATFORM_SOURCE_COMMIT
  valueFrom:
    fieldRef:
      fieldPath: metadata.annotations['platform.startup.dev/source-commit']
- name: CONTAINER_IMAGE_DIGEST
  valueFrom:
    fieldRef:
      fieldPath: metadata.annotations['platform.startup.dev/image-digest']
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
app.kubernetes.io/version: {{ default .Chart.AppVersion .Values.release.applicationVersion | quote }}
app.kubernetes.io/managed-by: {{ .Release.Service }}
{{- end -}}

{{- define "demo-api.selectorLabels" -}}
app.kubernetes.io/name: {{ include "demo-api.name" . }}
app.kubernetes.io/instance: {{ .Release.Name }}
{{- end -}}

{{- define "demo-api.releaseId" -}}
{{- $sourceCommit := default "" .Values.delivery.sourceCommit -}}
{{- $digestHex := trimPrefix "sha256:" (default "" .Values.image.digest) -}}
{{- if and (regexMatch "^[0-9a-f]{40}$" $sourceCommit) (regexMatch "^[0-9a-f]{64}$" $digestHex) -}}
{{- printf "demo-api-%s-%s" (trunc 12 $sourceCommit) (trunc 12 $digestHex) -}}
{{- else -}}
{{- printf "demo-api-local-%s" (required "release.applicationVersion is required" .Values.release.applicationVersion) -}}
{{- end -}}
{{- end -}}

{{- define "demo-api.deliveryAnnotations" -}}
platform.startup.dev/image-tag: {{ required "image.tag is required" .Values.image.tag | quote }}
platform.startup.dev/application-version: {{ required "release.applicationVersion is required" .Values.release.applicationVersion | quote }}
platform.startup.dev/environment: {{ required "env.APP_ENV is required" .Values.env.APP_ENV | quote }}
platform.startup.dev/release-id: {{ include "demo-api.releaseId" . | quote }}
platform.startup.dev/image-digest: {{ default "local-unpinned" .Values.image.digest | quote }}
{{- with .Values.delivery.sourceRepository }}
platform.startup.dev/source-repository: {{ . | quote }}
{{- end }}
platform.startup.dev/source-commit: {{ default "local-unavailable" .Values.delivery.sourceCommit | quote }}
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
