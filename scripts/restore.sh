#!/usr/bin/env bash
# Restore-verify driver for an AMELI backup archive.
#
# Two modes:
#   verify  — extract into a scratch dir, validate MANIFEST checksums,
#             never touches the live deploy. Use it as a periodic
#             cron job to confirm backups are restorable.
#   restore — extract into the live ETC_DIR / DATA_DIR, restore the
#             DB dump back into the configured database. Destructive
#             on the live system — refuses unless ``--yes`` is passed.
#
# Usage:
#   bash scripts/restore.sh verify  <archive>
#   bash scripts/restore.sh restore <archive> --yes
#
# If the archive is GPG-encrypted (``.tar.gz.gpg``) the operator must
# have the matching private key in their keyring.

set -euo pipefail

export APP_ENV="${APP_ENV:-prod}"
source "$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/_common.sh"

mode="${1:-}"
archive="${2:-}"
flag="${3:-}"

case "${mode}" in
  verify|restore) ;;
  *) fail "usage: restore.sh {verify|restore} <archive> [--yes]" ;;
esac

[[ -f "${archive}" ]] || fail "archive not found: ${archive}"

workdir="$(mktemp -d -t "${APP_INSTANCE}-restore-XXXXXX")"
trap 'rm -rf "${workdir}"' EXIT

# 1. Decrypt if .gpg.
plain_archive="${archive}"
if [[ "${archive}" == *.gpg ]]; then
  command -v gpg >/dev/null 2>&1 || fail "gpg required to decrypt ${archive}"
  plain_archive="${workdir}/$(basename "${archive%.gpg}")"
  log "Decrypting -> ${plain_archive}"
  gpg --yes --batch --output "${plain_archive}" --decrypt "${archive}"
fi

# 2. Extract.
log "Extracting into ${workdir}"
tar -xzf "${plain_archive}" -C "${workdir}"

# 3. Manifest verification.
manifest="${workdir}/MANIFEST.sha256"
[[ -f "${manifest}" ]] || fail "MANIFEST.sha256 missing in archive"
log "Verifying MANIFEST checksums"
(cd "${workdir}" && sha256sum --check --quiet "MANIFEST.sha256") || \
  fail "MANIFEST checksums DO NOT MATCH — archive is corrupt or tampered"

log "Manifest OK"

if [[ "${mode}" == "verify" ]]; then
  log "Verify mode complete; live system untouched."
  exit 0
fi

# ----- restore (destructive) -----
if [[ "${flag}" != "--yes" ]]; then
  fail "restore is destructive on the live deploy; pass --yes to confirm"
fi
require_root

log "Restoring etc into ${ETC_DIR}"
mkdir -p "${ETC_DIR}"
cp -a "${workdir}/etc/." "${ETC_DIR}/"
log "Restoring data into ${DATA_DIR}"
mkdir -p "${DATA_DIR}"
cp -a "${workdir}/data/." "${DATA_DIR}/"

# DB restore.
if [[ -f "${workdir}/db.pgdump" ]]; then
  command -v pg_restore >/dev/null 2>&1 || fail "pg_restore not installed"
  [[ -n "${DATABASE_URL:-}" ]] || fail "DATABASE_URL not set for postgres restore"
  log "pg_restore -> ${DATABASE_URL}"
  pg_restore --clean --if-exists --no-owner --no-acl \
    --dbname="${DATABASE_URL}" "${workdir}/db.pgdump"
elif [[ -f "${workdir}/db.sqlite3" ]]; then
  [[ -n "${AMELI_APP_SQLITE_PATH:-}" ]] || fail "AMELI_APP_SQLITE_PATH not set for sqlite restore"
  log "Copying sqlite -> ${AMELI_APP_SQLITE_PATH}"
  cp "${workdir}/db.sqlite3" "${AMELI_APP_SQLITE_PATH}"
fi

log "Restore complete. Run ``ameli-app verify-audit`` to confirm chain integrity."
