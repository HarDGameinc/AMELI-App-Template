## AMELI App Template handoff (sesion Claude, 2026-06-13)

Fecha: `2026-06-13`

Continuacion de
[`CLAUDE_HANDOFF_2026-06-12_SECURITY_BLOCK_4.md`](CLAUDE_HANDOFF_2026-06-12_SECURITY_BLOCK_4.md).

> Nota retro: este handoff se escribe el `2026-06-15` desde una sesion
> nueva, despues de que la sesion del 13 llegara al limite de contexto
> sin alcanzar a documentar el cierre. El contenido se reconstruye
> a partir de los 13 commits que la sesion empujo a `dev` entre
> `5b0a718` (close handoff del bloque 4) y `bc747fe` (HEAD actual).

### Estado general al cierre

- Repo: `HarDGameinc/AMELI-App-Template`
- Rama estable: `main` (sin promocion del dia 13 todavia — pendiente)
- Rama de trabajo: `dev` (HEAD `bc747fe`)
- **670/670 tests pasando** (`pytest -q`), 0 warnings, 0 regresiones
- Workflow de CI corriendo en GitHub Actions (Python 3.11 y 3.12)
- Sin migraciones nuevas

### Resumen ejecutivo

La sesion del 13 paso de "todo cerrado" (615 tests, 4 bloques de
seguridad firmes) a un bloque de **operabilidad y entregabilidad**:
observabilidad fina, modo mantenimiento real, retention sweep,
metrics Prometheus-style, CI workflow, Docker dev stack y backup
pipeline con verify+restore. La idea: que el template no solo sea
seguro sino que un operador externo pueda **adoptarlo, monitorearlo,
mantenerlo y restaurarlo** sin sorpresas.

| Frente | Antes (cierre 06-12) | Despues (cierre 06-13) |
|---|---|---|
| `/health` | `{ok, db}` | `+ smtp + email_queue + audit_chain + disk` |
| Trazabilidad por request | Solo correlation manual via timestamp | `X-Request-Id` end-to-end + contextvar + log filter + audit auto-inject |
| Ventana de mantenimiento | No existia | Singleton flag + middleware 503 + banner + admin toggle |
| Limpieza de tablas operativas | Manual / nunca | Worker tick corre retention sweep cada vuelta |
| `/metrics` | counters basicos | + queue + chain + maintenance + uptime + locked |
| Pagination del panel admin de sesiones | Renderizaba la pagina completa nested | Fix + regression test |
| CI | Inexistente | GitHub Actions con ruff + django check + makemigrations --check + pytest matrix |
| Onboarding local | venv + `install.sh` | Dockerfile multi-stage + compose stack (api + notifier + postgres) |
| Backup | tar dirs sueltos | Dump consistente + MANIFEST sha256 + retention scoped + opt-in GPG + restore.sh verify/restore |

### Bloque del dia (13 commits)

| # | Commit | Tema |
|---|---|---|
| 1 | `172013b` | health: extend /health con smtp + queue + audit chain + disk |
| 2 | `99070c5` | request_id: middleware + contextvar + log filter |
| 3 | `8ff7e9f` | maintenance-mode: singleton + middleware + admin toggle + banner |
| 4 | `5d11d19` | maintenance worker: data retention sweep |
| 5 | `58a88d3` | health + admin: graceful disk check, friendlier toggle UI |
| 6 | `8ee83a3` | admin: fix sessions pagination partial (full-page nest bug) |
| 7 | `d666d81` | admin: stop nesting `<section>` on sessions partial swap |
| 8 | `d934911` | metrics: extend /metrics (queue, chain, maintenance, uptime) |
| 9 | `13af165` | ci: GitHub Actions workflow (ruff + check + pytest) |
| 10 | `8624702` | docker: dev Dockerfile + compose stack |
| 11 | `33c143a` | backup: dump + MANIFEST + retention + optional GPG + restore.sh |
| 12 | `352acd7` | ci: ruff baseline cleanup (CI green) |
| 13 | `bc747fe` | ci: align env with project defaults to fix 3 tests |

