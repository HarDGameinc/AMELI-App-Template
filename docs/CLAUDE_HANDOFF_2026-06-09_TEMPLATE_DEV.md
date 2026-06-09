## AMELI App Template handoff (sesion Claude, 2026-06-09)

Fecha: `2026-06-09`

Continuacion de
[`CLAUDE_HANDOFF_2026-06-08_TEMPLATE_DEV.md`](CLAUDE_HANDOFF_2026-06-08_TEMPLATE_DEV.md).

Cierra los tres bloques de mejoras del Template solicitados por el
usuario el dia anterior: admin/observabilidad, seguridad/auth y
operativo/infra. Multi-tenancy fue conversada pero el usuario opto por
mantener el Template simple y construir esa capa dentro de la primera
app heredada cuando arranque.

### Estado general al cierre

- Repo: `HarDGameinc/AMELI-App-Template`
- Rama estable: `main` (post-promocion del dia)
- Rama de trabajo: `dev` (sincronizada con `main`)
- Servidor Debian: `/opt/ameli-app-template-dev`, puerto `18080`
- **417 tests pasando** (`pytest -v`)
- **0 regresiones**
- Verificado E2E: MFA recovery codes UX (copy / download .txt /
  print), `/metrics` Prometheus respondiendo con counters reales,
  `ameli-app shell -c "..."` y `ameli-app create-token` funcionando
  desde la shell del server.

### Contexto al arrancar

El cierre del 2026-06-08 dejo el backlog operativo con tres frentes
posibles. El usuario eligio atacarlos en orden:
**admin/observabilidad → seguridad/auth → operativo/infra**.

### Bloque 1 — Admin / observabilidad (4 commits)

| Commit | Item |
|---|---|
| `58ab034` | Export users CSV/JSON streaming |
| `11e8ece` | Paginacion + filtros en sessions panel |
| `1d7d3c7` | `/metrics` Prometheus sin deps externas |
| `4593f86` | Structured logging JSON via env var |

#### `58ab034` — Export users CSV/JSON

Patron identico al export de audit del 2026-06-08. Refactor del service
extrayendo `_users_queryset_for_filters` reusable, nuevo
`filtered_users_queryset` publico, endpoint
`/admin/users/export/?format=<csv|json>` con `StreamingHttpResponse`
para no agotar memoria. Botones en la toolbar del panel de Usuarios
respetando los filtros activos. **8 tests**.

#### `11e8ece` — Sessions panel paginado + filtros

`paginate_admin_sessions` con filtros por search (username icontains),
status (active/revoked) e IP (icontains, para filtrar subredes tipo
`192.168`). Partial nuevo `_sessions_panel.html` con AJAX swap +
selector page size + limpiar filtros. La cookie `ps_admin_sessions_per_page`
persiste el page size del operador, independiente de users/audit. **8 tests**.

#### `1d7d3c7` — Endpoint `/metrics`

Format Prometheus text-based, sin `prometheus_client` para mantener el
Template dependency-free. Metrics expuestas:

- `ameli_app_users_total`, `_active`, `_pending_password` (gauges)
- `ameli_app_sessions_total`, `_active`, `_revoked` (gauges)
- `ameli_app_audit_events_total`, `_failed` (counters)
- `ameli_app_info{version, environment}` (info label)

Endpoint publico (sin auth) porque scraping suele ser interno.
Operadores que necesiten restringirlo lo hacen via reverse proxy. Sin
PII en la respuesta. **7 tests**.

#### `4593f86` — Structured logging JSON

Nuevo `JsonFormatter` en `logging_utils.py` que serializa una linea
JSON por evento con `ts`, `level`, `logger`, `message` + cualquier
`extra={...}` promovido a top-level. Selector via:

- Argumento explicito `configure_logging(format="json")`
- Variable de entorno `AMELI_APP_LOG_FORMAT=json`
- Default sigue siendo text (no rompe deploys existentes)

Idempotente: llamar `configure_logging` varias veces NO acumula
handlers (importante en tests). **9 tests**.

### Bloque 2 — Seguridad / auth (3 commits + 1 chico de soporte)

