#!/usr/bin/env bash
set -Eeuo pipefail

: "${BACKUP_DATABASE_URL:?BACKUP_DATABASE_URL is required}"
timestamp="$(date -u +%Y%m%dT%H%M%SZ)"
key="postgres/${timestamp}/scam2market.dump"
workdir="$(mktemp -d)"
trap 'rm -rf "$workdir"' EXIT

pg_dump "$BACKUP_DATABASE_URL" --format=custom --compress=9 --no-owner --no-acl \
  --file="$workdir/scam2market.dump"
(cd "$workdir" && sha256sum scam2market.dump > scam2market.dump.sha256)
if [[ -n "${BACKUP_LOCAL_DIRECTORY:-}" ]]; then
  destination="${BACKUP_LOCAL_DIRECTORY}/${key}"
  mkdir -p "$(dirname "$destination")"
  cp "$workdir/scam2market.dump" "$destination"
  cp "$workdir/scam2market.dump.sha256" "${destination}.sha256"
  object="file://${destination}"
else
  : "${BACKUP_BUCKET:?BACKUP_BUCKET is required}"
  : "${BACKUP_KMS_KEY_ARN:?BACKUP_KMS_KEY_ARN is required}"
  aws s3 cp "$workdir/scam2market.dump" "s3://${BACKUP_BUCKET}/${key}" \
    --sse aws:kms --sse-kms-key-id "$BACKUP_KMS_KEY_ARN" --only-show-errors
  aws s3 cp "$workdir/scam2market.dump.sha256" "s3://${BACKUP_BUCKET}/${key}.sha256" \
    --sse aws:kms --sse-kms-key-id "$BACKUP_KMS_KEY_ARN" --only-show-errors
  aws s3api put-object-tagging --bucket "$BACKUP_BUCKET" --key "$key" \
    --tagging 'TagSet=[{Key=restore-tested,Value=false}]'
  object="s3://${BACKUP_BUCKET}/${key}"
fi
printf '{"status":"BACKED_UP","object":"%s","created_at":"%s"}\n' "$object" "$timestamp"
