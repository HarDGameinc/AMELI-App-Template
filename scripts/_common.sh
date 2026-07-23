#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$(cd "${SCRIPT_DIR}/.." && pwd)"

APP_NAME="${APP_NAME:-AMELI App Template}"

# Auto-detect APP_SLUG when not exported. Convention: the install
# layout puts code at /opt/<slug>-<env>/ and config at
# /etc/<slug>-<env>/, with PROJECT_DIR equal to the code path
# above. So PROJECT_DIR basename minus the trailing env suffix
# is the slug -- matches what install.sh wrote 1:1, and matches
# manage.py's _candidate_slugs auto-detection. Required because
# interactive invocations of backup.sh/uninstall.sh/update.sh
# without APP_SLUG= used to fall back to the literal default
# "ameli-app" and look at the wrong /etc path. The conservative
# fallback (literal "ameli-app") is preserved for the case where
# the checkout dir doesn't follow the convention.
if [[ -z "${APP_SLUG:-}" ]]; then
    _project_dir_basename="$(basename "${PROJECT_DIR}")"
    if [[ "${_project_dir_basename}" == *-dev ]]; then
        APP_SLUG="${_project_dir_basename%-dev}"
    elif [[ "${_project_dir_basename}" == *-prod ]]; then
        APP_SLUG="${_project_dir_basename%-prod}"
    else
        APP_SLUG="ameli-app"
    fi
fi

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
  "backup.service"
  "backup.timer"
  "verify-audit.service"
  "verify-audit.timer"
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

# Sets COPY_IF_MISSING_CREATED to 1 when it actually wrote the file, 0 when
# it preserved an existing one. Callers that need to post-process a freshly
# seeded file (render_config_file) read that flag instead of a return code,
# which under ``set -e`` would abort the install on the "preserved" path.
COPY_IF_MISSING_CREATED=0
copy_if_missing() {
  local src="$1" dst="$2" mode="${3:-640}"
  COPY_IF_MISSING_CREATED=0
  if [[ ! -f "${dst}" ]]; then
    cp "${src}" "${dst}"
    chmod "${mode}" "${dst}" || true
    chown root:"${RUN_GROUP}" "${dst}" || true
    COPY_IF_MISSING_CREATED=1
    log "Creado: ${dst}"
  else
    log "Preservado: ${dst}"
  fi
}