| Commit | Item |
|---|---|
| `564a662` | API tokens (modelo + middleware + endpoints) |
| ~~Forgot password~~ | Ya existia con tests dedicados — verificado, no se toco |
| `56ea766` | MFA recovery codes UX (copy + download + print) |
| `35d3e62` | Session idle/browser-close configurable |
| `1b4a86a` | CLI `create-token`/`revoke-token`/`list-tokens` (post-bloque, ver abajo) |

#### `564a662` — API tokens

Modelo `ApiToken(user, name, token_hash, token_prefix, created_at,
last_used_at, revoked_at, expires_at)`. Migracion `0006_apitoken`.

Storage: SHA-256 hex del plaintext, **nunca** el secreto. El usuario lo
ve una sola vez al crear (response trae `"token": "ameli_..."`).
Format: `ameli_` + `secrets.token_urlsafe(30)` (~46 chars).

Middleware `ApiTokenAuthMiddleware` que lee `Authorization: Bearer ameli_...`,
valida (no revocado, no expirado, user activo) y bumpea `last_used_at`.
Si la sesion del request ya esta autenticada por cookie, el token NO
sobrescribe — la cookie gana. Esto evita que un token expirado en URL
pisotee una sesion legitima.

Endpoints:

- `GET /profile/tokens/` lista (sin plaintext)
- `POST /profile/tokens/` crea (devuelve plaintext una vez)
- `POST /profile/tokens/<id>/revoke/`
- `GET /api/me/` ping autenticado (responde con `auth_mode: token|session`)

Audit: `api_token_created` y `api_token_revoked` con `prefix` y `name`
en el payload. **24 tests**.

#### Forgot password (preexistente)

Verificado: `request_password_reset` + `complete_password_reset` con
flow `/login/forgot/` + `/login/reset/<uidb64>/<token>/` ya estaba
implementado con `test_password_reset_service.py` +
`test_password_reset_views.py`. **No se toco**.

#### `56ea766` — MFA recovery codes UX

Tres botones nuevos en el bloque "Guarda tus codigos de recuperacion":

- **Copiar** (`navigator.clipboard.writeText`) — fallback a feedback
  "No se pudo copiar - selecciona manualmente" cuando no hay HTTPS
- **Descargar .txt** — genera blob, descarga
  `ameli-recovery-codes-YYYY-MM-DD.txt`
- **Imprimir** — abre ventana nueva con titulo + bullets en monospace,
  dispara `window.print()`

Verificado por screenshot del usuario: download genera archivo con
todos los codes uno por linea; print genera vista limpia. **2 tests**.

#### `35d3e62` — Session timeout configurable

Dos nuevos campos en `Settings`:

- `session_idle_renewal: bool` (default True) → `SESSION_SAVE_EVERY_REQUEST`.
  Cuando True, cada request renueva la cookie y `session_max_age_seconds`
  se comporta como timeout de inactividad. Cuando False, es un cap
  absoluto desde creacion.
- `session_expire_at_browser_close: bool` (default False) →
  `SESSION_EXPIRE_AT_BROWSER_CLOSE`. Cuando True, cierra la sesion al
  cerrar el browser.

Configurables via YAML (`auth.session_idle_renewal`,
`auth.session_expire_at_browser_close`) o env vars
(`AMELI_APP_SESSION_IDLE_RENEWAL`, `AMELI_APP_SESSION_EXPIRE_AT_BROWSER_CLOSE`).
Expuestos en `settings_summary` para auditar via `ameli-app config-check`.
**12 tests**.

#### `1b4a86a` — CLI tokens (post-bloque, fix operativo)

El usuario intento crear un token via `curl -X POST /profile/tokens/` y
choco con CSRF (correcto: la web requiere CSRF token desde HTML). En
lugar de exentar CSRF para POSTs JSON (riesgoso), agregue tres
subcomandos CLI:

```bash
.venv/bin/ameli-app create-token --user admin --name "deploy" [--expires-in-days N]
.venv/bin/ameli-app list-tokens --user admin
.venv/bin/ameli-app revoke-token --user admin --id <token_id>
```

Util especificamente para scripts internos que no van a pasar por el
browser. Los outputs son JSON parseable.
**7 tests**.

### Bloque 3 — Operativo / infra (3 commits)

| Commit | Item |
|---|---|
| `9d89513` | Rate limit IP + account lockout por usuario |
| `cdc9fb9` | Health check expandido |
| `e9fe7ea` | Docs + Caddyfile para TLS interno |

