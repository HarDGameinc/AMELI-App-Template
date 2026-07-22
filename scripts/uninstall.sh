#!/usr/bin/env bash
set -euo pipefail

export APP_ENV="${APP_ENV:-prod}"
source "$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/_common.sh"

require_root
disable_known_units

log "Units removidas para ${APP_INSTANCE}."
log "Datos preservados en ${DATA_DIR}, ${ETC_DIR}, ${LOG_DIR}."
