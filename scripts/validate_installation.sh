#!/usr/bin/env bash
set -euo pipefail

export APP_ENV="${APP_ENV:-prod}"
source "$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/_common.sh"

resolve_systemd_profile

OK=0
WARN=0
FAIL=0

pass() { echo "[OK] $*"; OK=$((OK + 1)); }
warn() { echo "[WARN] $*"; WARN=$((WARN + 1)); }
fail_check() { echo "[FAIL] $*"; FAIL=$((FAIL + 1)); }

[[ -d "${APP_DIR}" ]] && pass "APP_DIR_EXISTS" || fail_check "APP_DIR_EXISTS"
[[ -f "${APP_DIR}/README.md" ]] && pass "README_EXISTS" || fail_check "README_EXISTS"
[[ -f "${APP_DIR}/VERSION" ]] && pass "VERSION_EXISTS" || fail_check "VERSION_EXISTS"
[[ -f "${APP_DIR}/pyproject.toml" ]] && pass "PYPROJECT_EXISTS" || fail_check "PYPROJECT_EXISTS"
[[ -f "${CONFIG_FILE}" ]] && pass "CONFIG_FILE_EXISTS" || fail_check "CONFIG_FILE_EXISTS"
[[ -f "${ENV_FILE}" ]] && pass "ENV_FILE_EXISTS" || warn "ENV_FILE_EXISTS"
[[ -d "${DATA_DIR}" ]] && pass "DATA_DIR_EXISTS" || fail_check "DATA_DIR_EXISTS"
[[ -d "${LOG_DIR}" ]] && pass "LOG_DIR_EXISTS" || fail_check "LOG_DIR_EXISTS"
[[ -x "${VENV_DIR}/bin/python" ]] && pass "PYTHON_VENV_EXISTS" || fail_check "PYTHON_VENV_EXISTS"

if [[ -x "${VENV_DIR}/bin/python" ]]; then
  if "${VENV_DIR}/bin/python" -m "${APP_PACKAGE}.cli" --config "${CONFIG_FILE}" version >/tmp/ameli_app_version.txt 2>/tmp/ameli_app_version.err; then
    pass "CLI_VERSION_COMMAND"
  else
    fail_check "CLI_VERSION_COMMAND"
  fi

  if "${VENV_DIR}/bin/python" -m "${APP_PACKAGE}.cli" --config "${CONFIG_FILE}" config-check >/tmp/ameli_app_config_check.json 2>/tmp/ameli_app_config_check.err; then
    pass "CONFIG_CHECK"
  else
    fail_check "CONFIG_CHECK"
  fi

  if "${VENV_DIR}/bin/python" -m "${APP_PACKAGE}.cli" --config "${CONFIG_FILE}" db-status >/tmp/ameli_app_db_status.json 2>/tmp/ameli_app_db_status.err; then
    pass "DB_STATUS_COMMAND"
  else
    fail_check "DB_STATUS_COMMAND"
  fi

  if "${VENV_DIR}/bin/python" "${APP_DIR}/manage.py" check >/tmp/ameli_app_manage_check.txt 2>/tmp/ameli_app_manage_check.err; then
    pass "DJANGO_CHECK"
  else
    fail_check "DJANGO_CHECK"
  fi
fi

if command -v systemctl >/dev/null 2>&1; then
  local_unit=""
  for local_unit in "${ENABLED_SERVICE_UNITS[@]}"; do
    if systemctl is-enabled --quiet "${local_unit}"; then
      pass "ENABLED ${local_unit}"
    else
      warn "ENABLED ${local_unit}"
    fi

    # ActiveState alone is not enough: with Type=simple systemd reports
    # "active" from the instant it execs, so a process crash-looping on a
    # bind error samples as healthy about half the time. Require the
    # running substate, and surface the restart counter that gives a loop
    # away.
    unit_state="$(systemctl show -p ActiveState --value "${local_unit}" 2>/dev/null || echo unknown)"
    unit_sub="$(systemctl show -p SubState --value "${local_unit}" 2>/dev/null || echo unknown)"
    if [[ "${unit_state}" == "active" && "${unit_sub}" == "running" ]]; then
      pass "ACTIVE ${local_unit}"
    else
      warn "ACTIVE ${local_unit} (${unit_state}/${unit_sub})"
    fi

    unit_restarts="$(systemctl show -p NRestarts --value "${local_unit}" 2>/dev/null || echo 0)"
    if [[ "${unit_restarts:-0}" -gt 0 ]]; then
      warn "RESTART_LOOP ${local_unit} (NRestarts=${unit_restarts})"
    fi
  done

  for local_unit in "${ENABLED_TIMER_UNITS[@]}"; do
    if systemctl is-enabled --quiet "${local_unit}"; then
      pass "ENABLED ${local_unit}"
    else
      warn "ENABLED ${local_unit}"
    fi

    if systemctl is-active --quiet "${local_unit}"; then
      pass "ACTIVE ${local_unit}"
    else
      warn "ACTIVE ${local_unit}"
    fi
  done
else
  warn "SYSTEMCTL_NOT_AVAILABLE"
fi

# The authoritative liveness check. Everything above inspects files and
# systemd bookkeeping; only this one proves the deploy actually serves.
# It is a FAIL, not a WARN: a RESUMEN with zero failures is what an
# operator reads as "this deploy is healthy", and until now that summary
# could come back clean while the API answered nothing at all.
if [[ " ${ENABLED_SERVICE_UNITS[*]} " == *" $(service_unit_name api) "* ]]; then
  if smoke_health; then
    pass "HEALTH_ENDPOINT"
  else
    fail_check "HEALTH_ENDPOINT"
  fi
fi

echo "RESUMEN: OK=${OK} WARN=${WARN} FAIL=${FAIL}"
[[ "${FAIL}" -eq 0 ]]