# ``config/app.yaml.example`` doubles as the local-dev config, so it ships
# with working *relative* paths and a hardcoded "dev" environment. Copying
# it verbatim into an install is wrong on both counts:
#
#   * ``environment: "dev"`` disables every fail-closed prod guard.
#   * ``profile_uploads_dir`` / ``paths.*`` stay relative, so they resolve
#     inside ${APP_DIR} — and settings/i18n_static.py refuses to boot with
#     MEDIA_ROOT or data_dir inside the checkout (a redeploy would wipe
#     user uploads). Note MEDIA_ROOT derives from ``profile_uploads_dir``,
#     not from ``paths.data_dir`` (see ameli_app/config.py).
#
# So rewrite those keys to the instance's real values right after seeding.
# Anchored on the exact indentation each key has in the example file; only
# ever called on a file we just created, never on an operator-edited one.
# ``.env.example`` is the local-dev env file, and dev wants things prod
# must never have. Copying it verbatim into /etc/<instance>/app.env seeds:
#
#   * AMELI_APP_DJANGO_DEBUG=true       -> base.py refuses to boot (loud)
#   * AMELI_APP_SESSION_COOKIE_NAME=... -> cookies.py reads any explicit
#     name as a deliberate operator override and skips the ASVS V3.4.4
#     ``__Host-`` prefix policy (silent downgrade)
#   * AMELI_APP_SESSION_COOKIE_SECURE=false -> session cookie without the
#     Secure flag behind TLS (silent downgrade)
#
# The last two are the dangerous ones: they do not fail, they just make
# the deploy quietly weaker than the template promises. Outside dev,
# rewrite them to the safe values. Only ever called on a file we just
# created -- an operator who deliberately set these keeps them.
render_env_file() {
  [[ -f "${ENV_FILE}" ]] || return 0

  # Runtime values first, for EVERY environment. ``.env.example`` ships
  # the dev host/ports, and ``default_env`` only writes a key that is
  # MISSING -- so the seeded dev values silently outranked both the
  # per-environment defaults and an explicit
  # ``AMELI_APP_API_PORT=... bash scripts/install.sh``. The operator got
  # no error: systemd units were rendered from the resolved value while
  # the app read the stale one from this file, so the deploy listened on
  # a port nobody asked for -- on a host with several apps, potentially
  # one that belongs to a different instance.
  #
  # These are the values _common.sh already resolved (explicit export >
  # existing app.env via load_env_file > per-env default), so writing
  # them here keeps the env file and the units in agreement.
  sed -i \
    -e "s|^AMELI_APP_HOST=.*|AMELI_APP_HOST=${AMELI_APP_HOST}|" \
    -e "s|^AMELI_APP_API_PORT=.*|AMELI_APP_API_PORT=${AMELI_APP_API_PORT}|" \
    -e "s|^AMELI_APP_WEB_PORT=.*|AMELI_APP_WEB_PORT=${AMELI_APP_WEB_PORT}|" \
    -e "s|^AMELI_APP_NOTIFIER_INTERVAL=.*|AMELI_APP_NOTIFIER_INTERVAL=${AMELI_APP_NOTIFIER_INTERVAL}|" \
    -e "s|^APP_LOG_LEVEL=.*|APP_LOG_LEVEL=${APP_LOG_LEVEL}|" \
    -e "s|^APP_SYSTEMD_PROFILE=.*|APP_SYSTEMD_PROFILE=${APP_SYSTEMD_PROFILE}|" \
    "${ENV_FILE}"
  log "Env renderizada: host=${AMELI_APP_HOST} api=${AMELI_APP_API_PORT} web=${AMELI_APP_WEB_PORT}"

  [[ "${APP_ENV}" == "dev" ]] && return 0
  sed -i \
    -e "s|^AMELI_APP_DJANGO_DEBUG=.*|AMELI_APP_DJANGO_DEBUG=false|" \
    -e "s|^AMELI_APP_SESSION_COOKIE_SECURE=.*|AMELI_APP_SESSION_COOKIE_SECURE=true|" \
    -e "/^AMELI_APP_SESSION_COOKIE_NAME=/d" \
    "${ENV_FILE}"
  log "Env renderizada para ${APP_ENV}: DEBUG=false, cookie Secure, prefijo __Host- activo"
}

# The systemd units are rendered from the shell values while the running
# process reads the env file, so any drift between the two means the
# deploy listens somewhere nobody declared. Instances provisioned before
# render_env_file existed carry exactly that drift.
warn_port_drift() {
  [[ -f "${ENV_FILE}" ]] || return 0
  local key resolved current
  for key in AMELI_APP_API_PORT AMELI_APP_WEB_PORT AMELI_APP_HOST; do
    resolved="${!key}"
    current="$(sed -n "s|^${key}=||p" "${ENV_FILE}" | tail -n1)"
    if [[ -n "${current}" && "${current}" != "${resolved}" ]]; then
      log "WARN: ${ENV_FILE} tiene ${key}=${current} pero las units se" \
          "renderizan con ${resolved}. El servicio va a escuchar en" \
          "${current}: corregi el archivo o reinstala con ${key}=${current}."
    fi
  done
}