#### 1. `172013b` — `/health` operativo

El probe paso de un check superficial (`{ok, db}`) a una matriz de
checks ligeros pero significativos para una readiness probe real:

- `smtp_config`: backend es `smtp` (no `console`), host/port poblados
- `email_queue`: edad de la fila pending mas vieja contra umbral de 1h
- `audit_chain`: HMAC del tail row coincide con el recalculado
- `disk`: free space en `data_dir`, falla bajo 5%

`ok` global = AND de todos los checks. Campo legacy `db` se mantiene
top-level por compat. Sin SMTP connection, sin walk completo de la
chain, sin iteracion costosa — esto es smoke, no audit. **3 tests**
nuevos en `tests/test_health_endpoint.py`.

#### 2. `99070c5` — Request correlation end-to-end

`X-Request-Id` se vuelve ciudadano de primera. Toda request entrante
arranca con un id estable: el header upstream si llega y matchea el
charset seguro (`[A-Za-z0-9._-]`), o un UUID fresco si no.

- `RequestIdMiddleware` mintea/echoea el id, lo stashea en un
  `ContextVar`, y lo stampa en el response como `X-Request-Id`
- `RequestIdLogFilter` lo promueve a atributo del record para que el
  formatter JSON lo serialize y el text format saque `[req=...]`
- `record_audit` auto-inyecta `request_id` en cada audit row payload
  si la contextvar esta seteada — pivot directo log -> audit row
- Charset validation en el header inbound: nada de newlines o shell
  metacharacters en logs de operador
- Insertado al inicio absoluto de `MIDDLEWARE` para que toda la pipa
  corra bajo la contextvar

**6 tests** cubren happy path + adversarial + log filter + audit
auto-correlation.

#### 3. `8ff7e9f` — Modo mantenimiento

Un singleton (`MaintenanceMode` siempre `pk=1`) con:

- `active`: master flag
- `read_only`: writes no-staff -> 503
- `message`: texto para el banner
- `activated_at` / `activated_by_username`

`MaintenanceModeMiddleware` corre temprano y:

- Stampa `request.maintenance_state` para que cualquier template
  pueda renderizar el banner (`base.html` ya lo hace)
- Pasa GET/HEAD/OPTIONS y requests de staff sin tocar
- Bypasea `/health`, `/admin/`, `/login/`, `/logout/`, `/static/`,
  `/media/` para que probes y operador puedan flipear el flag
- Devuelve 503 (plain o JSON segun `Accept`) en writes no-staff

Helpers publicos: `enable_maintenance`, `disable_maintenance`,
`get_state`. `record_audit` se dispara en cada transicion.

#### 4. `5d11d19` — Maintenance worker = retention sweep

El worker tick dejo de ser placeholder. Cada vuelta corre
`services.run_retention_sweep` que purga filas operativas que
crecerian sin techo en deploys de larga vida:

- `UserSession` revocadas hace > 30d
- `OutboundEmail` en sent/failed updated > 30d
- `ThrottleCounter` con `window_start` > 1d
- `EmailChangeRequest` confirmadas o canceladas hace > 30d
- `MFAEmailChallenge` usadas hace > 7d

Filas pending/in-flight nunca se tocan. Todos los umbrales son
kwargs.

Pruning del audit es **opt-in** (`audit_max_age_days=None` por
default). Cuando se setea, borra filas viejas, demove el tail
superviviente a legacy (`hmac=""` / `prev_hmac=""`) y escribe un
`retention_audit_anchor` que pasa a ser el nuevo head. Trade-off
explicito: verifiabilidad de las filas que vivieron el cut a cambio
de un chain limpio yendo para adelante. Operadores que quieran
garantia mas dura: archivar la tabla audit fuera del template.

