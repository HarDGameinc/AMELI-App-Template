#!/usr/bin/env bash
set -euo pipefail

export APP_ENV="${APP_ENV:-prod}"
source "$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/_common.sh"

require_root
resolve_systemd_profile
ensure_user_group
make_dirs
"${APP_DIR}/scripts/backup.sh" || true
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