# Runs on every install, including upgrades of an instance provisioned by
# an older version that seeded the dev values above. Never rewrites an
# existing file -- just refuses to let the downgrade pass unnoticed.
warn_insecure_prod_env() {
  [[ "${APP_ENV}" == "dev" ]] && return 0
  [[ -f "${ENV_FILE}" ]] || return 0
  if grep -qiE '^AMELI_APP_DJANGO_DEBUG=(true|1|yes|on)' "${ENV_FILE}"; then
    log "WARN: ${ENV_FILE} tiene AMELI_APP_DJANGO_DEBUG activo en ${APP_ENV}."
  fi
  if grep -qiE '^AMELI_APP_SESSION_COOKIE_SECURE=(false|0|no|off)' "${ENV_FILE}"; then
    log "WARN: ${ENV_FILE} tiene SESSION_COOKIE_SECURE=false en ${APP_ENV};" \
        "la cookie de sesion viaja sin flag Secure."
  fi
  if grep -q '^AMELI_APP_SESSION_COOKIE_NAME=.' "${ENV_FILE}"; then
    log "WARN: ${ENV_FILE} fija SESSION_COOKIE_NAME; eso desactiva el" \
        "prefijo __Host- (ASVS V3.4.4). Borra la linea salvo que sea intencional."
  fi
  local _hma
  _hma="$(sed -n 's/^AMELI_APP_HEALTH_METRICS_ALLOWLIST=//p' "${ENV_FILE}" | tail -n1)"
  if [[ -z "${_hma}" ]]; then
    log "WARN: ${ENV_FILE} no restringe /health ni /metrics (allowlist vacia)" \
        "en ${APP_ENV}: filtran version, uptime, disco y metricas a cualquiera" \
        "que alcance el proxy. Setea AMELI_APP_HEALTH_METRICS_ALLOWLIST=127.0.0.1,::1" \
        "(mas las IP de tus monitores externos, si los hay)."
  fi
}