#### 5. `58a88d3` — Rough edges post-verificacion en server

Dos issues que aparecieron al probar lo de arriba en el server dev:

1. `/health` flipeaba a DEGRADADO cuando `data_dir` no existia
   (deploys ephemeros, Django sin media). El disk probe trata
   "unset" o "missing" como **ok-con-nota** en vez de fail duro.
2. La card "Modo mantenimiento" mostraba "HTTP 403" cuando el user
   apretaba "Activar" sin sudo grant. JS ahora hace match con el
   patron sudo: `x-csrf-token` lowercase, maneja `401 || need_sudo`
   para prompt sudo, y parsea el JSON de error para mostrar la
   causa real.

#### 6 y 7. `8ee83a3` + `d666d81` — Bug regresivo de pagination

Bug visible: en `/admin/` la card "Sesiones recientes" al apretar
"Siguiente" renderizaba **el sitio completo nesteado dentro del
panel**.

Root cause partido en dos:

- View comparaba `partial == "sessions"` pero el panel usa
  `data-pagination-panel="admin_sessions"` (intencional, para no
  colisionar con `/profile/`). El branch caia al `else` y servia
  `admin/panel.html` (layout completo). Fix: `elif partial ==
  "admin_sessions"`.
- El partial `_sessions_panel.html` aun tenia su propio
  `<section>` wrapper. El JS hace `innerHTML = html` contra el
  outer section que ya existe, asi que la response landea como
  `<section>` nesteado adentro. Aligned con la convencion del
  resto: el partial es solo inner content.

Regression test verifica que la respuesta del partial **no**
contenga `<html`, `<body`, ni el id/data-attr del wrapper outer.

#### 8. `d934911` — `/metrics` operativo

El endpoint hand-rolled (zero deps de `prometheus_client`) ya tenia
counters basicos. Se le suman las signals operativas para que un
Prometheus externo pueda alertar lo mismo que el widget en `/admin/`
o `/health`:

- `ameli_app_users_locked` (lockout permanente)
- `ameli_app_audit_chain_ok` (1/0)
- `ameli_app_email_queue_pending` / `_oldest_seconds` / `_sent_24h`
  / `_failed_24h` / `_expired_24h`
- `ameli_app_maintenance_mode_active` (1/0)
- `ameli_app_uptime_seconds`

Gating por IP allowlist igual que `/health`. `OPERATIONS.md` recibe
seccion "Prometheus metrics" con la tabla completa + alert rules
sample (chain roto, queue stuck, maintenance on permanente).

#### 9. `13af165` — GitHub Actions CI

`.github/workflows/ci.yml` corre en push/PR contra `main` y `dev`,
matrix `[3.11, 3.12]`:

- `ruff check` (hard fail)
- `ruff format --check` (warning-only por baseline historico)
- `django check`
- `makemigrations --check` (catch de model change sin migracion)
- `migrate` contra SQLite scratch
- `pytest -q --tb=short`

Env pre-poblada para satisfacer los boot guards (`SECRET_KEY`,
`ALLOWED_HOSTS`, `TRUSTED_PROXIES`, etc.). Concurrency cancela runs
stale en el mismo ref para no quemar minutos en jobs obsoletos.

**7 smoke tests** guardan el workflow contra regresion silenciosa.

#### 10. `8624702` — Docker dev stack

Onboarding-grade, no manifest de prod:

- Dockerfile multi-stage (builder con venv + project; runtime solo
  runtime libs)
- UID fijo no-root para que bind-mounts mantengan ownership
- `tini` PID 1 para que SIGTERM forwardee limpio a uvicorn y al
  loop del notifier
- `DJANGO_SETTINGS_MODULE` pinned
- Tags: `ameli-app-template:dev` (stack), `:<sha>` (prod)

`docker-compose.yml`:

