#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$(cd "${SCRIPT_DIR}/.." && pwd)"

APP_NAME="${APP_NAME:-AMELI App Template}"
APP_SLUG="${APP_SLUG:-ameli-app}"
APP_PACKAGE="${APP_PACKAGE:-ameli_app}"
APP_ENV="${APP_ENV:-dev}"

case "${APP_ENV}" in
  prod | dev) ;;
  *)
    echo "APP_ENV invalido: ${APP_ENV}. Use prod o dev." >&2
    exit 1
    ;;
esac

DEFAULT_API_PORT="8080"
DEFAULT_WEB_PORT="8081"
if [[ "${APP_ENV}" == "dev" ]]; then
  DEFAULT_API_PORT="18080"
  DEFAULT_WEB_PORT="18081"
fi

APP_INSTANCE="${APP_INSTANCE:-${APP_SLUG}-${APP_ENV}}"
UNIT_PREFIX="${UNIT_PREFIX:-${APP_SLUG}-${APP_ENV}}"

APP_DIR="${APP_DIR:-/opt/${APP_INSTANCE}}"
ETC_DIR="${ETC_DIR:-/etc/${APP_INSTANCE}}"
DATA_DIR="${DATA_DIR:-/var/lib/${APP_INSTANCE}}"
LOG_DIR="${LOG_DIR:-/var/log/${APP_INSTANCE}}"
BACKUP_DIR="${BACKUP_DIR:-/var/backups/${APP_INSTANCE}}"
RUN_USER="${RUN_USER:-${APP_INSTANCE}}"
RUN_GROUP="${RUN_GROUP:-${APP_INSTANCE}}"
VENV_DIR="${APP_DIR}/.venv"
ENV_FILE="${ETC_DIR}/app.env"
CONFIG_FILE="${ETC_DIR}/app.yaml"
SYSTEMD_DIR="${SYSTEMD_DIR:-/etc/systemd/system}"

