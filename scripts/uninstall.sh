#!/usr/bin/env bash
# Uninstall an AMELI app instance.
#
#   uninstall.sh                    # SAFE: stop+remove units, preserve
#                                   #       config/data/logs/backups.
#   uninstall.sh --purge --yes      # DESTRUCTIVE: also delete every dir,
#                                   #       the system user/group, and take
#                                   #       a final backup first.
#
# The database is never dropped (the installer does not create it); a
# --purge prints the exact drop commands. Opt out of the final backup
# with AMELI_APP_UNINSTALL_SKIP_BACKUP=1 (only if you back up out of band).
set -euo pipefail

export APP_ENV="${APP_ENV:-prod}"
source "$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/_common.sh"

PURGE=0
ASSUME_YES=0
for arg in "$@"; do
  case "${arg}" in
    --purge) PURGE=1 ;;
    --yes) ASSUME_YES=1 ;;
    *) fail "uso: uninstall.sh [--purge] [--yes]" ;;
  esac
done

require_root
disable_known_units
log "Units removidas para ${APP_INSTANCE}."

if [[ "${PURGE}" != "1" ]]; then
  log "Datos preservados en ${DATA_DIR}, ${ETC_DIR}, ${LOG_DIR}, ${BACKUP_DIR}."
  log "Para eliminar TODO (dirs + usuario del sistema): uninstall.sh --purge --yes"
  exit 0
fi

# ----- purge: destructivo e IRREVERSIBLE -----
if [[ "${ASSUME_YES}" != "1" ]]; then
  fail "--purge borra ${APP_DIR}, ${ETC_DIR}, ${DATA_DIR}, ${LOG_DIR}," \
       "${BACKUP_DIR} y el usuario ${RUN_USER}. Es IRREVERSIBLE. Confirma con --yes."
fi

# A last backup before deleting everything -- the only copy left if the
# operator regrets the purge. It must NOT land in BACKUP_DIR (about to be
# removed): send it to the parent dir, where the archive survives the rm.
if [[ "${AMELI_APP_UNINSTALL_SKIP_BACKUP:-}" == "1" ]]; then
  log "WARN: AMELI_APP_UNINSTALL_SKIP_BACKUP=1 -- purga SIN backup final."
else
  final_dir="${AMELI_APP_UNINSTALL_BACKUP_DIR:-/var/backups}"
  mkdir -p "${final_dir}"
  log "Backup final antes de purgar -> ${final_dir}/${APP_INSTANCE}-*.tar.gz"
  BACKUP_DIR="${final_dir}" "${APP_DIR}/scripts/backup.sh" \
    || fail "el backup final fallo; la purga se detiene. Exporta" \
            "AMELI_APP_UNINSTALL_SKIP_BACKUP=1 para forzar la purga sin respaldo."
fi

purge_instance