#### `9d89513` — Login throttle

Usa el AuditEvent existente como source of truth (sin tabla nueva).
Helper `_count_recent_login_failures(username, ip, seconds)` cuenta
audit events con `action__endswith="_failed"` en la ventana. Soporta
filtrar por `ip` matcheando ambas variantes en payload
(`"ip"` y `"ip_address"`, asi cubre el signal preexistente y eventos
nuevos).

Dos excepciones: `LoginThrottled` (refuse por IP, mensaje generico) y
`AccountLocked` (refuse por user, mensaje pidiendo esperar o usar
recuperacion). Ambas con `retry_after` para clientes que quieran
mostrar countdown.

Wire en `TemplateLoginView.post()`: antes de delegar al super, llama
`check_login_throttle(username, ip)`. Si tira, registra
`login_throttled` o `login_locked_out` audit y renderiza la pagina de
login con mensaje en `messages.error`.

Defaults: 12 fails por IP en 60s, 5 fails por user en 5 min.
Configurables via `LOGIN_THROTTLE_IP_MAX`, `LOGIN_THROTTLE_IP_WINDOW`,
`LOGIN_LOCKOUT_USER_MAX`, `LOGIN_LOCKOUT_USER_WINDOW` en settings (la
infra de override por env esta lista para que ops los baje sin tocar
codigo). **9 tests**.

#### `cdc9fb9` — Health expandido

`/health` ahora devuelve:

- `ok: true/false` (top-level, derivado del AND de todos los checks)
- `status: "OPERATIVO" | "DEGRADADO"` (string legible)
- `service`, `environment`, `version` (info estatica)
- `uptime_seconds` (psutil si esta, time.time fallback)
- `checks: { database: { ok, detail } }` (extensible)
- `db` top-level mantenido por compat (dashboards viejos)

Estructura `checks` permite agregar mas chequeos (workers, queue,
storage) sin romper consumers existentes. **4 tests**.

#### `e9fe7ea` — TLS con Caddy

No toca codigo, solo docs:

- `docs/TLS_WITH_CADDY.md` con guia completa (instalacion, Caddyfile,
  DNS interno, trust de CA local, env var
  `AMELI_APP_SESSION_COOKIE_SECURE=true`, backout)
- `config/Caddyfile.example` con bloque tipo para reverse proxy

El operador instala Caddy, copia el Caddyfile, importa la CA en sus
clientes, y Firefox deja de quejarse del "Inseguro" en formularios.

### Snapshot al cierre

| Frente | Cobertura |
|---|---|
| Audit log | Filtros (actor/target/action/outcome/fechas/payload), presets de fecha, export CSV/JSON, limpiar filtros |
| Users panel | Filtros (search/role/status), paginacion, export CSV/JSON, limpiar filtros, page size cookie |
| Sessions panel | Filtros (search/status/ip), paginacion, page size cookie |
| Self profile | Sessions paginadas, MFA recovery UX con copy/download/print |
| Auth | Login con MFA, forgot password, API bearer tokens, rate limit + account lockout, session timeout configurable |
| Operacion | `/health` extendido, `/metrics` Prometheus, JSON logging opcional, TLS Caddy documentado |
| CLI | `ameli-app` con shell, create-user, create-token, list-tokens, revoke-token, workers, maintenance |

### Decisiones tomadas (no re-discutirlas)

- **Multi-tenancy: NO en el Template**. La construye la primera app
  heredada en su propia capa cuando arranque. Si una segunda app la
  necesita, ahi extraemos el patron al Template con dos casos reales.
- **Login throttle usa AuditEvent**, no tabla nueva. Cero migracion,
  permite query con la infra de filtros existente.
- **API tokens via CLI** porque exentar CSRF en POST JSON es riesgoso.
  Los scripts internos crean tokens con `ameli-app create-token`.
- **Metrics endpoint publico sin auth**. La restriccion la pone el ops
  via reverse proxy. Sin PII en la respuesta.
- **TLS via Caddy, no nginx + mkcert**. Mas simple operativamente,
  generacion de cert y renovacion automatica.
- **Logging JSON via env var**, default text. No rompe deploys actuales
  pero permite Loki/Promtail listo cuando el ops lo necesite.

### Numeros del dia

