{{- define "eso-keepass-webhook.fullname" -}}
{{- if contains .Chart.Name .Release.Name -}}
{{- .Release.Name | trunc 63 | trimSuffix "-" -}}
{{- else -}}
{{- printf "%s-%s" .Release.Name .Chart.Name | trunc 63 | trimSuffix "-" -}}
{{- end -}}
{{- end -}}

{{- define "eso-keepass-webhook.selectorLabels" -}}
app.kubernetes.io/name: {{ .Chart.Name }}
app.kubernetes.io/instance: {{ .Release.Name }}
{{- end -}}

{{- define "eso-keepass-webhook.labels" -}}
{{ include "eso-keepass-webhook.selectorLabels" . }}
app.kubernetes.io/version: {{ .Chart.AppVersion | quote }}
app.kubernetes.io/managed-by: {{ .Release.Service }}
helm.sh/chart: {{ printf "%s-%s" .Chart.Name .Chart.Version }}
{{- with .Values.commonLabels }}
{{ toYaml . }}
{{- end }}
{{- end -}}

{{- define "eso-keepass-webhook.databaseSecret" -}}
{{- required "database.secretName is required" .Values.database.secretName -}}
{{- end -}}

{{- define "eso-keepass-webhook.credentialsSecret" -}}
{{- .Values.credentials.secretName | default (include "eso-keepass-webhook.databaseSecret" .) -}}
{{- end -}}

{{- define "eso-keepass-webhook.authSecret" -}}
{{- .Values.auth.existingSecret | default (printf "%s-auth" (include "eso-keepass-webhook.fullname" .)) -}}
{{- end -}}
