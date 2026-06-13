#!/usr/bin/env bash
# Operational backup for an AMELI app deploy.
#
# Bundles:
#   - the DB dump (pg_dump custom format, or sqlite copy)
#   - the env file (/etc/<instance>/app.env) and yaml config
#   - the data dir (user-uploaded media)
#   - a manifest with sha256 of every artifact for verify-restore
#
# Tunables (via env):
#   AMELI_APP_BACKUP_RETENTION_DAYS — default 30. Older archives in the
#       backup dir are removed at the end of every run (deletes are
#       limited to files matching the ``${APP_INSTANCE}-*.tar.gz*``
#       pattern so neighbouring backups are never touched).
#   AMELI_APP_BACKUP_GPG_RECIPIENT — when set, the archive is encrypted
#       with ``gpg --encrypt`` to that recipient. Without it, the
#       archive is left as plaintext (acceptable on a private file
#       system, NOT acceptable for off-host shipping).
#
# Exit codes:
#   0 — backup ready
#   1 — generic error (pre-checks, missing tools, IO)
#   2 — DB dump failed (no archive written)

set -euo pipefail

export APP_ENV="${APP_ENV:-prod}"
source "$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/_common.sh"

require_root
mkdir -p "${BACKUP_DIR}"

RETENTION_DAYS="${AMELI_APP_BACKUP_RETENTION_DAYS:-30}"
GPG_RECIPIENT="${AMELI_APP_BACKUP_GPG_RECIPIENT:-}"

timestamp="$(date '+%Y%m%d-%H%M%S')"
workdir="$(mktemp -d -t "${APP_INSTANCE}-backup-XXXXXX")"
trap 'rm -rf "${workdir}"' EXIT

# 1. Dump the DB into the work dir.
db_dump_path=""
if [[ -n "${DATABASE_URL:-}" ]] && [[ "${DATABASE_URL}" == postgres* ]]; then
  command -v pg_dump >/dev/null 2>&1 || { fail "pg_dump not installed"; }
  db_dump_path="${workdir}/db.pgdump"
  log "Dumping Postgres -> ${db_dump_path}"
  if ! pg_dump --format=custom --no-owner --no-acl \
      --file="${db_dump_path}" "${DATABASE_URL}"; then
    fail "pg_dump failed" 2>&1
    exit 2
  fi
elif [[ -n "${AMELI_APP_SQLITE_PATH:-}" ]] && [[ -f "${AMELI_APP_SQLITE_PATH}" ]]; then
  db_dump_path="${workdir}/db.sqlite3"
  log "Copying SQLite -> ${db_dump_path}"
  # ``.backup`` is preferred over ``cp`` because it works against a
  # live writer without WAL inconsistencies.
  command -v sqlite3 >/dev/null 2>&1 && \
    sqlite3 "${AMELI_APP_SQLITE_PATH}" ".backup '${db_dump_path}'" || \
    cp "${AMELI_APP_SQLITE_PATH}" "${db_dump_path}"
else
  log "WARN: no DATABASE_URL nor AMELI_APP_SQLITE_PATH — DB dump skipped"
fi

# 2. Stage config + data into the work dir.
mkdir -p "${workdir}/etc" "${workdir}/data"
[[ -d "${ETC_DIR}" ]] && cp -a "${ETC_DIR}/." "${workdir}/etc/" 2>/dev/null || true
[[ -d "${DATA_DIR}" ]] && cp -a "${DATA_DIR}/." "${workdir}/data/" 2>/dev/null || true
[[ -f "${APP_DIR}/VERSION" ]] && cp "${APP_DIR}/VERSION" "${workdir}/VERSION" || true

# 3. Manifest with sha256 of every staged artifact.
manifest="${workdir}/MANIFEST.sha256"
(cd "${workdir}" && find . -type f ! -name "MANIFEST.sha256" \
    -print0 | xargs -0 sha256sum) > "${manifest}"

# 4. Pack.
archive="${BACKUP_DIR}/${APP_INSTANCE}-${timestamp}.tar.gz"
tar -czf "${archive}" -C "${workdir}" .

# 5. Optionally encrypt with GPG.
if [[ -n "${GPG_RECIPIENT}" ]]; then
  command -v gpg >/dev/null 2>&1 || { fail "gpg required when AMELI_APP_BACKUP_GPG_RECIPIENT is set"; }
  log "Encrypting -> ${archive}.gpg"
  gpg --yes --batch --encrypt --recipient "${GPG_RECIPIENT}" --output "${archive}.gpg" "${archive}"
  rm -f "${archive}"
  archive="${archive}.gpg"
fi

chmod 640 "${archive}" || true
chown "${RUN_USER}:${RUN_GROUP}" "${archive}" 2>/dev/null || true

# 6. Retention sweep — only delete files matching THIS instance's pattern.
if [[ "${RETENTION_DAYS}" =~ ^[0-9]+$ ]] && (( RETENTION_DAYS > 0 )); then
  log "Retention: deleting ${APP_INSTANCE}-*.tar.gz(.gpg) older than ${RETENTION_DAYS} days"
  find "${BACKUP_DIR}" -maxdepth 1 -type f \
       \( -name "${APP_INSTANCE}-*.tar.gz" -o -name "${APP_INSTANCE}-*.tar.gz.gpg" \) \
       -mtime "+${RETENTION_DAYS}" -print -delete || true
fi

log "Backup creado: ${archive}"