- `api` + `notifier` + `postgres`
- `api` depends_on db con healthcheck
- `notifier` depends_on api con healthcheck
- src bind-mounted al api para hot-reload
- email backend = `console` (dev no necesita SMTP)
- Credenciales db obviamente-dev (un leak no es incidente)

#### 11. `33c143a` — Backup pipeline + restore

Reemplaza el "tar dirs y move on" por una pipeline formal:

- DB dump al archive: `pg_dump --format=custom` (Postgres) o
  `sqlite3 .backup` (SQLite), ambos consistentes contra writer vivo
- ETC y DATA dirs stage al mismo archive
- `MANIFEST.sha256` con checksum de cada artifact — si un archive
  se corrompe silenciosamente lo detectamos antes del "restore in
  anger"
- Encryption GPG opt-in via `AMELI_APP_BACKUP_GPG_RECIPIENT`. Si
  esta seteada, archive se encripta y el plaintext se borra
- Retention al final de cada run, scoped por `${APP_INSTANCE}-*` —
  una retention mal configurada no puede wipear backups de un
  sibling deploy

`scripts/restore.sh` companion con dos modos:

- `verify`: extract a scratch, valida cada checksum del MANIFEST,
  exit clean. Contract test cron-friendly de "mis backups son
  restaurables?"
- `restore`: copia ETC + DATA back + pg_restore / sqlite restore

#### 12. `352acd7` — Baseline ruff limpio

La CI vino con 257 hallazgos historicos (140+ E501 en docstrings/
audit messages, 39 import-sort, 36 f-string sin placeholders, etc).
Pragmatic clean-up:

- `ruff check . --fix` bajo 106 (import sort, f-string fixups,
  noqa redundantes)
- 4 sustantivos a mano: unused `old_key_bytes`, `raise ValueError`
  sin `from`, imports debajo de `logger = ...`, unused `now` +
  `timezone`
- `pyproject.toml`:
  - `ignore E501` global (apretar es su propio pass)
  - `per-file-ignores tests/*` para `F841`, `E402`, `UP031`

#### 13. `bc747fe` — CI env fixes (cierre del dia)

Tres tests verde local que fallaban en CI por env divergente:

| Test | Causa | Fix |
|---|---|---|
| `test_trusted_proxies_setting_present` | CI seteaba `TRUSTED_PROXIES=127.0.0.1` (single), default es `{127.0.0.1, ::1}` | Env CI = `"127.0.0.1,::1"` |
| `test_default_trusts_loopback_only` | mismo root | mismo fix |
| `test_audit_chain_survives_normal_traffic_and_breaks_under_tamper` | CI seteaba `AUDIT_HMAC_KEY=ci-audit-key`, firmaba el `bootstrap_superadmin` de la fixture; el test despues flipea la key y la fila pre-existente falla | Drop del env var — fixtures van pre-chain (`hmac=""`) y `verify_audit_chain` las skipea |

Bonus: `DeprecationWarning` de `datetime.utcnow()` silenciado
reemplazando por `datetime.now(UTC).replace(tzinfo=None)` en el
test que necesita naive para ejercitar coercion en
`send_with_retry`.

Suite local: 670/670 verde, 0 warnings.

### Numeros del dia

- 13 commits en `dev` (pendiente promocion a `main`)
- **670 tests verde** (615 al inicio del dia 13, +55)
- 1 nuevo workflow CI (Python 3.11 + 3.12)
- 1 Dockerfile + 1 compose stack
- 1 pipeline de backup + restore con verify
- 0 migraciones nuevas
- 0 dependencias Python nuevas

### Decisiones tomadas (no re-discutirlas)

- **`/metrics` sigue hand-rolled**: no se sumo `prometheus_client`.
  La superficie es chica y text exposition spec es estable.
- **Audit pruning opt-in con anchor row**: si el operador prune,
  pierde verifiabilidad del tramo cortado pero queda un chain
  limpio. Quien quiera garantia dura -> archivar la tabla externa.
- **Docker stack es dev-only**: la prod sigue siendo
  systemd + venv + Caddy. Docker es para onboarding.