- 11 commits promocionados a `main`
- **417 tests pasando** (335 al inicio → 417 al cierre, +82 tests)
- 10 archivos de tests nuevos
- 1 migracion (`0006_apitoken`)
- 0 deps Python nuevas
- ~2500 lineas netas agregadas

### Conversaciones del dia

1. Revision items 2, 3, 4 + multi-tenancy.
2. Decision: hacer los tres bloques tacticos (admin/observabilidad,
   seguridad/auth, operativo/infra) en ese orden. Multi-tenancy queda
   para las apps heredadas, no para el Template.
3. Bloque 1: 4 commits, screenshot del usuario validando users export +
   sessions panel + metrics + log JSON.
4. Bloque 2: 3 commits + verificacion via screenshot del MFA recovery
   UX. Bug operativo: crear tokens via curl chocaba con CSRF. Fix:
   subcomandos CLI agregados como commit chico extra.
5. Bloque 3: 3 commits, throttle + health + docs TLS.
6. Este handoff.

### Proximos bloques abiertos

| # | Item | Tipo | Tamaño |
|---|---|---|---|
| 1 | UI HTML para gestion de API tokens en `/profile/` | UX | Chico |
| 2 | Health checks adicionales (workers, queue, storage) | Operativo | Chico |
| 3 | i18n con gettext | Internacionalizacion | Medio |
| 4 | Webhooks para eventos importantes | Integraciones | Medio |

### Orden recomendado para retomar

1. Resync local + servidor al hash de `main` post-promocion del dia
2. Continuar mejorando el Template: UI de tokens (chico, alta utilidad)
   + migrar a JSON logs y configurar Prometheus scraping.

### Comandos utiles de continuidad

Server resync:

```bash
cd /opt/ameli-app-template-dev
git fetch origin && git reset --hard origin/dev
# Migracion del dia: 0006_apitoken
.venv/bin/ameli-app shell -c "from django.core.management import call_command; call_command('migrate')"
systemctl restart ameli-app-template-dev-api.service
```

Crear un API token desde CLI (sin pasar por web/CSRF):

```bash
.venv/bin/ameli-app create-token --user admin --name "deploy-bot"
# {
#   "ok": true,
#   "token": "ameli_xxxxxxx...",   <- guardar este valor una sola vez
#   "record": { ... }
# }

TOKEN=ameli_xxxxxxx...
curl http://10.100.100.16:18080/api/me/ -H "Authorization: Bearer $TOKEN"
# {"ok": true, "user": {...}, "auth_mode": "token"}
```

Prometheus scraping rapido:

```bash
curl http://10.100.100.16:18080/metrics
```

Activar logs JSON:

```bash
# En /etc/<slug>-<env>/app.env
AMELI_APP_LOG_FORMAT=json
systemctl restart ameli-app-template-dev-api.service
journalctl -u ameli-app-template-dev-api.service -f | jq .
```

Tests:

```bash
DATABASE_URL= .venv/bin/pytest -v
```

### Archivos clave del cierre

- [`src/ameli_app/cli.py`](../src/ameli_app/cli.py) — `create-token`, `revoke-token`, `list-tokens`
- [`src/ameli_app/logging_utils.py`](../src/ameli_app/logging_utils.py) — `JsonFormatter` + selector via env
- [`src/ameli_app/config.py`](../src/ameli_app/config.py) — `session_idle_renewal` + `session_expire_at_browser_close`
- [`src/ameli_web/accounts/models.py`](../src/ameli_web/accounts/models.py) — `ApiToken`
- [`src/ameli_web/accounts/services.py`](../src/ameli_web/accounts/services.py) — API tokens helpers + login throttle
- [`src/ameli_web/accounts/middleware.py`](../src/ameli_web/accounts/middleware.py) — `ApiTokenAuthMiddleware`
- [`src/ameli_web/accounts/views.py`](../src/ameli_web/accounts/views.py) — throttle wire en login + endpoints de tokens
- [`src/ameli_web/admin_views.py`](../src/ameli_web/admin_views.py) — users export + sessions panel
- [`src/ameli_web/dashboard/views.py`](../src/ameli_web/dashboard/views.py) — `/metrics` + `/health` expandido
- [`docs/TLS_WITH_CADDY.md`](TLS_WITH_CADDY.md) — guia TLS interno
- [`config/Caddyfile.example`](../config/Caddyfile.example) — Caddyfile de referencia
