{{/*
Expand the name of the chart.
*/}}
{{- define "nurix-service.name" -}}
{{- default .Chart.Name .Values.nameOverride | trunc 63 | trimSuffix "-" }}
{{- end }}

{{/*
Create a default fully qualified app name.
*/}}
{{- define "nurix-service.fullname" -}}
{{- if .Values.fullnameOverride }}
{{- .Values.fullnameOverride | trunc 63 | trimSuffix "-" }}
{{- else }}
{{- $name := default .Chart.Name .Values.nameOverride }}
{{- if contains $name .Release.Name }}
{{- .Release.Name | trunc 63 | trimSuffix "-" }}
{{- else }}
{{- printf "%s-%s" .Release.Name $name | trunc 63 | trimSuffix "-" }}
{{- end }}
{{- end }}
{{- end }}

{{/*
Create chart name and version as used by the chart label.
*/}}
{{- define "nurix-service.chart" -}}
{{- printf "%s-%s" .Chart.Name .Chart.Version | replace "+" "_" | trunc 63 | trimSuffix "-" }}
{{- end }}

{{/*
Common labels
*/}}
{{- define "nurix-service.labels" -}}
helm.sh/chart: {{ include "nurix-service.chart" . }}
{{ include "nurix-service.selectorLabels" . }}
{{- if .Chart.AppVersion }}
app.kubernetes.io/version: {{ .Chart.AppVersion | quote }}
{{- end }}
app.kubernetes.io/managed-by: {{ .Release.Service }}
app.kubernetes.io/component: {{ .Values.application.type }}
app.kubernetes.io/part-of: {{ .Values.application.name }}
environment: {{ .Values.global.environment }}
{{- end }}

{{/*
Selector labels
*/}}
{{- define "nurix-service.selectorLabels" -}}
app.kubernetes.io/name: {{ .Values.application.name }}
app.kubernetes.io/instance: {{ .Release.Name }}
{{- end }}

{{/*
Create the name of the service account to use
*/}}
{{- define "nurix-service.serviceAccountName" -}}
{{- if .Values.serviceAccount.create }}
{{- default (include "nurix-service.fullname" .) .Values.serviceAccount.name }}
{{- else }}
{{- default "default" .Values.serviceAccount.name }}
{{- end }}
{{- end }}

{{/*
Create ConfigMap name
*/}}
{{- define "nurix-service.configMapName" -}}
{{- if .Values.configMap.name }}
{{- .Values.configMap.name }}
{{- else }}
{{- printf "%s-config" (include "nurix-service.fullname" .) }}
{{- end }}
{{- end }}

{{/*
Create Secret name
*/}}
{{- define "nurix-service.secretName" -}}
{{- if .Values.secret.name }}
{{- .Values.secret.name }}
{{- else }}
{{- printf "%s-secret" (include "nurix-service.fullname" .) }}
{{- end }}
{{- end }}

{{/*
Create Ingress name
*/}}
{{- define "nurix-service.ingressName" -}}
{{- if .Values.ingress.name }}
{{- .Values.ingress.name }}
{{- else }}
{{- printf "%s-ingress" (include "nurix-service.fullname" .) }}
{{- end }}
{{- end }}

{{/*
Create Service name
*/}}
{{- define "nurix-service.serviceName" -}}
{{- if .Values.service.name }}
{{- .Values.service.name }}
{{- else }}
{{- .Values.namespace.name }}
{{- end }}
{{- end }}


{{/*
Create WSS ALB Cert ARN
*/}}
{{- define "nurix-service.albCertArn" -}}
{{- if eq .Values.global.aws.region "us-east-1" -}}
  {{- if eq .Values.global.environment "stage" -}}
arn:aws:acm:us-east-1:533266975263:certificate/79c2f270-2a0e-455a-ac8c-9dfc977f543f
  {{- else if eq .Values.global.environment "prod" -}}
arn:aws:acm:us-east-1:533266975263:certificate/49c0219e-4d44-4baa-a836-c45b170cdbbb
  {{- end -}}
{{- else -}}
  {{- if eq .Values.global.environment "stage" -}}
arn:aws:acm:ap-south-1:533266975263:certificate/71aa2ab6-45a2-49a2-a7e3-b1890d1d5315
  {{- else if eq .Values.global.environment "prod" -}}
arn:aws:acm:ap-south-1:533266975263:certificate/7b480a5b-5cf0-48b6-a982-a2a1611fcbba
  {{- end -}}
{{- end -}}
{{- end -}}
