#!/usr/bin/env bash
set -euo pipefail

export APP_ENV="${APP_ENV:-prod}"
source "$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/_common.sh"

require_root
resolve_systemd_profile
install_system_packages
ensure_user_group
make_dirs
copy_project_tree
initialize_runtime_env
install_python_deps
"${VENV_DIR}/bin/python" "${APP_DIR}/manage.py" migrate --noinput
"${VENV_DIR}/bin/python" "${APP_DIR}/manage.py" check
if [[ -n "${AMELI_APP_BOOTSTRAP_ADMIN_USER:-}" && -n "${AMELI_APP_BOOTSTRAP_ADMIN_PASSWORD:-}" ]]; then
  log "Bootstrap de superadmin inicial"
  "${VENV_DIR}/bin/python" -m "${APP_PACKAGE}.cli" \
    --config "${CONFIG_FILE}" \
    --env-file "${ENV_FILE}" \
    bootstrap-admin \
    --username "${AMELI_APP_BOOTSTRAP_ADMIN_USER}" \
    --password "${AMELI_APP_BOOTSTRAP_ADMIN_PASSWORD}" \
    --must-change-password
fi
render_systemd_units
repair_permissions
enable_selected_units

log "Instalacion lista: ${APP_INSTANCE} (${APP_SYSTEMD_PROFILE})"
"${APP_DIR}/scripts/validate_installation.sh"
