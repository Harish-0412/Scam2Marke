#!/usr/bin/env bash
set -Eeuo pipefail

: "${RESTORE_DATABASE_URL:?RESTORE_DATABASE_URL is required}"
: "${ALLOW_RESTORE_DRILL:?ALLOW_RESTORE_DRILL must be true}"
[[ "$ALLOW_RESTORE_DRILL" == "true" ]] || { echo "restore drill not authorized" >&2; exit 2; }
[[ "$RESTORE_DATABASE_URL" == *restore-drill* ]] || {
  echo "RESTORE_DATABASE_URL must target a dedicated restore-drill database" >&2
  exit 2
}

workdir="$(mktemp -d)"
trap 'rm -rf "$workdir"' EXIT
if [[ -n "${BACKUP_LOCAL_DIRECTORY:-}" ]]; then
  object="${BACKUP_OBJECT:-$(find "$BACKUP_LOCAL_DIRECTORY/postgres" -name scam2market.dump -type f | sort | tail -1)}"
  [[ -n "$object" ]] || { echo "no local backup found" >&2; exit 3; }
  cp "$object" "$workdir/scam2market.dump"
  cp "${object}.sha256" "$workdir/scam2market.dump.sha256"
  object_uri="file://${object}"
else
  : "${BACKUP_BUCKET:?BACKUP_BUCKET is required}"
  object="${BACKUP_OBJECT:-$(aws s3api list-objects-v2 --bucket "$BACKUP_BUCKET" \
    --prefix postgres/ --query 'reverse(sort_by(Contents,&LastModified))[0].Key' --output text)}"
  [[ "$object" != "None" && -n "$object" ]] || { echo "no backup found" >&2; exit 3; }
  aws s3 cp "s3://${BACKUP_BUCKET}/${object}" "$workdir/scam2market.dump" --only-show-errors
  aws s3 cp "s3://${BACKUP_BUCKET}/${object}.sha256" "$workdir/scam2market.dump.sha256" --only-show-errors
  object_uri="s3://${BACKUP_BUCKET}/${object}"
fi
(cd "$workdir" && sha256sum --check scam2market.dump.sha256)
pg_restore --dbname="$RESTORE_DATABASE_URL" --clean --if-exists --no-owner --no-acl \
  "$workdir/scam2market.dump"
psql "$RESTORE_DATABASE_URL" -v ON_ERROR_STOP=1 -Atc \
  "SELECT version_num FROM alembic_version; SELECT count(*) FROM information_schema.tables WHERE table_schema='public';" \
  > "$workdir/verification.txt"
[[ "$(wc -l < "$workdir/verification.txt")" -ge 2 ]] || { echo "restore verification failed" >&2; exit 4; }
if [[ -z "${BACKUP_LOCAL_DIRECTORY:-}" ]]; then
  aws s3api put-object-tagging --bucket "$BACKUP_BUCKET" --key "$object" \
    --tagging "TagSet=[{Key=restore-tested,Value=true},{Key=restore-tested-at,Value=$(date -u +%Y-%m-%d)}]"
fi
printf '{"status":"RESTORE_VERIFIED","object":"%s","verified_at":"%s"}\n' \
  "$object_uri" "$(date -u +%Y-%m-%dT%H:%M:%SZ)"
