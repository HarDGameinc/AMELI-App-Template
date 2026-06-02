#!/usr/bin/env bash
set -euo pipefail

export APP_ENV="${APP_ENV:-prod}"
source "$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/_common.sh"

require_root
mkdir -p "${BACKUP_DIR}"

archive="${BACKUP_DIR}/${APP_INSTANCE}-$(date '+%Y%m%d-%H%M%S').tar.gz"

tar -czf "${archive}" -C / \
  "${ETC_DIR#/}" \
  "${DATA_DIR#/}" \
  "${LOG_DIR#/}" 2>/dev/null || true

if [[ -f "${APP_DIR}/VERSION" ]]; then
  cp "${APP_DIR}/VERSION" "${BACKUP_DIR}/VERSION-${APP_INSTANCE}-latest" 2>/dev/null || true
fi

chmod 640 "${archive}" || true
chown "${RUN_USER}:${RUN_GROUP}" "${archive}" 2>/dev/null || true
log "Backup creado: ${archive}"