render_config_file() {
  local target="$1"
  [[ -f "${target}" ]] || return 0

  # settings/email.py refuses to boot outside dev on the console backend:
  # it keeps mail in memory, so password reset and MFA-by-email fail
  # silently and the operator only finds out when a user is locked out.
  # "file" is the safe seed -- it writes .eml to <data_dir>/outbox, so
  # nothing is lost and the deploy boots. The operator switches to "smtp"
  # via `ameli-app configure` once there are real credentials.
  local email_backend="console"
  [[ "${APP_ENV}" != "dev" ]] && email_backend="file"

  sed -i \
    -e "s|^  backend: .*|  backend: \"${email_backend}\"|" \
    -e "s|^  slug: .*|  slug: \"${APP_SLUG}\"|" \
    -e "s|^  environment: .*|  environment: \"${APP_ENV}\"|" \
    -e "s|^  profile_uploads_dir: .*|  profile_uploads_dir: \"${DATA_DIR}/uploads\"|" \
    -e "s|^  data_dir: .*|  data_dir: \"${DATA_DIR}\"|" \
    -e "s|^  log_dir: .*|  log_dir: \"${LOG_DIR}\"|" \
    -e "s|^  backup_dir: .*|  backup_dir: \"${BACKUP_DIR}\"|" \
    "${target}"
  log "Config renderizada para ${APP_INSTANCE}: ${target}"
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

# Generate a value with the given python3 one-liner and append to the env
# file — but ONLY if the key is missing. Never overwrites; safe to re-run
# across upgrades. Used to auto-provision the three crypto keys the prod
# fail-closed guards require (SECRET_KEY, AUDIT_HMAC_KEY,
# MFA_ENCRYPTION_KEY). See DECISIONS #10.
gen_env_if_missing() {
  local key="$1" generator="$2"
  mkdir -p "$(dirname "${ENV_FILE}")"
  touch "${ENV_FILE}"
  chmod 640 "${ENV_FILE}" || true
  chown root:"${RUN_GROUP}" "${ENV_FILE}" || true
  if ! grep -q "^${key}=" "${ENV_FILE}" 2>/dev/null; then
    local value
    value="$(python3 -c "${generator}")"
    printf '%s=%s\n' "${key}" "${value}" >> "${ENV_FILE}"
    log "  generated ${key}"
  fi
}

# Comma-separated ALLOWED_HOSTS for this box: loopback first, then whatever
# names the host answers to. Deduplicated, order preserved. Falls back to
# loopback alone when `hostname` is unavailable -- enough for the install to
# boot and for the smoke check to pass.
detect_allowed_hosts() {
  # No "::1" here: ALLOWED_HOSTS is matched against the Host header, where
  # a literal IPv6 address arrives bracketed ("[::1]"), so a bare "::1"
  # entry never matches. TRUSTED_PROXIES is a different comparison
  # (REMOTE_ADDR) and does take the bare form.
  local candidates=("127.0.0.1" "localhost")
  local name
  for name in "$(hostname 2>/dev/null || true)" "$(hostname -f 2>/dev/null || true)"; do
    [[ -n "${name}" ]] && candidates+=("${name}")
  done

  local out="" item
  for item in "${candidates[@]}"; do
    [[ -n "${item}" ]] || continue
    [[ "${item}" == "*" ]] && continue
    case ",${out}," in
      *",${item},"*) continue ;;
    esac
    out="${out:+${out},}${item}"
  done
  printf '%s' "${out}"
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
  local env_file_created="${COPY_IF_MISSING_CREATED}"
  if [[ "${env_file_created}" == "1" ]]; then
    render_env_file
  fi
  copy_if_missing "${APP_DIR}/config/app.yaml.example" "${CONFIG_FILE}" 640
  if [[ "${COPY_IF_MISSING_CREATED}" == "1" ]]; then
    render_config_file "${CONFIG_FILE}"
  fi

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

  # Seed the two fail-closed guards in settings/base.py that have no safe
  # default outside dev. Without these a fresh prod install cannot boot at
  # all -- not `migrate`, not `check`, not the configure wizard that is
  # supposed to set them. Seeding a conservative, correct-by-construction
  # value breaks that circularity; the operator narrows it later via
  # `ameli-app configure`.
  #
  # ALLOWED_HOSTS: loopback (the post-install smoke check hits
  # 127.0.0.1:<api_port>/health) plus this host's own names. Never "*" --
  # base.py rejects wildcards outside dev, and rightly so.
  default_env AMELI_APP_DJANGO_ALLOWED_HOSTS "$(detect_allowed_hosts)"
  # TRUSTED_PROXIES: loopback only, which is the correct answer for the
  # documented topology (Caddy terminating TLS on the same host).
  default_env AMELI_APP_TRUSTED_PROXIES "127.0.0.1,::1"

  # Auto-provision the three crypto keys the prod fail-closed guards
  # require (base.py: SECRET_KEY; auth.py: AUDIT_HMAC_KEY,
  # MFA_ENCRYPTION_KEY). Idempotent — never overwrites an existing value
  # so an in-place upgrade keeps working session/audit/MFA state.
  # MFA_ENCRYPTION_KEY uses the same shape ``Fernet.generate_key()``
  # emits: base64.urlsafe_b64encode(os.urandom(32)).
  gen_env_if_missing AMELI_APP_DJANGO_SECRET_KEY \
    'import secrets; print(secrets.token_urlsafe(60))'
  gen_env_if_missing AMELI_APP_AUDIT_HMAC_KEY \
    'import secrets; print(secrets.token_urlsafe(48))'
  gen_env_if_missing AMELI_APP_MFA_ENCRYPTION_KEY \
    'import base64, os; print(base64.urlsafe_b64encode(os.urandom(32)).decode())'

  # /health and /metrics are world-readable by default (settings/
  # integrations.py: "public for probes"). Through a reverse proxy that
  # means version, uptime, disk and the full Prometheus scrape leak to
  # anyone who can reach the public port -- version alone hands an
  # attacker a CVE shortlist. Outside dev, lock them to loopback: the
  # post-install smoke and validate_installation hit 127.0.0.1:<port>/
  # health directly (client_ip = 127.0.0.1, allowed), while anything
  # arriving through the proxy is refused. The operator adds external
  # monitor IPs explicitly. Dev stays open so local probes work.
  #
  # Fail-OPEN (empty = exposed), unlike ALLOWED_HOSTS above, so it is
  # only seeded on a FRESH env file: an existing prod instance that
  # deliberately serves /metrics to an external scraper is not silently
  # locked down on an in-place upgrade -- warn_insecure_prod_env flags it
  # instead, and the operator decides.
  if [[ "${APP_ENV}" != "dev" && "${env_file_created}" == "1" ]]; then
    default_env AMELI_APP_HEALTH_METRICS_ALLOWLIST "127.0.0.1,::1"
  fi

  warn_port_drift
  warn_insecure_prod_env
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

# Probe the API's own /health. This is the only trustworthy liveness
# signal: with Type=simple, systemd marks a unit "active" the moment it
# execs, before the process has bound its port -- so `systemctl is-active`
# returns success for a service that is crash-looping on a bind error.
# That is not a rare race: the same install reported [WARN] ACTIVE on one
# run and [OK] ACTIVE on the next with nothing changed but the sampling
# instant. Shared by install.sh and validate_installation.sh so both
# agree on what "up" means.
smoke_health() {
  local url="http://127.0.0.1:${AMELI_APP_API_PORT:-18080}/health"
  local attempt
  # Up to ~15s: a first boot right after migrate can be slow on cold caches.
  for attempt in $(seq 1 15); do
    if curl -fsS --max-time 2 "${url}" >/dev/null 2>&1; then
      log "  /health ${url} -> 200 (attempt ${attempt})"
      return 0
    fi
    sleep 1
  done
  log "  /health ${url} did not answer in 15s"
  log "  check: journalctl -u $(service_unit_name api) --since '2 minutes ago'"
  return 1
}

repair_permissions() {
  chown -R root:root "${APP_DIR}" || true

  # Skip .git entirely. The documented install clones straight into
  # /opt/<instance>, so APP_DIR *is* the git checkout: a blanket chmod
  # rewrites git's own internals and leaves every file whose recorded
  # mode differs showing as modified -- which makes the documented
  # update path (`git pull` + reinstall) abort with "local changes
  # would be overwritten". The repo mode of scripts/*.sh and of
  # deploy/git-hooks/* is kept in sync with what this function applies,
  # so a reinstall leaves the checkout clean.
  find "${APP_DIR}" -name .git -prune -o -type d -exec chmod 755 {} \; || true
  find "${APP_DIR}" -name .git -prune -o -type f -exec chmod 644 {} \; || true
  find "${APP_DIR}/scripts" -type f -name "*.sh" -exec chmod 755 {} \; || true
  if [[ -d "${APP_DIR}/deploy/git-hooks" ]]; then
    find "${APP_DIR}/deploy/git-hooks" -type f -exec chmod 755 {} \; || true
  fi

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

  # Every profile gets the backup timer. The backup is a
  # cross-cutting OPS concern, not tied to any particular runtime
  # role (api/web/worker). The timer is idempotent: re-enabling it
  # on an instance that already has it is a no-op. Skipping the
  # backup is an explicit operator choice (``systemctl disable
  # ${UNIT_PREFIX}-backup.timer``) and is documented in
  # docs/OPERATIONS.md.
  ENABLED_TIMER_UNITS+=("$(timer_unit_name backup)")

  # Every profile also gets the audit-chain verification timer. Like the
  # backup, integrity verification is a cross-cutting security concern,
  # not tied to a runtime role: every deployment that runs the app writes
  # to the hash-chained audit log, so every deployment should verify it
  # (a failed verify = tampering/corruption). Was previously rendered but
  # never enabled by any profile. Disable per-instance with
  # ``systemctl disable ${UNIT_PREFIX}-verify-audit.timer`` if unwanted.
  ENABLED_TIMER_UNITS+=("$(timer_unit_name verify-audit)")
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