- **Backup GPG es opt-in**: requerido cuando el archive sale del
  host, pero no se obliga a configurar GPG para una instalacion
  air-gapped que nunca exporta.
- **Retention scoped por `APP_INSTANCE`**: previene wipe accidental
  de backups de instalaciones hermanas en el mismo `/backups`.
- **`ignore E501` global en ruff**: hay un baseline de E501s en
  docstrings y audit messages que vale rewrap aparte. No bloquea
  CI ni esconde bugs.
- **CI env `TRUSTED_PROXIES="127.0.0.1,::1"`**: matchea el default
  del codigo. Cualquier override CI debe documentarse.
- **CI **no** setea `AUDIT_HMAC_KEY`**: fixtures arrancan
  pre-chain. Los tests que necesitan key la setean explicitamente
  en setUp.

### Snapshot al cierre — capacidades del template

| Frente | Cobertura |
|---|---|
| Boot | Refuse en non-dev sin SECRET_KEY/ALLOWED_HOSTS/DEBUG safe |
| Auth | MFA email + password policy + sudo grant + lockout permanente + admin unlock |
| API tokens | Scopes (`read`/`write`/`admin`), default `read`, admin requerido para admin views |
| Sesiones | HttpOnly + Secure + SameSite + idle renewal + disabled-user kick |
| Rate limiting | IP throttle con trusted proxies + JSON-path exact match |
| Audit | HMAC SHA256 chain + `verify-audit` CLI + systemd timer + retention opt-in + alert hook documentado |
| Webhooks | HMAC dispatch + SSRF guard (RFC1918/loopback/metadata/reserved reject) |
| Avatares | Format whitelist + pixel cap + byte cap |
| Static/media | DEBUG-gated + media auth gate |
| Headers | CSP per-page con nonces + XFO + Permissions-Policy + COOP + CORP + Referrer-Policy |
| Email | Backend boot guard + queue persistente con retry + admin UI + structured logging + metrics |
| Health | DB + SMTP + queue + chain + disk (graceful) |
| Request tracing | `X-Request-Id` end-to-end + audit auto-correlation |
| Maintenance | Singleton flag + middleware 503 + banner + admin toggle |
| Retention | Worker tick limpia sesiones/queue/throttle/MFA/email-changes |
| Metrics | `/metrics` text exposition con queue + chain + maintenance + uptime |
| CI | GitHub Actions con ruff + check + makemigrations check + matrix pytest |
| Containers | Dockerfile multi-stage + compose stack |
| Backups | Dump consistente + MANIFEST + retention scoped + opt-in GPG + restore verify |

### Items pendientes / abiertos

| # | Item | Tipo | Tamaño | Origen |
|---|---|---|---|---|
| 1 | Promocion `dev` -> `main` (13 commits) | Release | Chico | Pendiente operativo |
| 2 | RBAC (roles intermedios entre `superadmin` y `public`) | Feature | Grande | Pedido proxima sesion |
| 3 | UI HTML para scopes de tokens en `/profile/` | UX | Chico | Handoff 06-11 |
| 4 | Selector de idioma en header | UX | Chico | Handoff 06-11 |
| 5 | Retry + queue para webhooks fallidos | Operativo | Medio | Handoff 06-11 |
| 6 | Doc receptor webhook con verificacion timestamp | Doc | Chico | Handoff 06-11 |
| 7 | Apretar baseline de `E501` global | Calidad | Chico | Decision 06-13 |
| 8 | CSP sin `unsafe-inline` (nonces ya estan, falta migrar inline JS) | Seguridad | Medio | Pendiente desde bloque 4A |
| 9 | AMELI Report Starlink (primera app real) | Estrategico | Grande | Handoff 06-11 |

### Para el proximo agente

- Rama de trabajo: `dev` (HEAD `bc747fe`)
- Rama estable: `main` (todavia en `644599b` — el dia 13 no se
  promociono, es una de las primeras tareas pendientes)
