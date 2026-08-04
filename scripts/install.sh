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
# ``enable --now`` only STARTS stopped units; it does NOT restart
# an already-running daemon to pick up new code. Without the
# explicit restart, an in-place upgrade leaves the api/notifier
# daemons on the old Python bytecode — operators see the new
# VERSION via CLI but /health reports the previous one. Caught
# 2026-06-20 wire test (v0.4.0-django shipped but /health
# reported v0.2.0-django until manual restart).
restart_selected_units

log "Instalacion lista: ${APP_INSTANCE} (${APP_SYSTEMD_PROFILE})"

# Post-install smoke — validate the install layout, then probe /health
# on the loopback API port. Both must pass or install exits non-zero so
# a broken install cannot silently proceed to systemd enablement being
# treated as "success". See DECISIONS #10.
# validate_installation.sh ends with the /health probe (shared
# smoke_health in _common.sh), so a deploy that does not actually serve
# fails here and install exits non-zero. It used to be a separate step
# after validate, which meant `validate_installation.sh` on its own --
# the command operators are told to trust -- could report OK=25 WARN=0
# FAIL=0 for an API that answered nothing.
"${APP_DIR}/scripts/validate_installation.sh"

# Next-step pointers the operator will actually need. Kept in install.sh
# on purpose so the DX chain (install -> configure -> Caddyfile) is one
# read, not spread across five docs. See docs/FIRST_INSTALL_DJANGO.md
# for the full walk-through and docs/TLS_WITH_CADDY.md for the proxy
# side of the story.
log ""
log "Siguientes pasos (no automaticos):"
log "  1. ameli-app configure           # ALLOWED_HOSTS, TRUSTED_PROXIES, SMTP, superadmin"
log "  2. Caddy TLS reverse proxy: tomar deploy/caddy/Caddyfile.example como"
log "     molde y AGREGAR el bloque a /etc/caddy/Caddyfile (no sobrescribir:"
log "     si el host sirve otras apps, las tiras todas). Reemplazar"
log "     __HOSTNAME__, validar con 'caddy adapt --config /etc/caddy/Caddyfile'"
log "     y recien ahi 'systemctl reload caddy'."
log "  3. En ${ENV_FILE} setear (una vez Caddy este arriba):"
log "     AMELI_APP_SECURE_PROXY_SSL_HEADER=X-Forwarded-Proto=https"
log "  4. systemctl restart $(service_unit_name api)"
