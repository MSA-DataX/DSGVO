#!/usr/bin/env bash
# Postgres backup + rotation for the production compose stack.
#
# What it does:
#   1. Runs pg_dump inside the `postgres` compose service (no host pg tools needed).
#   2. Compresses with gzip — ~10x reduction on scan JSON payloads.
#   3. Optionally encrypts with GPG if $BACKUP_GPG_RECIPIENT is set.
#      That's the only acceptable form for off-site storage; plain .gz
#      copied to S3 fails a DSGVO audit on "encrypted at rest" the
#      moment the bucket is outside EU.
#   4. Keeps the last 30 daily + last 12 monthly snapshots. Older
#      files are deleted from $BACKUP_DIR.
#
# How to run:
#   Manually:  ./deploy/backup.sh
#   Daily via cron (on the production host):
#     0 3 * * * /opt/dsgvo-scanner/deploy/backup.sh >> /var/log/scanner-backup.log 2>&1
#
# Required env (set via /etc/default/scanner-backup or before the cron line):
#   BACKUP_DIR               Where to write. Must be OFF the same volume as postgres_data.
#   POSTGRES_USER            Same as docker-compose.prod.yml — defaults to "scanner".
#   POSTGRES_DB              Same as docker-compose.prod.yml — defaults to "scanner".
#
# Optional env:
#   BACKUP_GPG_RECIPIENT     GPG key id / email; presence enables encryption.
#   COMPOSE_FILE             Override the compose file path (default: docker-compose.prod.yml).
#   COMPOSE_DIR              Directory holding docker-compose.yml (default: one level up from this script).

set -euo pipefail

# --- Config ---------------------------------------------------------------
BACKUP_DIR="${BACKUP_DIR:-/var/backups/scanner}"
POSTGRES_USER="${POSTGRES_USER:-scanner}"
POSTGRES_DB="${POSTGRES_DB:-scanner}"
COMPOSE_FILE="${COMPOSE_FILE:-docker-compose.prod.yml}"
COMPOSE_DIR="${COMPOSE_DIR:-"$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"}"
RETAIN_DAILY="${RETAIN_DAILY:-30}"
RETAIN_MONTHLY="${RETAIN_MONTHLY:-12}"

TIMESTAMP="$(date -u +%Y-%m-%dT%H-%M-%SZ)"
OUT_BASENAME="scanner-${TIMESTAMP}"
mkdir -p "${BACKUP_DIR}/daily" "${BACKUP_DIR}/monthly"

# --- Dump -----------------------------------------------------------------
echo "[backup] dumping ${POSTGRES_DB} at ${TIMESTAMP}"
cd "${COMPOSE_DIR}"

# `-T` disables TTY allocation so the stream stays binary-clean across
# compose + SSH. `pg_dump -Fc` would be faster to restore but the plain
# SQL dump is human-inspectable, which helps during an incident.
OUT_PLAIN="${BACKUP_DIR}/daily/${OUT_BASENAME}.sql.gz"
docker compose -f "${COMPOSE_FILE}" exec -T postgres \
    pg_dump -U "${POSTGRES_USER}" "${POSTGRES_DB}" \
  | gzip -9 > "${OUT_PLAIN}"

# --- Optional encryption --------------------------------------------------
FINAL_OUT="${OUT_PLAIN}"
if [[ -n "${BACKUP_GPG_RECIPIENT:-}" ]]; then
  OUT_ENC="${OUT_PLAIN}.gpg"
  echo "[backup] encrypting for ${BACKUP_GPG_RECIPIENT}"
  gpg --batch --yes --trust-model always \
      --recipient "${BACKUP_GPG_RECIPIENT}" \
      --output "${OUT_ENC}" \
      --encrypt "${OUT_PLAIN}"
  # Only delete the plaintext AFTER gpg succeeded.
  rm -f "${OUT_PLAIN}"
  FINAL_OUT="${OUT_ENC}"
fi

SIZE="$(stat -c%s "${FINAL_OUT}" 2>/dev/null || stat -f%z "${FINAL_OUT}")"
echo "[backup] wrote ${FINAL_OUT} (${SIZE} bytes)"

# --- Monthly promotion ----------------------------------------------------
# On the first of the month, copy today's backup into the monthly shelf.
# Cheap and keeps the logic out of cron scheduling.
if [[ "$(date -u +%d)" == "01" ]]; then
  cp -v "${FINAL_OUT}" "${BACKUP_DIR}/monthly/"
fi

# --- Rotation -------------------------------------------------------------
# Delete anything beyond the retention window. `-mtime` counts days
# since last modification; works for both .sql.gz and .sql.gz.gpg.
find "${BACKUP_DIR}/daily"   -type f -mtime "+${RETAIN_DAILY}"   -delete
# Monthly retention expressed in days (~30d * RETAIN_MONTHLY).
MONTHLY_DAYS="$(( RETAIN_MONTHLY * 31 ))"
find "${BACKUP_DIR}/monthly" -type f -mtime "+${MONTHLY_DAYS}" -delete

echo "[backup] done"