- Sin migraciones nuevas (ultima sigue siendo
  `accounts.0010_outboundemail_audit_payload`)
- Server dev `ha-report2` no recibio el codigo del dia 13 todavia
  (estaba en `a0a84ec`). Hay que `git fetch && reset --hard
  origin/dev` y `migrate` (no-op), y reiniciar el service.
- CI workflow esta verde local. El proximo push a `dev`/`main`
  dispara el run en GitHub Actions.
- Backups: si el operador quiere correr el pipeline nuevo, setear
  `AMELI_APP_BACKUP_GPG_RECIPIENT` antes de la primera ejecucion
  (sino los archives quedan en plaintext en disco).

### Orden recomendado para retomar

1. Promocionar `dev` -> `main` (revisar diff y push)
2. Resync server dev al hash `bc747fe`
3. Decidir entre RBAC (#2) o cerrar UX chicos pendientes (#3 + #4)
4. Si RBAC: empezar por modelar `Role` + migracion + tests, despues
   pasar al `superadmin_required` -> `role_required("admin")`

### Comandos utiles de continuidad

Sync local + server:

```bash
# Local
git fetch origin && git checkout dev && git reset --hard origin/dev

# Server dev (ha-report2)
cd /opt/ameli-app-template-dev
git fetch origin && git reset --hard origin/dev
.venv/bin/ameli-app shell -c "from django.core.management import call_command; call_command('migrate')"
systemctl restart ameli-app-template-dev-api.service
```

Probar el modo mantenimiento:

```bash
# Activar (require sudo grant)
curl -X POST http://10.100.100.16:18080/admin/maintenance/ \
    -H "Cookie: <session cookie>" \
    -H "x-csrf-token: <token>" \
    -d '{"active": true, "message": "Ventana de mantenimiento 22:00-22:30"}'

# Verificar 503 con write como user normal
curl -X POST http://10.100.100.16:18080/profile/update/ -i
# Esperado: HTTP/1.1 503
```

Backup + verify:

```bash
sudo AMELI_APP_INSTANCE=template-dev /opt/ameli-app-template-dev/scripts/backup.sh
ls /var/backups/ameli-app-template-dev/

# Verify a restoration smoke test
sudo /opt/ameli-app-template-dev/scripts/restore.sh verify \
    /var/backups/ameli-app-template-dev/template-dev-2026-06-13-*.tar.gz
```

Tests + CI:

```bash
DATABASE_URL= .venv/bin/pytest -q  # 670/670
ruff check .                        # clean
ruff format --check .               # baseline-aware
```

### Archivos clave del dia 13

- `.github/workflows/ci.yml` — workflow nuevo
- `Dockerfile` + `docker-compose.yml` — stack dev
- `scripts/backup.sh` + `scripts/restore.sh` — pipeline nuevo
- `src/ameli_web/accounts/middleware.py` — `RequestIdMiddleware`
  + `MaintenanceModeMiddleware`
- `src/ameli_web/accounts/models.py` — `MaintenanceMode` singleton
- `src/ameli_web/accounts/services.py` — `run_retention_sweep`,
  `enable_maintenance` / `disable_maintenance`,
  `summarize_email_queue` extendido
- `src/ameli_web/dashboard/views.py` — `/health` extendido
- `src/ameli_web/admin_views.py` — fix de pagination admin
- `src/ameli_web/templates/admin/_sessions_panel.html` — drop del
  wrapper `<section>` redundante
- `src/ameli_app/logging.py` — `RequestIdLogFilter` integration
- `pyproject.toml` — ruff config con baseline historico
- Tests nuevos: `test_health_endpoint.py` (3), `test_request_id.py`
  (6), `test_maintenance_mode.py`, `test_retention_sweep.py`,
  `test_metrics_endpoint.py` (5), `test_ci_workflow.py` (7)
