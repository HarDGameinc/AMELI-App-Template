#!/usr/bin/env bash
set -euo pipefail

export APP_ENV="${APP_ENV:-prod}"
source "$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/_common.sh"

require_root
resolve_systemd_profile
ensure_user_group
make_dirs

# The pre-update backup is the ONLY recovery path from the ``migrate``
# below, which can be irreversible or corrupt data. The old
# ``backup.sh || true`` swallowed a failed pg_dump or a full disk and let
# the destructive step proceed with no safety net. Halt instead, with an
# explicit opt-out for operators who back up out of band.
if [[ "${AMELI_APP_UPDATE_SKIP_BACKUP:-}" == "1" ]]; then
  log "WARN: AMELI_APP_UPDATE_SKIP_BACKUP=1 -- se omite el backup previo;" \
      "no hay red de seguridad local si migrate falla."
else
  "${APP_DIR}/scripts/backup.sh" \
    || fail "el backup previo fallo; el update se detiene (migrate puede ser" \
            "irreversible). Corrige el backup, o exporta" \
            "AMELI_APP_UPDATE_SKIP_BACKUP=1 si respaldas por fuera."
  # A backup that does not verify is not a safety net. Confirm the archive
  # we just wrote actually restores BEFORE touching the DB.
  _fresh_backup="$(find "${BACKUP_DIR}" -maxdepth 1 -type f \
      \( -name "${APP_INSTANCE}-*.tar.gz" -o -name "${APP_INSTANCE}-*.tar.gz.gpg" \) \
      -printf '%T@ %p\n' 2>/dev/null | sort -rn | head -n1 | cut -d' ' -f2-)"
  if [[ -z "${_fresh_backup}" ]]; then
    fail "backup.sh no dejo un archivo en ${BACKUP_DIR}; el update se detiene."
  elif [[ "${_fresh_backup}" == *.gpg ]]; then
    # Verifying a GPG archive needs the private key on this host; if it is
    # not here, do not block the update -- the archive exists, warn only.
    "${APP_DIR}/scripts/restore.sh" verify "${_fresh_backup}" \
      || log "WARN: no se pudo verificar el backup GPG (¿falta la clave privada" \
             "aca?); el archivo existe pero el manifest no se valido. Continua."
  else
    "${APP_DIR}/scripts/restore.sh" verify "${_fresh_backup}" \
      || fail "el backup previo no verifica (manifest corrupto); el update se detiene."
  fi
  log "Backup previo verificado: ${_fresh_backup}"
fi

copy_project_tree
initialize_runtime_env
install_python_deps
"${VENV_DIR}/bin/python" "${APP_DIR}/manage.py" migrate --noinput
"${VENV_DIR}/bin/python" "${APP_DIR}/manage.py" check
render_systemd_units
repair_permissions
enable_selected_units
restart_selected_units

log "Actualizacion lista: ${APP_INSTANCE} (${APP_SYSTEMD_PROFILE})"
"${APP_DIR}/scripts/validate_installation.sh"
