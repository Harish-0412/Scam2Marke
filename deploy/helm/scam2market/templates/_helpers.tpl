{{- define "scam2market.name" -}}scam2market{{- end }}
{{- define "scam2market.image" -}}
{{- required "image.digest must pin an immutable release" .Values.image.digest -}}
{{ printf "%s@%s" .Values.image.repository .Values.image.digest }}
{{- end }}
{{- define "scam2market.operationsImage" -}}
{{- required "backup.imageDigest must pin an immutable operations release" .Values.backup.imageDigest -}}
{{ printf "%s@%s" .Values.backup.imageRepository .Values.backup.imageDigest }}
{{- end }}