load_env_file() {
  local env_path="$1"
  [[ -f "${env_path}" ]] || return 0

  while IFS= read -r raw_line || [[ -n "${raw_line}" ]]; do
    local line key value
    line="${raw_line#"${raw_line%%[![:space:]]*}"}"
    [[ -z "${line}" || "${line}" == \#* || "${line}" != *=* ]] && continue

    key="${line%%=*}"
    value="${line#*=}"
    key="${key//[[:space:]]/}"
    value="${value#"${value%%[![:space:]]*}"}"
    value="${value%"${value##*[![:space:]]}"}"
    value="${value#\"}"
    value="${value%\"}"
    value="${value#\'}"
    value="${value%\'}"

    if [[ -z "${!key+x}" ]]; then
      export "${key}=${value}"
    fi
  done < "${env_path}"
}

load_env_file "${ENV_FILE}"

AMELI_APP_HOST="${AMELI_APP_HOST:-127.0.0.1}"
AMELI_APP_API_PORT="${AMELI_APP_API_PORT:-${DEFAULT_API_PORT}}"
AMELI_APP_WEB_PORT="${AMELI_APP_WEB_PORT:-${DEFAULT_WEB_PORT}}"
AMELI_APP_NOTIFIER_INTERVAL="${AMELI_APP_NOTIFIER_INTERVAL:-30}"
APP_LOG_LEVEL="${APP_LOG_LEVEL:-INFO}"
APP_SYSTEMD_PROFILE="${APP_SYSTEMD_PROFILE:-api-worker-maintenance}"

ALL_UNIT_SUFFIXES=(
  "api.service"
  "web.service"
  "worker.service"
  "worker.timer"
  "capture.service"
  "capture.timer"
  "capture@.service"
  "capture-primary.timer"
  "capture-secondary.timer"
  "notifier.service"
  "maintenance.service"
  "maintenance.timer"
)

log() {
  printf '[%s] %s\n' "$(date '+%Y-%m-%d %H:%M:%S')" "$*"
}

fail() {
  # Honour an explicit exit code passed as the FIRST positional arg if
  # it looks numeric — callers like backup.sh document distinct codes
  # so a monitor can categorise the failure (1 = generic, 2 = DB dump
  # failed, etc.). Without the arg we exit 1 by default, matching the
  # historical behaviour.
  local code=1
  if [[ "${1:-}" =~ ^[0-9]+$ ]]; then
    code="$1"
    shift
  fi
  echo "ERROR: $*" >&2
  exit "$code"
}

bool_is_true() {
  case "$(printf '%s' "${1:-}" | tr '[:upper:]' '[:lower:]')" in
    1 | true | yes | on | y) return 0 ;;
    *) return 1 ;;
  esac
}

add_unique() {
  local name="$1"
  shift
  local current
  for current in "$@"; do
    [[ "${current}" == "${name}" ]] && return 0
  done
  return 1
}

service_unit_name() {
  printf '%s-%s.service\n' "${UNIT_PREFIX}" "$1"
}

timer_unit_name() {
  printf '%s-%s.timer\n' "${UNIT_PREFIX}" "$1"
}

known_unit_name() {
  printf '%s-%s\n' "${UNIT_PREFIX}" "$1"
}

require_root() {
  if [[ "${EUID:-$(id -u)}" -ne 0 ]]; then
    fail "Este script debe ejecutarse como root."
  fi
}

ensure_user_group() {
  getent group "${RUN_GROUP}" >/dev/null 2>&1 || groupadd --system "${RUN_GROUP}"
  id "${RUN_USER}" >/dev/null 2>&1 || useradd \
    --system \
    --gid "${RUN_GROUP}" \
    --home-dir "${DATA_DIR}" \
    --shell /usr/sbin/nologin \
    "${RUN_USER}"
}

make_dirs() {
  mkdir -p "${APP_DIR}" "${ETC_DIR}" "${DATA_DIR}" "${LOG_DIR}" "${BACKUP_DIR}"
  chown root:"${RUN_GROUP}" "${ETC_DIR}" || true
  chmod 750 "${ETC_DIR}" || true
  chown -R "${RUN_USER}:${RUN_GROUP}" "${DATA_DIR}" "${LOG_DIR}" "${BACKUP_DIR}" || true
  chmod 750 "${DATA_DIR}" "${LOG_DIR}" "${BACKUP_DIR}" || true
}

copy_if_missing() {
  local src="$1" dst="$2" mode="${3:-640}"
  if [[ ! -f "${dst}" ]]; then
    cp "${src}" "${dst}"
    chmod "${mode}" "${dst}" || true
    chown root:"${RUN_GROUP}" "${dst}" || true
    log "Creado: ${dst}"
  else
    log "Preservado: ${dst}"
  fi
}

set_env() {
  local key="$1" value="$2"
  mkdir -p "$(dirname "${ENV_FILE}")"
  touch "${ENV_FILE}"
  chmod 640 "${ENV_FILE}" || true
  chown root:"${RUN_GROUP}" "${ENV_FILE}" || true
  if grep -q "^${key}=" "${ENV_FILE}" 2>/dev/null; then
    sed -i "s|^${key}=.*|${key}=${value}|" "${ENV_FILE}"
  else
    printf '%s=%s\n' "${key}" "${value}" >> "${ENV_FILE}"
  fi
}

default_env() {
  local key="$1" value="${2:-}"
  mkdir -p "$(dirname "${ENV_FILE}")"
  touch "${ENV_FILE}"
  chmod 640 "${ENV_FILE}" || true
  chown root:"${RUN_GROUP}" "${ENV_FILE}" || true
  grep -q "^${key}=" "${ENV_FILE}" 2>/dev/null || printf '%s=%s\n' "${key}" "${value}" >> "${ENV_FILE}"
}

install_system_packages() {
  if command -v apt-get >/dev/null 2>&1; then
    apt-get update -y
    apt-get install -y python3 python3-venv python3-pip rsync curl jq
  fi
}

copy_project_tree() {
  if command -v rsync >/dev/null 2>&1; then
    rsync -a --delete \
      --exclude ".git" \
      --exclude ".venv" \
      --exclude ".pytest_cache" \
      --exclude ".test-deps" \
      --exclude "__pycache__" \
      --exclude "*.pyc" \
      "${PROJECT_DIR}/" "${APP_DIR}/"
  else
    find "${APP_DIR}" -mindepth 1 -maxdepth 1 ! -name ".venv" -exec rm -rf {} +
    (
      cd "${PROJECT_DIR}" && tar \
        --exclude=".git" \
        --exclude=".venv" \
        --exclude=".pytest_cache" \
        --exclude=".test-deps" \
        --exclude="__pycache__" \
        --exclude="*.pyc" \
        -cf - .
    ) | (
      cd "${APP_DIR}" && tar -xf -
    )
  fi
}

initialize_runtime_env() {
  copy_if_missing "${APP_DIR}/.env.example" "${ENV_FILE}" 640
  copy_if_missing "${APP_DIR}/config/app.yaml.example" "${CONFIG_FILE}" 640

  set_env APP_ENV "${APP_ENV}"
  set_env APP_CONFIG "${CONFIG_FILE}"
  default_env APP_LOG_LEVEL "${APP_LOG_LEVEL}"
  default_env APP_SYSTEMD_PROFILE "${APP_SYSTEMD_PROFILE}"
  default_env AMELI_APP_HOST "${AMELI_APP_HOST}"
  default_env AMELI_APP_API_PORT "${AMELI_APP_API_PORT}"
  default_env AMELI_APP_WEB_PORT "${AMELI_APP_WEB_PORT}"
  default_env AMELI_APP_NOTIFIER_INTERVAL "${AMELI_APP_NOTIFIER_INTERVAL}"
  default_env AMELI_APP_REQUIRE_TOKEN "false"
  default_env AMELI_APP_API_TOKEN "change-me"
  default_env DATABASE_URL ""
}

install_python_deps() {
  python3 -m venv "${VENV_DIR}"
  "${VENV_DIR}/bin/python" -m pip install --upgrade pip setuptools wheel
  # ASVS V14.2.3 — install runtime deps under ``--require-hashes`` so
  # any package whose archive does not match a sha256 in the lockfile
  # gets refused. Protects the deploy against a rotated wheel on PyPI
  # or a typosquat that slipped through code review. Pre-lockfile
  # deploys (one-shot upgrade path) fall back to the range-pinned
  # source list with a warning; fresh provisions always hit the lock.
  if [ -f "${APP_DIR}/requirements.lock" ]; then
    "${VENV_DIR}/bin/python" -m pip install --require-hashes -r "${APP_DIR}/requirements.lock"
  else
    echo "WARN: requirements.lock not found, falling back to requirements.txt (no hash verification)" >&2
    "${VENV_DIR}/bin/python" -m pip install -r "${APP_DIR}/requirements.txt"
  fi
  "${VENV_DIR}/bin/python" -m pip install -e "${APP_DIR}" --no-deps
}

repair_permissions() {
  chown -R root:root "${APP_DIR}" || true
  find "${APP_DIR}" -type d -exec chmod 755 {} \; || true
  find "${APP_DIR}" -type f -exec chmod 644 {} \; || true
  find "${APP_DIR}/scripts" -type f -name "*.sh" -exec chmod 755 {} \; || true

  if [[ -d "${VENV_DIR}" ]]; then
    chown -R "${RUN_USER}:${RUN_GROUP}" "${VENV_DIR}" || true
    find "${VENV_DIR}" -type d -exec chmod 755 {} \; || true
    find "${VENV_DIR}" -type f -exec chmod u+rw,g+r,o-rwx {} \; || true
    find "${VENV_DIR}/bin" -type f -exec chmod u+rwx,g+rx,o-rwx {} \; 2>/dev/null || true
  fi

  chown root:"${RUN_GROUP}" "${ETC_DIR}" || true
  chmod 750 "${ETC_DIR}" || true
  [[ -f "${ENV_FILE}" ]] && chown root:"${RUN_GROUP}" "${ENV_FILE}" || true
  [[ -f "${ENV_FILE}" ]] && chmod 640 "${ENV_FILE}" || true
  [[ -f "${CONFIG_FILE}" ]] && chown root:"${RUN_GROUP}" "${CONFIG_FILE}" || true
  [[ -f "${CONFIG_FILE}" ]] && chmod 640 "${CONFIG_FILE}" || true

  chown -R "${RUN_USER}:${RUN_GROUP}" "${DATA_DIR}" "${LOG_DIR}" "${BACKUP_DIR}" || true
  find "${DATA_DIR}" "${LOG_DIR}" "${BACKUP_DIR}" -type d -exec chmod 750 {} \; 2>/dev/null || true
  find "${DATA_DIR}" "${LOG_DIR}" "${BACKUP_DIR}" -type f -exec chmod 640 {} \; 2>/dev/null || true
}

render_systemd_units() {
  local src basename suffix target
  for src in "${APP_DIR}/deploy/systemd/"*.service "${APP_DIR}/deploy/systemd/"*.timer; do
    [[ -f "${src}" ]] || continue
    basename="$(basename "${src}")"
    suffix="${basename#ameli-app-}"
    target="${SYSTEMD_DIR}/${UNIT_PREFIX}-${suffix}"

    sed \
      -e "s|__APP_NAME__|${APP_NAME}|g" \
      -e "s|__APP_SLUG__|${APP_SLUG}|g" \
      -e "s|__APP_ENV__|${APP_ENV}|g" \
      -e "s|__APP_DIR__|${APP_DIR}|g" \
      -e "s|__DATA_DIR__|${DATA_DIR}|g" \
      -e "s|__LOG_DIR__|${LOG_DIR}|g" \
      -e "s|__BACKUP_DIR__|${BACKUP_DIR}|g" \
      -e "s|__ENV_FILE__|${ENV_FILE}|g" \
      -e "s|__CONFIG_FILE__|${CONFIG_FILE}|g" \
      -e "s|__RUN_USER__|${RUN_USER}|g" \
      -e "s|__RUN_GROUP__|${RUN_GROUP}|g" \
      -e "s|__APP_PACKAGE__|${APP_PACKAGE}|g" \
      -e "s|__UNIT_PREFIX__|${UNIT_PREFIX}|g" \
      -e "s|__API_PORT__|${AMELI_APP_API_PORT}|g" \
      -e "s|__WEB_PORT__|${AMELI_APP_WEB_PORT}|g" \
      -e "s|__NOTIFIER_INTERVAL__|${AMELI_APP_NOTIFIER_INTERVAL}|g" \
      "${src}" > "${target}"
    chmod 644 "${target}"
  done

  systemctl daemon-reload
}

disable_known_units() {
  local suffix unit
  for suffix in "${ALL_UNIT_SUFFIXES[@]}"; do
    unit="${UNIT_PREFIX}-${suffix}"
    systemctl disable --now "${unit}" 2>/dev/null || true
    rm -f "${SYSTEMD_DIR}/${unit}"
  done
  systemctl daemon-reload || true
  systemctl reset-failed 2>/dev/null || true
}

resolve_systemd_profile() {
  ENABLED_SERVICE_UNITS=()
  ENABLED_TIMER_UNITS=()

  case "${APP_SYSTEMD_PROFILE}" in
    api-worker-maintenance)
      # The notifier daemon drains the OutboundEmail retry queue every
      # ~30 s (AMELI_APP_NOTIFIER_INTERVAL). Without it, queued mails
      # sit indefinitely until an operator runs ``notify-once`` by
      # hand, which defeats the purpose of having a retry queue.
      ENABLED_SERVICE_UNITS=("$(service_unit_name api)" "$(service_unit_name notifier)")
      ENABLED_TIMER_UNITS=("$(timer_unit_name worker)" "$(timer_unit_name maintenance)")
      ;;
    api-web)
      ENABLED_SERVICE_UNITS=("$(service_unit_name api)" "$(service_unit_name web)")
      ;;
    api-web-worker-maintenance)
      ENABLED_SERVICE_UNITS=("$(service_unit_name api)" "$(service_unit_name web)" "$(service_unit_name notifier)")
      ENABLED_TIMER_UNITS=("$(timer_unit_name worker)" "$(timer_unit_name maintenance)")
      ;;
    web-worker)
      ENABLED_SERVICE_UNITS=("$(service_unit_name web)")
      ENABLED_TIMER_UNITS=("$(timer_unit_name worker)")
      ;;
    web-capture)
      ENABLED_SERVICE_UNITS=("$(service_unit_name web)")
      ENABLED_TIMER_UNITS=("$(timer_unit_name capture)")
      ;;
    api-web-capture)
      ENABLED_SERVICE_UNITS=("$(service_unit_name api)" "$(service_unit_name web)")
      ENABLED_TIMER_UNITS=("$(timer_unit_name capture)")
      ;;
    api-capture-notifier-maintenance)
      ENABLED_SERVICE_UNITS=("$(service_unit_name api)" "$(service_unit_name notifier)")
      ENABLED_TIMER_UNITS=(
        "$(timer_unit_name capture-primary)"
        "$(timer_unit_name capture-secondary)"
        "$(timer_unit_name maintenance)"
      )
      ;;
    *)
      fail "APP_SYSTEMD_PROFILE invalido: ${APP_SYSTEMD_PROFILE}"
      ;;
  esac
}

enable_selected_units() {
  local unit
  for unit in "${ENABLED_SERVICE_UNITS[@]}"; do
    systemctl enable --now "${unit}"
  done
  for unit in "${ENABLED_TIMER_UNITS[@]}"; do
    systemctl enable --now "${unit}"
  done
}

restart_selected_units() {
  local unit
  for unit in "${ENABLED_SERVICE_UNITS[@]}"; do
    systemctl restart "${unit}" || true
  done
  for unit in "${ENABLED_TIMER_UNITS[@]}"; do
    systemctl restart "${unit}" || true
  done
}
