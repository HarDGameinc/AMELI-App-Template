# Changelog

## v0.5.9-django — 2026-07-17 (correccion same-day de la estrategia de dev)

Release de mantenimiento — **sin cambios de runtime de la app** (`src/`,
Dockerfile, systemd/prod path sin cambios). Corrige la estrategia de entorno
de dev que v0.5.8 shipeo con la orientacion equivocada.

### Correccion

- **`DECISIONS.md` #9 supersede a #8.** #8 (que v0.5.8 llevo al tag)
  planteaba un modelo "Windows daily + WSL2 para paridad" que fuerza
  **double work**: dos venvs, dos locks, dos suites, dos sets de deps
  mantenidos en sincronia manual. El objetivo real es lo contrario: un
  **unico** entorno de dev que iguale a produccion.
- **`#9`**: WSL2 Ubuntu 24.04 **es** el entorno de dev. Un clone en
  `/home/hardg/ameli-app-template`, un venv desde ambos locks
  hash-pinneados (mismos deps que shipea a prod), un solo loop. WSL2
  tambien alberga el despliegue local (`python -m ameli_app.api`
  directo, sin Docker — este operador emula el server directamente en
  WSL2). Produccion sigue siendo la VM Linux `ha-report2`. El venv
  Windows-nativo queda como fallback (mypy DLL / emergencias) pero **no
  es el loop diario**; el clone en `C:\` se trata como archivado.
  Edicion desde Windows via UNC `\\wsl.localhost\Ubuntu-24.04\...` (VS
  Code Remote-WSL es transparente).
- **`CONTRIBUTING.md`** invertida: setup de WSL2 al frente (incluye
  Postgres local para emular el server), Windows-nativo movido a
  subseccion "fallback deprecated".
- **`AGENTS.md`** anota inline que #8 fue mismo-dia supersedido por #9,
  asi un lector siguiendo la narrativa de estado no adopta la
  estrategia equivocada.

### Multi-maquina

Sin cambios en el modelo de colaboracion: `origin` (GitHub) sigue siendo
el canonico global. Cada maquina (otro laptop del operador, un segundo
dev) instala WSL2 + su propio clone Linux-fs; sync por `git push`/`pull`
como cualquier repo. La regla "WSL2 canonico" es **per-maquina**.

### Deploy

- **Sin migraciones ni deps nuevas.** Solo docs. Como v0.5.7 y v0.5.8, no
  requiere validacion en server ni redeploy. La hija Starlink adopta la
  estrategia correcta cherry-pickeando este tag en lugar de v0.5.8.

## v0.5.8-django — 2026-07-17 (mantenimiento: docs — PRIVACY + WSL2 strategy + two-locks)

Release de mantenimiento — **sin cambios de runtime de la app** (`src/`,
`Dockerfile` builder, `docker-compose.yml` sin cambios funcionales). Consolida
tres piezas de documentacion que valian un tag propio para que la flota
las herede juntas.

### Docs / policy

- **`docs/PRIVACY.md`** — nuevo. Inventario de PII (User, UserSession, MFA*,
  EmailChange, OutboundEmail, ThrottleCounter, AuditEvent), ventanas de
  retencion (extraidas de `services/retention.py`), controles de
  confidencialidad (argon2, Fernet TOTP secret, `salted_hmac` para MFA
  email, audit HMAC chain, EXIF/GPS strip), derechos de usuario (access,
  rectification, **erasure self-service** via `/profile/delete-account/`),
  y **§10 "lo que el operador debe decidir por deploy"** (base legal, DPO,
  disclosure transfronterizo, portabilidad, consent). Consolida lo que
  YA existe en codigo con referencias `file:line`; portabilidad marcada
  como GAP documentado.
- **`DECISIONS.md` #8 — Windows/WSL2/Docker por capas.** Loop diario en
  Windows nativo (barato, rapido; CI Linux respalda lo que win32 skipea);
  WSL2 para paridad Linux on-demand (tests shell/systemd + lock hash-
  pinneado con `uvloop`); **Docker fuera del loop del agente**. Puntero
  desde `CONTRIBUTING.md` "Windows notes".
- **Correccion two-locks** — `requirements.lock` y `requirements-dev.lock`
  son **complementarios, no superset/subset**: el runtime (`uvicorn[
  standard]`, `uvloop`, `httptools`) y el tooling (pytest, ruff, mypy,
  pip-audit) estan en locks distintos; `django` aparece en ambos solo
  porque `pytest-django` lo arrastra. Un env dev completo instala **los
  dos**. Corregido el comentario del Dockerfile (el *comportamiento* ya
  era correcto: el target `dev` hereda de `builder`), `DECISIONS.md` #8 y
  `CONTRIBUTING.md` con el procedimiento correcto y los numeros medidos
  (WSL2 Linux: **1156 passed / 28 skipped** vs Windows 1126 / 58).

### Deploy

- **Sin migraciones ni deps nuevas.** No requiere validacion en server ni
  redeploy. La hija cherry-pickea desde el tag para heredar estos docs.

## v0.5.7-django — 2026-07-16 (mantenimiento: path Docker/compose de dev)

## v0.5.7-django — 2026-07-16 (mantenimiento: path Docker/compose de dev)

Release de mantenimiento — **sin cambios de runtime de la app** (`src/` y el
path systemd/prod intactos; solo el path Docker/dev + line-endings). El primer
dry-run real de Docker de la **app hija (Starlink)** encontró 5 bugs, todos
verificados y ahora corregidos en el template para que la flota los herede.

### Fixes (handoff 2026-07-15 §5)

1. **`docker-compose.yml`: env vars con nombres inertes.** El código lee
   `AMELI_APP_DJANGO_{SECRET_KEY,DEBUG,ALLOWED_HOSTS}` (`config.py`/`base.py`);
   el compose seteaba las formas sin el infijo `DJANGO_` → inertes → caía al
   `SECRET_KEY` default inseguro + `DEBUG=False`. Renombradas en `api` +
   `notifier`, más `APP_ENV=dev` y una `AMELI_APP_MFA_ENCRYPTION_KEY` (Fernet dev).
2. **`Dockerfile`: `ModuleNotFoundError: ameli_web`.** El `.pth` del editable
   apuntaba a `/build/src` (no existe en runtime). Fix: `PYTHONPATH=/app/src`.
3. **`Dockerfile`: instalaba rangos, no el lock.** `pip install -r
   requirements.txt` (podía traer Django 6 vs el `5.2.16` pinneado) y sin
   dev-deps. Ahora `--require-hashes -r requirements.lock` (paridad prod,
   ASVS V14.2.3) + un target **`dev`** que agrega `requirements-dev.lock` para
   `docker compose run --rm api pytest`; la imagen `runtime`/prod queda lean.
4. **`Dockerfile`: no copiaba `VERSION`** → `/health` reportaba `v0.0.0-dev`.
   Fix: `COPY VERSION ./VERSION`.
5. **Falta `.gitattributes`** → un clone Windows con `autocrlf=true` checkouteaba
   los `.sh` en CRLF y rompía `source _common.sh` en contenedores Linux.
   Agregado (`* text=auto eol=lf`; `.ps1/.bat/.cmd` CRLF; binarios incl. `*.gif`).

Extras: corregido el comentario del compose (`.venv/bin/ameli-app` →
`ameli-app`; el venv vive en `/opt/venv`). **+6 tests de regresión** en
`test_docker_stack.py` fijan cada fix contra drift. Suite **1126 passed**, CI verde.

## v0.5.6-django — 2026-07-15 (mantenimiento: camino de fork + tooling de CI)

Release de mantenimiento — **sin cambios de runtime de la app** (el código del
servicio es idéntico a v0.5.5). Corrige el camino de "crear una app hija" y
pone al día el tooling de CI. Validado en server (`template-check` corre limpio
en la caja; `/health` `v0.5.5-django` OPERATIVO, servicio intacto).

### Camino de fork — corregido (primer dry-run real, ver v0.5.5 §3.9)

El camino que justifica el template (`BUILDING_NEW_APP.md`) nunca se había
ejecutado. Un dry-run completo destapó tres bugs reales:

- **`BUILDING_NEW_APP §2`**: decía que renombrar los paquetes `ameli_app`/
  `ameli_web` era **obligatorio** (tabla de 5 filas). Falso: **conservar los
  nombres funciona out-of-the-box** (suite completa + ruff + `manage.py check`
  0 issues) porque la identidad desplegada es env-driven (`APP_SLUG`/
  `APP_PACKAGE`/`APP_NAME`). Seguir la tabla dejaba **~740 referencias rotas en
  ~250 archivos** (imports, `DJANGO_SETTINGS_MODULE`, tests) → la app **ni
  arrancaba**. Y el tip de verificación (`pytest` post-rename) daba **falso
  positivo** con el template instalado editable en el venv. Reencuadrado:
  keep-names = default recomendado; el rename es opcional/cosmético y, si se
  hace, es un refactor scripteado verificado en venv limpio.
- **`cli._json()` crasheaba con salida no-ASCII** (`print` sobre consola
  cp1252 → `UnicodeEncodeError`). Ese es el canal (`template-check`) con el que
  una app hija se entera de una security release — y el 🔴 de las notas de
  v0.5.5 lo rompía. Fix: reconfigura stdout a UTF-8 (protegido para streams
  capturados/piped).
- **`template-check` daba `github api 403` opaco** al agotar el rate limit
  anónimo de GitHub (60/hora por IP). Fix: detecta `X-RateLimit-Remaining: 0`
  y da un mensaje accionable (setear `GITHUB_TOKEN`).

Tests de regresión para el rate-limit y el camino no-ASCII.

### Tooling de CI

- Bump de actions pinneadas: `actions/checkout` v5→v7, `github/codeql-action`
  v3→v4, `actions/setup-node` v6→v7 (todas verificadas verdes por Dependabot).
- **Dependabot ahora apunta a `dev`** (`target-branch: dev`), no a `main`, para
  que los bumps de deps sigan la promoción normal en vez de abrir contra la
  rama de release.

## v0.5.5-django — 2026-07-14 (SECURITY: hash del código MFA por email + info disclosure SMTP)

> ### 🔴 NOTA DE SEGURIDAD — acción requerida para apps hijas
>
> **Actualizá.** Esta release corrige una debilidad **real** en el segundo
> factor por email.
>
> **Qué pasaba:** el código MFA por email es de **6 dígitos** (10⁶ ≈ 2²⁰
> posibilidades) y su digest se persistía en `MFAEmailChallenge.code_hash` con
> **SHA-256 plano**. Cualquiera capaz de **leer esa tabla** — SQL injection, un
> backup filtrado, un dump robado, una réplica comprometida — podía **agotar el
> espacio en milisegundos** y recuperar el código MFA vivo, **derrotando el
> segundo factor**. Contradecía el propio modelo de amenaza del template: el
> secreto TOTP (`mfa_secret`) ya se cifra at-rest justamente para que un
> compromiso de *solo lectura* de la DB no diera bypass de MFA; el código de
> email era el hueco que quedaba.
>
> **Fix:** el digest ahora es un **HMAC keyeado** (`django.utils.crypto.salted_hmac`)
> sobre `SECRET_KEY` — que **nunca vive en la base de datos** — con domain
> separation. El hash almacenado, por sí solo, ya no sirve para nada.
>
> **Impacto al actualizar:** los challenges **en vuelo** dejan de validar (TTL
> 10 min, single-use). El usuario simplemente pide un código nuevo. **No hace
> falta migración de datos.**
>
> Descubierto por **CodeQL** (`py/weak-sensitive-data-hashing`) en su primera
> corrida, 2026-07-14.

### Info disclosure: excepciones de SMTP ecoadas al cliente

Tres handlers (`views/auth.py`, `views/mfa.py`, `views/profile.py`) devolvían
`f"...{exc.__class__.__name__}: {exc}"` al cliente. `auth.py` es alcanzable en
estado **pre-MFA** (solo `@require_POST`) y los otros dos son apenas
`@login_required` — así que nombres de mail-host y fallos de auth/TLS se
filtraban a usuarios sin privilegio. El comentario de `profile.py` afirmaba que
era una afordancia de operador, pero **la vista no estaba gateada a superadmin**.

`auth` y `mfa` ahora devuelven un mensaje genérico; `profile` **conserva el
detalle solo para superadmins** (que ya tienen acceso total), preservando la
afordancia de debug. `logger.exception` sigue registrando el traceback completo
en el journal en los tres casos.

### Tooling de seguridad: CodeQL + Dependabot

Gratis al pasar el repo a público. **CodeQL** (SAST, Python + JS) corre en cada
push/PR + sweep semanal; encontró el hallazgo de arriba en su primera corrida
(16 alertas → 1 real + 1 rastreada desde el sink; 14 FPs descartados con razón
auditable). **Dependabot** solo para `github-actions` — **`pip` queda
deliberadamente deshabilitado** (documentado en `dependabot.yml`): los locks son
`requirements*.lock` hash-pinneados que Dependabot no descubre, y `pip-audit` ya
los audita en cada push **y** en el cron semanal, con más precisión.

### Docs

- `SERVER_HARDENING.md §2`: corregido un claim **falso** (decía que la app
  "currently binds `0.0.0.0:18080` over plain HTTP"). El template **shippea
  loopback por default** (`api.host: "127.0.0.1"`); la sección se contradecía
  con su propio appendix (P2 CLOSED).
- Ground-truth del deploy sanitizado del repo público.

## v0.5.4-django — 2026-07-13 (security: CSP style-src sin 'unsafe-inline' + Pillow CVEs)

Endurecimiento de CSP + parche de seguridad de dependencia + docs de cadena
de suministro. Validado en server (`ha-report2`): el header responde
`style-src 'self' https://fonts.googleapis.com` (sin `'unsafe-inline'`),
render sin cambios.

### Pillow 12.2.0 → 12.3.0 (5 CVEs)

El gate `pip-audit` del PR de promoción detectó **5 vulnerabilidades**
conocidas en `pillow==12.2.0` (PYSEC-2026-2253..2257), todas corregidas en
**12.3.0** (dentro del rango `Pillow>=11.3,<13`). Se actualizó
`requirements.lock` a `pillow==12.3.0` con hashes frescos de PyPI (87
archivos) — edición manual del bloque (el `pip-compile` no corre en Windows
por `uvloop`; mismo procedimiento que el bump de Django en v0.5.2),
verificado por CI (`--require-hashes` + `pip-audit`).

### setuptools 82.0.1 → 83.0.0 (PYSEC-2026-3447)

Al re-correr el CI (repo ahora público → Actions gratis), `pip-audit` detectó
`PYSEC-2026-3447` en `setuptools==82.0.1` (dep de build en
`requirements-dev.lock`, no en lo que se despliega), fix en **83.0.0**. Bump
manual del bloque con hashes de PyPI (wheel + sdist).

### CSP `style-src` sin `'unsafe-inline'` (commit `96f6bec`)

- Los **46 `style=""` inline de 11 templates** pasaron a clases utilitarias
  en `app.css` (declaraciones idénticas, especificidad analizada → cero
  cambio visual), lo que permitió **quitar `'unsafe-inline'` de `style-src`**
  del CSP principal — el último token inseguro que quedaba (`script-src` ya
  usaba nonces). Los CSP de `/django-admin` y `/docs` conservan
  `'unsafe-inline'` (estilos de framework/CDN fuera de nuestro control).
- Nota: un gestor de contraseñas del navegador que inyecte estilos inline
  verá su overlay bloqueado por el CSP (comportamiento correcto; la app no
  tiene violaciones propias).

### Docs / supply-chain

- `OPERATIONS.md` → "Deployed instance — ground truth": referencia canónica
  del deploy en `ha-report2` (paths/units/puertos computados, no adivinados).
- `OPERATIONS.md` → SBOM (CycloneDX) via `pip-audit -f cyclonedx-json`;
  clarificación de qué forma se adjunta al release.
- Prompts de sesión S-09/S-10 (inicio/cierre de día) en el handoff template.
- `test(sri)`: test de invalidación por mtime hecho determinista (flake Windows).
- `test(migrations)`: `tests/test_migrations.py` — drift (`makemigrations
  --check` dentro de la suite) + round-trip reverse-a-zero/re-apply que prueba
  la **reversibilidad** de todas las migraciones first-party (incluidas las 3
  `RunPython`). Cierra el gap "no migration tests" de `AGENTS.md`.
- `test(migration-backfill)`: `tests/test_migration_mfa_backfill.py` — cubre la
  lógica de datos de `0012_mfa_secret_encrypt` (antes solo ejercitada como
  no-op sin clave): con clave, encripta filas plaintext, salta las ya
  encriptadas (idempotente), el reverse desencripta, y sin clave es no-op.
  Código sensible: un bug dejaría secretos TOTP en claro o bloquearía usuarios.

### a11y — anuncio SR de swaps de paginación/filtro

- Los paneles del admin reemplazan su contenido in-place (`swapPanelTo` en
  `app.js`) con `aria-busy` pero **sin anunciar** el resultado al lector de
  pantalla. Agregada una región live global oculta (`#a11y-live`, `role=status`
  `aria-live=polite` `aria-atomic`) en `base.html` + helper `announce()` que,
  tras cada swap, anuncia el resumen del panel (`"Mostrando 26–50 de 120"` /
  `"Sin resultados"`). Cubierto por `tests/test_a11y_live_region.py` (template)
  y `tests/e2e/test_a11y_announce.py` (e2e).
- Los 4 feedbacks de acción del panel admin (toggle de mantenimiento, crear
  usuario, cambiar/resetear password) actualizan `textContent` vía JS pero
  **no eran regiones live** — un usuario SR no escuchaba "Guardando…" /
  "Operación completada" / errores. Agregado `role=status aria-live=polite`
  a los cuatro (los feedbacks de sudo/perfil ya lo tenían). Verificado en
  browser real + `tests/test_a11y_live_region.py`.

### HSTS `includeSubDomains` — override + default opt-in (commit `8ddb0bb`)

- Nuevo env-var `AMELI_APP_HSTS_INCLUDE_SUBDOMAINS` en `security_headers.py`
  para controlar la directiva `includeSubDomains` de HSTS.
- **Cambio de default:** `includeSubDomains` pasa a **OFF (opt-in)**, igual que
  el default de Django. Antes se prendía implícitamente cuando `HSTS_SECONDS>0`.
  Un deploy que hoy tenga HSTS activo y dependa del `includeSubDomains` implícito
  debe ahora setear `AMELI_APP_HSTS_INCLUDE_SUBDOMAINS=true` para conservarlo.
- Motivo: `includeSubDomains` extiende la política solo a los **subdominios del
  host que lo emite** (no a hermanos ni al padre); activarlo sin ser dueño de
  todo el subárbol —o con hijos HTTP-only, o vía preload— bloquea navegadores en
  HTTPS de forma irreversible por el `max-age`. Opt-in es la postura conservadora.
- Valor no-booleano falla cerrado (raise); nunca se emite con HSTS off. +5 tests.
- Nota operativa: en deploys detrás de un reverse-proxy que ya emite HSTS (p. ej.
  Caddy), el proxy es la fuente de verdad y estas vars quedan sombreadas
  (ver `SERVER_HARDENING.md` §9).

## v0.5.3-django — 2026-07-12 (security: throttle atómico M3 + template-check CLI)

Completa **M3**: el rediseño atómico del throttle de login que en `v0.5.1`
quedó diferido (allí solo se corrigió el docstring a "soft-ceiling"). Cierra
la carrera **check-then-act** del gate por-usuario, que dejaba un techo
blando bajo ráfagas concurrentes. Validado en `ha-report2` (`manage.py
check` limpio, `/health` OPERATIVO sobre Postgres); la prueba atómica sobre
Postgres la cierra el job `test-postgres` del CI en el PR de promoción.
Suite completa **1101** verde.

### Security

- **M3 — gate de login por-usuario atómico** (`accounts/services/
  throttle.py`, `signals.py`, `services/__init__.py`): **reserve-then-verify**
  sobre un gate dedicado `login_gate_user`. Cada `check` cuenta el intento
  atómicamente (`_bump_throttle_counter` bajo `select_for_update` + `F()`) y
  luego lee el sliding total; el incremento commitea **antes** de la
  decisión, así requests concurrentes ven counts distintos y el cap pasa de
  techo blando a **techo duro** (`>` en vez de `>=` mantiene el cap efectivo
  idéntico). Un login exitoso limpia el gate vía `reset_login_throttle()`,
  cableado al único hook `user_logged_in` (cubre login-form + MFA). El gate
  por-**IP** queda failure-based soft **a propósito** — gatea un keyspace
  grande/mixto; contar todos los intentos penalizaría ráfagas legítimas de
  NAT/oficina compartida. +5 tests (`test_login_throttle.py`).

### Features

- **`ameli-app template-check`** (`cli.py`): la pieza "consultar" del canal
  de updates (`DECISIONS.md` #7). Consulta el último GitHub Release del
  template y lo compara contra el **lineage** de la app; emite JSON y sale
  **1 si está behind** (cron-friendly), 0 up-to-date/ahead, 2 en error. Sin
  dep runtime nueva (stdlib `urllib`, repo validado por regex + host https
  fijo); soporta `GITHUB_TOKEN`/`AMELI_APP_GITHUB_TOKEN` (el repo del
  template es privado → la API da 404 sin auth). +11 tests.
- **Canal de actualización del template documentado** (`BUILDING_NEW_APP.md`
  §6, `DECISIONS.md` #7): flujo upstream + los tres modelos de adopción.

### Docs / ops

- **Runbook de rotación de secretos** (`OPERATIONS.md` → "Secret rotation";
  `SERVER_HARDENING.md` §5 apunta ahí): procedimiento para las 4 claves
  (`DJANGO_SECRET_KEY`, `MFA_ENCRYPTION_KEY`, `AUDIT_HMAC_KEY`, password de
  la DB), con las trampas de cada una (p. ej. rotar `MFA_ENCRYPTION_KEY`
  rompe TOTP en silencio → re-enrolar o re-cifrar).
- **SBOM CycloneDX** (`OPERATIONS.md` → "Lockfile / supply chain"): generar
  con `pip-audit -f cyclonedx-json` (sin dep nueva — ya es dev-dep + job de
  CI); artefacto point-in-time adjunto al GitHub Release, no commiteado
  (`*.cdx.json` gitignored).

### CI

- `pip-audit` corre también en `pull_request`, completando el gate de
  promoción a `main` (antes solo en push/schedule).

### Deploy

- **Sin migraciones ni deps nuevas.** `git pull` en `dev` + restart del
  service (`ameli-app-template-dev-api.service`). El `/health` marcará
  `v0.5.3-django` tras el redeploy.

## v0.5.2-django — 2026-07-10 (security: Django 5.2.16 — 3 CVEs)

Bump Django `5.2.15 → 5.2.16` (LTS patch) to clear three CVEs the CI
`pip-audit` job flagged against the lockfile: **PYSEC-2026-2090 / 2091 /
2092**. Stays on the 5.2 **LTS** line (the alternative fix, 6.0.7, is
non-LTS — see `DECISIONS.md`).

- Lock-only change: `requirements.lock` + `requirements-dev.lock` updated
  to `django==5.2.16` with fresh PyPI hashes. The `Django>=5.2,<7` range
  in `requirements.txt` already permitted it — no code changes.
- **Deploy**: on the server, `git pull` + `pip install --require-hashes -r
  requirements.lock` picks up 5.2.16, then restart the service.

## v0.5.1-django — 2026-07-08 (hardening: revisión de seguridad multi-agente)

Cierra 7 hallazgos de una revisión de seguridad defensiva (3 agentes por
clase de vulnerabilidad + verificación manual). La postura ya era muy
fuerte (cero inyección/SSRF/traversal/XSS/CSRF/open-redirect); estos son
fallas de **lógica/config**. Suite 1086 verde, ruff limpio.

### Fixes

- **M1 — entorno fail-closed** (`config.py`): un entorno no declarado
  rehusaba arrancar en vez de caer silenciosamente a "dev" (que desactivaba
  todos los guards de prod: SECRET_KEY/DEBUG/ALLOWED_HOSTS, cifrado MFA,
  audit HMAC, cookies Secure, HSTS).
- **M2 — MFA obligatorio se aplica** (`MfaRequiredMiddleware` + `services/
  mfa.py`): un `mfa_required` sin enrolar es redirigido a enrolamiento;
  enrolar ya no limpia el flag; el self-disable queda bloqueado bajo
  mandato (antes el flag era cosmético).
- **M3 — docstring del throttle corregido** (`throttle.py`): la
  comprobación es check-then-act (no atómica); documentado como soft-ceiling
  acotado por el lockout permanente. Rediseño atómico diferido.
- **L1 — IDOR de avatar** (`urls.py` / `permissions.py`): ownership por
  `avatar.name` exacto (con token), no por slug lossy (colisión
  `john.doe`/`john_doe`).
- **L2 — `decrypt_secret`**: `except` estrechado a `InvalidToken` (no
  enmascara fallos no-cripto como "plaintext").
- **L3 — cancel de email two-step** (`email_change.py`): GET intersticial +
  POST aplica, para que un mail-scanner no auto-cancele un cambio legítimo
  (espeja el confirm de B5).
- **L4 — invariante último-superadmin** (`services/user.py`): demote/disable
  de un superadmin activo bajo `select_for_update` que rehúsa dejar cero
  admins (race de demote mutuo concurrente).

## v0.5.0-django — 2026-07-07 (hito: promoción dev → main)

Primer release en `main` desde el arranque del template. Marca el hito de
**identidad visual (D-1) completa** más toda la base acumulada en `dev`:
cuentas/perfil/administración, MFA (TOTP+email), auditoría encadenada,
sesiones con revocación, endurecimiento de seguridad (CSP+nonce, Trusted
Types, SRI, throttling), pipeline de avatares, CI matriz 3.11-3.14 +
Postgres + e2e + a11y (axe) + js-unit + pip-audit, y docs para agentes.

No hay cambios de código respecto a `v0.4.16-django`; es el bump de
promoción (`main` estuvo congelado hasta este hito). El detalle por versión
está en las entradas siguientes.

## v0.4.16-django — 2026-07-07 (D-1 Fase D: motion — cierra D-1)

Última fase de D-1, palette-aware y reduced-motion-safe. **Cierra D-1
completo** (A paleta+tipografía · B jerarquía+layout · C signature · D
motion). Validado en server (`ha-report2`) y CI.

### D-1 Fase D (commit `648923e`)

- **Reveal escalonado al cargar**: los bloques de nivel superior de
  `<main>` hacen fade + slide-up en cascada (`ameliReveal`, `fill-mode
  both`) — la página "se arma" en vez de aparecer de golpe. La regla global
  `prefers-reduced-motion` colapsa la duración → cada bloque cae a su estado
  final al instante.
- **Hover states**: las cards de estado (summary/hero-stat) se elevan con
  borde de acento + sombra suave (`color-mix` sobre `--accent`); los links
  `icon-action` ganan transición + wash de acento al hover.

## v0.4.15-django — 2026-07-07 (D-1 Fase C: elemento signature)

Elemento signature de D-1: un **pulso de telemetría** en el header. Sparkline
con un segmento que recorre la onda (CSS, `pathLength=100` para bucle
perfecto), coloreado por la paleta activa (`--accent`). Decorativo
(`aria-hidden`) — la salud real vive en las cards del dashboard y el endpoint
`/health`.

### D-1 Fase C (commits `31a9684`, `ed36889`, `c5ec17d`)

- Sparkline SVG en el header (dos polilíneas: base tenue + segmento de
  barrido); keyframes `brandPulseScan`; `prefers-reduced-motion` lo congela.
- **Hallazgo**: `/health` está protegido por `HEALTH_METRICS_ALLOWLIST`
  (allowlist por IP) → un probe del navegador da **403** en deployments
  asegurados. Por eso el pulso es **puramente decorativo** (no consulta
  `/health`) — evita una petición fallida + `403` en consola por página. El
  hook CSS `[data-health="degraded"]` queda documentado para reflejar salud
  en vivo en deployments abiertos.
- Se quitó el link `/health` del footer (daba un "forbidden" crudo a
  usuarios fuera del allowlist); los monitores lo consultan directo.

## v0.4.14-django — 2026-07-07 (D-1 Fase B: jerarquía + layout)

Jerarquía visual sobre la base de paletas (v0.4.13), todo palette-aware vía
tokens (sin colores hardcodeados). Validado en server (`ha-report2`) en las
4 paletas y CI (21 axe verdes).

### D-1 Fase B (commit `19a2b0f`)

- **Hero**: la tarjeta superior de cada página (dashboard/perfil/admin)
  ahora lee como hero de marca — wash de acento (radial `color-mix`), borde
  teñido, barra de 2px `accent → brand` arriba y sombra suave teñida. En
  modo oscuro esto **hace visible el color de la paleta** (antes los fondos
  oscuros se veían casi iguales entre paletas).
- **Alineación**: el header envuelve su contenido en `.header-inner` con el
  mismo `max-width` que `<main>` / `.footer-inner` (1320) — la app bar deja
  de sangrar hasta el borde de la ventana.
- **Paneles**: radio 8→12 y algo más de padding; ancho del shell 1280→1320
  con más aire vertical.

## v0.4.13-django — 2026-07-07 (D-1: identidad visual + paletas de color)

Cierra la base de D-1 (identidad visual). Paleta navy+teal + tipografía
DM Sans / IBM Plex Sans, y un segundo eje de theming: **paletas de color**
completas (Teal / Índigo / Ámbar / Violeta) seleccionables por usuario,
ortogonales al modo claro/oscuro/auto. Validado en server (`ha-report2`) y
CI (21 checks axe en las 4 paletas × claro/oscuro).

### D-1 Fase A — paleta + tipografía (commit `72470ee`)

- Reemplazo del azul genérico (`#155eef`) por identidad navy + acento teal.
  Cuerpo en IBM Plex Sans, títulos en DM Sans. Se conservó la estructura de
  tokens `--*-fill` de v0.4.11 (contraste 4.5:1 bajo texto blanco).

### Verde menos fluorescente (commit `506b677`)

- El acento oscuro (`#22c9ac`) y `--ok` (`#34d399`, emerald) leían neón —
  se apagaron a teal/verde más sobrios (`#33a894` / `#3fae7a`).

### Paletas de color (commit `95b6c9e`)

- Nuevo `User.color_theme` (choices, default `teal`) + migración `0014`.
  Segundo eje `data-palette` en `<html>`; bloques CSS de override por paleta
  (índigo/ámbar/violeta) × claro/oscuro/auto. Los estados (verde/ámbar/rojo)
  se heredan del base → constantes entre paletas.
- Selector de swatches en el perfil (RadioSelect estilado con `:has()`),
  focuseable por teclado; campo opcional en el server (un POST parcial
  conserva la paleta actual). Persistido en las rutas JSON y form; auditado.
- **Bug corregido**: el bloque *Auto* (media query) aún tenía los verdes
  neón — solo se había actualizado el oscuro explícito.
- Gate a11y extendido a las 4 paletas × claro/oscuro (21 axe verdes). Los
  smoke tests de CSS ahora leen `app.css` como UTF-8.

## v0.4.12-django — 2026-07-06 (a11y: focus management de modales)

a11y++ — manejo de foco en los modales del admin (WCAG 2.1.2 / 2.4.3).
Validado en CI (e2e Playwright).

### a11y++ (commit `d0f8307`)

- `admin-panel.js`: `openModal()` recuerda el elemento que lo disparó y
  mueve el foco al diálogo; `closeModal()` lo restaura. Un handler de
  `keydown` **atrapa Tab** dentro de cualquier `.modal-backdrop` visible y
  rutea Escape por el botón de cierre del modal (así el flujo del sudo
  cancela su promesa). El sudo-modal usa el mismo remember/restore.
- `admin/panel.html`: los modales reset-password / change-role /
  delete-user ganaron `role="dialog" aria-modal="true" aria-labelledby`
  (el sudo ya los tenía).
- `test_accessibility.py`: valida el markup del diálogo, que Tab quede
  atrapado y que Escape cierre. 13/13 a11y verde.

Sin cambio visual (comportamiento de teclado) → validado por e2e, sin
smoke visual de servidor.

## v0.4.11-django — 2026-07-06 (a11y: tema oscuro + teclado + tokens -fill)

Amplía el smoke de accesibilidad a **ambos temas** y agrega checks de
teclado. Validado en CI (axe con `emulate_media` claro+oscuro) y smoke
visual en servidor (tema oscuro impecable).

### a11y+ (commit `5a86106`)

- **Test** (`tests/e2e/test_accessibility.py`): cada página corre en
  claro **y oscuro** (`page.emulate_media`); se suma `/login/forgot/` y
  2 checks de teclado (skip-link es el primer Tab stop y apunta a
  `<main>`; el form de login es alcanzable). El mensaje de fallo muestra
  fg/bg/ratio de axe.
- **Fixes de contraste del tema oscuro** (el claro no los tenía): el
  palette oscuro reutilizaba colores brillantes como **fondos rellenos**
  con texto blanco, cayendo bajo 4.5:1 — botones primarios (3.16:1),
  pills de estado (2.83:1), botones danger. Se introdujeron tokens
  `--accent-fill` / `--ok-fill` / `--warn-fill` / `--bad-fill` (color de
  fondo relleno bajo texto blanco): claro = base; oscuro = variantes más
  oscuras que superan 4.5:1. `--bad` oscuro #e5564a → #ee6459 para el
  texto "fail" del checklist.

Nota: el tema **Auto** delega correctamente en `prefers-color-scheme`
(sin `data-theme`); si el navegador (p.ej. Firefox "Apariencia del sitio
web") fuerza oscuro, Auto se ve oscuro — es esperado, no un bug.

Bump tras smoke visual en `ha-report2` (tema oscuro: botones/pills/checklist
legibles, nada lavado).

## v0.4.10-django — 2026-07-06 (accesibilidad: smoke axe-core + fixes)

Cierra el gap "no accessibility tests". Nuevo smoke axe-core (WCAG 2.1
A/AA) sobre login/dashboard/profile/admin vía Playwright, gateando
critical + serious. Validado en CI (Linux) y smoke visual en servidor.

### a11y (commit `254948e`)

- **Test** (`tests/e2e/test_accessibility.py`): axe-core 4.10.2 vendoreado
  (`tests/e2e/vendor/axe.min.js`, MPL-2.0, test-only, sin dep pip ni
  cambio de lock) inyectado vía `page.evaluate` (sortea la CSP por CDP).
- **Fixes que el test encontró**:
  - `select-name` (critical): los 4 `<select>` de filtro admin sin nombre
    accesible → `aria-label` (`users_role`, `users_status`,
    `audit_outcome`, `admin_sessions_status`).
  - `color-contrast` (serious): `--muted` (#687385) y `--warn` (#b46a00)
    del tema claro caían apenas bajo 4.5:1 → #5b6472 / #a15e00.
  - `.password-policy-item.fail` usaba un durazno claro (#ffcfbf) pensado
    para fondo oscuro (~1.3:1 en blanco) → `var(--bad)`, por-tema
    (#b42318 claro / #e5564a oscuro), legible en ambos.
- Atribución axe-core en `THIRD_PARTY_LICENSES.md`.

Bump aplicado tras smoke visual en `ha-report2` (checklist de contraseña
rojo/legible, filtros OK, nada roto por el cambio de contraste).

## v0.4.9-django — 2026-07-03 (refactor: split del JS inline a estáticos)

Cierra el ítem de deuda frontend **"split inline JS"** del roadmap. Los
dos `<script>` inline grandes de las plantillas pasan a archivos
estáticos externos, protegidos con SRI y servidos desde `'self'` bajo el
`script-src` de la CSP (sin nonce). Refactor **sin cambio de
comportamiento**, validado en `ha-report2` (ambas páginas responden
igual, sin errores en DevTools).

### Fase 1 — `profile.js` (commit `1dcb8ff`)

`accounts/profile.html` adelgaza ~530 líneas: el JS (tabs, cambio de
contraseña, MFA activar/desactivar app+email, tools de recuperación,
cambio de email) se movió a `static/js/profile.js`. Los 9 `{% url %}`
server-rendered viajan por `data-*` en un `#profile-js-config` oculto; el
CSRF se sigue leyendo del input oculto del form. Include gateado por
`not must_change_password` (misma condición que tenía el inline).

### Fase 2 — `admin-panel.js` (commit `8e1e5e6`)

`admin/panel.html` adelgaza ~600 líneas: el JS (toggle de mantenimiento,
widget de cola de email, sudo grant/status, CRUD de usuarios +
rol/password/MFA) se movió a `static/js/admin-panel.js`. Las URLs ya
eran literales `/admin/*`, así que el único valor inyectado es el CSRF,
vía `data-csrf-token` en `#admin-js-config`.

### Infra

- `base.html`: nuevo `{% block extra_scripts %}` tras `app.js` (antes de
  `</body>`, para que un listener `DOMContentLoaded` siga disparando).
- Sin `collectstatic`: `_serve_static` (urls.py) resuelve `/static/*`
  con `finders.find()` directo desde `STATICFILES_DIRS`.
- Tests: la aserción de wiring de recovery-tools se movió al archivo
  `profile.js`; +1 test que fija el include externo con SRI en `/admin/`.

## v0.4.8-django — 2026-07-03 (D-2: re-auth MFA inline + tools de recuperación)

Cierra **D-2** del roadmap: la re-autenticación por contraseña en el
panel MFA de `/profile` dejó de usar los diálogos nativos del navegador
(`window.prompt` / `confirm` / `alert`) y ahora usa **campos de
contraseña inline**, igual que el flujo de desactivación que ya existía.
Validado en `ha-report2` (smoke navegador): activar app, activar email y
regenerar códigos, los tres sin popups nativos.

### D-2 — re-auth inline (commit `fb8e9e1`)

Tres acciones endurecidas contra robo de sesión (PHASE_B A1/A2) pasan a
input inline con toggle de visibilidad:

- **Activar 2FA (app)**: `#profile-mfa-totp-activate-password`.
- **Activar 2FA (email)**: input inline, solo cuando hay email
  registrado (si no, el botón queda deshabilitado como antes).
- **Regenerar códigos**: input inline + leyenda de advertencia +
  feedback `aria-live`, reemplazando el trío `confirm()`+`prompt()`+
  `alert()`.

Cada campo se limpia al éxito, valida vacío con foco y muestra errores
en línea. Los IDs de botón se preservaron, así que los tests de render
apilado siguen verdes. +3 tests que fijan los campos inline y la
ausencia de `window.prompt` en el body servido.

### Fix — tools de recuperación tras regenerar (commit `9a9d7d8`)

El handler de regenerar pintaba los códigos pero **nunca cableaba**
`setupRecoveryTools()`, así que Copiar / Descargar / Imprimir quedaban
muertos tras un regenerado (bug pre-existente, aflorado en el smoke de
D-2). Ahora reusa `showRecoveryOrReload()` — el mismo helper que ya
usan los flujos de enrolamiento app/email — para cablearlos consistente.

### Fallback de copia en HTTP (commit `3889fbd`)

El botón Copiar usaba solo `navigator.clipboard`, gateado a contexto
seguro (HTTPS / localhost). En un deploy HTTP (dev o red interna sin
TLS) degradaba a "copia manual". Se añade un fallback legacy
(`<textarea>` temporal + `document.execCommand('copy')`) que corre
**solo** cuando `window.isSecureContext` es `false`: un deploy
HTTPS/Caddy toma la rama de la Clipboard API moderna y nunca ejecuta
`execCommand`, así el path viejo se auto-desactiva en producción sin
flag. Descargar / Imprimir ya eran independientes del contexto seguro.

Validado en `ha-report2` (HTTP): copiar, descargar e imprimir OK.

## v0.4.7-django — 2026-07-02 (fix: cropper submit síncrono)

Fix del cropper de avatar (v0.4.6): el submit hacía `preventDefault` +
`canvas.toBlob` **async** + `form.submit()` diferido. En un navegador
manual funciona (S-09 pasó), pero rompía el e2e Playwright
`test_avatar_upload_renders_image_in_hero`: el `.click()` retornaba
antes de que arrancara la navegación diferida, `wait_for_url` matcheaba
la URL `/profile/` actual de forma trivial y la aserción corría sobre la
página vieja → 0 imágenes. El CI e2e venía rojo desde el commit del
cropper (`618b451`).

**Fix**: el submit ahora es **síncrono** — se arma el archivo recortado
con `canvas.toDataURL` (síncrono, no `toBlob`) y se hace el swap al
`<input type=file>` vía `DataTransfer` **sin** `preventDefault`, así el
submit nativo serializa el archivo recortado en el mismo tick y la
cadena click→redirect queda síncrona (lo que espera el navegador y el
auto-wait de Playwright). Además simplifica el código (sin callback
async ni re-submit).

Verificado: los 4 tests e2e Playwright verdes en local (chromium).

## v0.4.6-django — 2026-07-02 (cropper de avatar)

Capa de recorte/encuadre en el cliente para el avatar: el usuario elige
**qué mostrar** (pan + zoom) antes de subir, en vez del recorte-al-centro
implícito. Validado en navegador (S-09 en `ha-report2`): el cropper
aparece, drag+zoom responden, el avatar guardado refleja el encuadre
elegido y el archivo en disco es `WEBP (512, 512) EXIF: {}`.

### Cropper de avatar (commit `618b451`)

`setupAvatarCropper()` en `static/js/app.js` revela un canvas cuadrado
al elegir una imagen; pan (pointer + flechas) y zoom (slider). En submit
renderiza el cuadro visible a un canvas 512, lo exporta a Blob y lo mete
al `<input type=file>` vía `DataTransfer` → el submit **nativo** lo sube
y el pipeline D-5 (resize + WebP + strip EXIF) lo procesa.

- **Seguridad/CSP**: la imagen se lee con `FileReader.readAsDataURL`
  (`data:` URL), NO `URL.createObjectURL` (`blob:`), para respetar la CSP
  `img-src 'self' data:` sin relajarla. Sin sinks de Trusted Types
  (solo canvas + `createElement`).
- **Progressive enhancement**: feature-gated
  (canvas/FileReader/DataTransfer). Sin JS, el `<input>` nativo sube el
  archivo crudo y el pipeline lo procesa. El input plano se preserva.
- `templates/accounts/profile.html`: scaffold del cropper dentro de
  `#avatar-form`, oculto por defecto.
- `static/css/app.css`: estilos del cropper (reusa las clases
  `.avatar-crop-*` antes huérfanas).
- `tests/test_profile_avatar_ui.py`: test de presencia del scaffold +
  fallback no-JS intacto.

Sin cambios de dependencias ni migraciones.

## v0.4.5-django — 2026-07-02 (D-5)

Pipeline de transformación de avatar (resize + WebP + strip EXIF).
Validado en servidor (S-08 en `ha-report2`): un avatar subido en wire
queda como `WEBP (512, 512) EXIF: {}` y `verify-audit` → `ok: true`.

### D-5 (commit `da239cd`)

`services/user.py:replace_avatar` ahora pasa cada upload por el nuevo
`services/images.py:transform_avatar` **después del AV scan, antes del
`.save()`**:

- `ImageOps.exif_transpose` — hornea la orientación EXIF en los píxeles.
- `img.thumbnail((MAX, MAX))` — reduce a un cuadrado configurable
  (solo achica, nunca agranda).
- Strip explícito de `exif`/`xmp`/`icc_profile` + re-encode a WebP —
  **este strip es lo que realmente elimina el bloque GPS/PII** (el
  encoder WebP de Pillow re-incrusta `img.info['exif']` si no se limpia).

Un PNG grande de celular (3 MB / 4000px) → WebP ~30 KB / ≤512px sin
EXIF. Transparente para templates (`avatar_url` ya apunta al archivo).

- **Settings** (`settings/media.py`, nuevo): `AVATAR_FORMAT`
  (`webp`/`keep`), `AVATAR_MAX_DIMENSION` (512, clamp 64-2048),
  `AVATAR_WEBP_QUALITY` (82, clamp 1-100). Env `AMELI_APP_AVATAR_*` con
  clamp defensivo — un valor basura no rompe un upload. Registrado en el
  orquestador `settings/__init__.py` (paso 6b).
- **Fallback**: `transform_avatar` devuelve `None` (→ guardar verbatim)
  si el operador puso `keep` o si el transform falla, para que un avatar
  nunca se pierda por un edge case de Pillow.
- **Tests** (`tests/test_avatar_transform.py`, nuevo, 8): resize ≤ MAX +
  WebP, strip EXIF/GPS (con guard anti-vacuo), orientación aplicada,
  `keep` → None, no-upscale, alpha preservado, `.webp` + `avatar_url`
  resuelve, `keep` preserva extensión.

Sin cambios de dependencias ni migraciones.

## v0.4.4-django — 2026-07-01 (PC-4)

Cierre del split de `settings.py`. API pública intacta — Django sigue
leyendo `settings.<NAME>` sin ningún cambio en `urls.py`, middleware o
código externo.

### PC-4 (commit `911aea6`)

`ameli_web/settings.py` (746 líneas) convertido a paquete
`ameli_web/settings/` con 10 módulos:

- `base.py` — `BASE_DIR`, `PROJECT_DIR`, `CFG`, `ENV_NAME`,
  `SECRET_KEY`, `DEBUG`, `ALLOWED_HOSTS`, `TRUSTED_PROXIES`,
  `_int_env`, boot guards secret + debug + hosts + proxies.
- `integrations.py` — CDN SRI, `HEALTH_METRICS_ALLOWLIST`,
  `HIBP_PASSWORD_CHECK`, `AV_ENDPOINT` (+ scheme guard),
  `OTEL_EXPORTER_OTLP_ENDPOINT` (+ scheme guard), `SILK_ENABLED`
  (+ prod second-flag guard).
- `auth.py` — `PASSWORD_HASHERS`, `ARGON2_*`,
  `AUTH_PASSWORD_VALIDATORS`, `AUDIT_HMAC_KEY` (+ prod guard),
  `MFA_ENCRYPTION_KEY` (+ prod guard), `AUTH_USER_MODEL`,
  `LOGIN_URL`, `LOGIN_REDIRECT_URL`, `LOGOUT_REDIRECT_URL`.
- `cookies.py` — SESSION_COOKIE_* (con política `__Host-` +
  guards para Secure y Domain), CSRF_COOKIE_*.
- `security_headers.py` — HSTS, `X_FRAME_OPTIONS`,
  `SECURE_PROXY_SSL_HEADER`, `MESSAGE_STORAGE` (+ allow-list guard).
- `i18n_static.py` — `LANGUAGE_CODE`, `TIME_ZONE`, `LANGUAGES`,
  `STATIC_URL`, `MEDIA_ROOT` + path-inside-checkout guard.
- `database.py` — `_default_sqlite_path`, `_db_pool_options`,
  `_database_settings`, `DATABASES`. Ver "Late-binding de CFG" abajo.
- `applications.py` — `INSTALLED_APPS`, `MIDDLEWARE`, `TEMPLATES`,
  `ROOT_URLCONF`, WSGI/ASGI. Silk apps + middleware condicionales.
- `email.py` — `EMAIL_BACKEND`, SMTP config, `PASSWORD_RESET_TIMEOUT`,
  prod-only email backend guard.
- `__init__.py` — orquestador con orden crítico de imports +
  `# ruff: noqa: I001` para que ruff no reordene (rompería la
  cadena de guards).

### Fixes descubiertos durante la extracción

- **Orden crítico de imports**: ruff `--fix` reordena alfabéticamente
  y rompe la cadena de dependencias (`applications` lee `SILK_ENABLED`
  de `integrations`; `applications` debe cargarse después). Fix:
  `# ruff: noqa: I001` en `__init__.py`.
- **Test helpers `_reload_settings`** en 3 archivos
  (`test_settings_boot_guards.py`, `test_host_cookie_prefix.py`,
  `test_message_storage_guard.py`) solo poppeaban `ameli_web.settings`
  de `sys.modules`. Con package, los submódulos quedaban cacheados y
  los guards no re-corrían. Extendido a wipe de todos los
  `ameli_web.settings*`.
- **Late-binding de `CFG`** en `database.py`: 6 tests hacen
  `monkeypatch.setattr(settings, "CFG", ...)` y luego llaman
  `settings._database_settings()`. En el monolito el helper resolvía
  `CFG` en el mismo módulo → el patch tomaba efecto. En el package,
  `database.py` importaba `CFG` de `.base` al import time → referencia
  frozen. Fix: `_cfg()` que lee `settings.CFG` en cada llamada
  (late-binding a través del package).
- **Helpers privados** (`_database_settings`, `_db_pool_options`,
  `_default_sqlite_path`, `_int_env`, `_IS_DEV_ENV`) no propagados por
  `from .X import *` (drop de underscore names). Re-importados
  explícitamente en `__init__.py`.

### Verificación

- **Suite local Windows**: 1060 pass / 0 fail / 18 skip.
- **Ruff / Mypy**: 0 errores.
- **S-07 aprobado en `ha-report2`**: boot limpio, `manage.py check`
  0 issues, 15 settings symbols importables, valores derivados
  coherentes (INSTALLED_APPS=9, MIDDLEWARE=15,
  SESSION_COOKIE_NAME=`ameli_app_session` en dev,
  EMAIL_BACKEND=console en dev).

## v0.4.3-django — 2026-07-01 (PC-3 + Windows CI cleanup)

Cierre del split de `admin_views.py` + higiene de la suite local en
Windows. API publica intacta — `from ameli_web import admin_views` +
`admin_views.<name>` sigue funcionando sin cambios en `urls.py`.

### PC-3 (commit `a5e37fc`)

`ameli_web/admin_views.py` (745 lineas) convertido a paquete
`ameli_web/admin_views/` con 10 modulos:

- `_common.py` — decoradores (`superadmin_required`, `sudo_required`),
  constantes `*_PER_PAGE_COOKIE`, helpers.
- `panel.py` — `admin_panel` (HTML dashboard).
- `users.py` — 6 endpoints de users (list, update, MFA disable,
  password reset, unlock, admin change_password).
- `audit.py` — `admin_audit`.
- `exports.py` — `_csv_safe`, CSV/JSON export helpers,
  `admin_audit_export`, `admin_users_export`.
- `maintenance.py` — `admin_maintenance_toggle`, `admin_maintenance_status`.
- `metrics.py` — `admin_email_queue_metrics`.
- `sessions.py` — `admin_sessions`, `admin_revoke_session`.
- `sudo.py` — 4 endpoints de sudo (grant, email code, status,
  django-admin gate).

`_csv_safe` re-exportado desde `__init__.py` para preservar el
import directo de `tests/test_security_hardening_block1.py`.

**Fix de regresion durante la verificacion**: mi primera version
hand-written del decorador `sudo_required` devolvia `403 "sudo
required"` — el original devuelve `401 {"need_sudo": true,
"sudo_url": "/admin/sudo/"}` para que la UI prompt-and-retry
transparente. Restaurado antes del push.

### CI cleanup (commits `604ffe2`, `bc55df8`, `d607269`, `2556d74`, `35c8785`)

- 11 tests pre-existentes que fallaban en Windows marcados con
  `pytest.mark.skipif(sys.platform == "win32", ...)` (AF_UNIX, bash
  `sed`, symlink privilegio elevado, `st_dev/st_ino` POSIX inode).
  En CI Linux siguen corriendo sin cambios.
- 1 test corregido para ser cross-platform (`test_autodetect_prefers_
  config_yaml_over_example` usaba `"/config/app.yaml"` en lugar de
  `os.sep`-joined).
- Coverage de `views/` (post-PC-2) subio de ~78% a **96%** con nuevos
  tests para JSON malformado, form-POST invalido, `?partial=` fetch,
  wrong-password branches, `_csv_safe` export edge cases, y las 3
  ramas "generic Exception" (SMTP failure → 502).

### Verificacion

- **Suite local Windows**: 1060 pass / 0 fail / 18 skip (14 nuevos
  skipif Windows + 4 e2e opt-in).
- **CI Linux (bandit + pytest)**: 1031 pass / 0 fail / 6 skip.
- **Ruff / Mypy**: 0 errores.
- **S-06 aprobado en `ha-report2`**: boot limpio con la nueva
  version, 25 admin_views symbols importables, 7 URLs `/admin/*`
  responden 302 sin cookie, browser smoke manual OK (reset password,
  requerir 2FA, cambio obligatorio) — todas las acciones de admin
  panel pasan por `superadmin_required` + `sudo_required` correctos.

## v0.4.2-django — 2026-07-01 (PC-1 cleanup + PC-2)

Cierra el split estructural del paquete `accounts/`: `services/__init__.py`
queda como puro re-export y `accounts/views.py` se convierte en un paquete
por dominios. La API publica esta intacta — todos los imports de
`from ameli_web.accounts.services import X` y de
`from ameli_web.accounts.views import X` siguen funcionando.

### PC-1 cleanup (commit `0268300`)

Extraidos los 4 dominios residuales de `services/__init__.py`:

- `services/retention.py` (194 lineas) — `run_retention_sweep`,
  `_prune_audit_with_anchor`.
- `services/reporting.py` (286 lineas) — `summarize_users`,
  `summarize_email_queue`, `serialize_audit_event`,
  `list_recent_audit_entries`, `_audit_queryset_for_filters`,
  `paginate_audit_for_admin`, `filtered_audit_queryset`,
  `_display_tone_for_action`.
- `services/auth_alerts.py` (189 lineas) — auth-failure alert (ASVS V2.2.3).
- `services/email_change.py` (302 lineas) — double-opt-in flow.

`services/__init__.py` paso de 1104 a ~200 lineas. `EmailChangeRequest`
(modelo) queda re-exportado para preservar `from ameli_web.accounts.services
import EmailChangeRequest`.

### PC-2 (commit `94ce941`)

`accounts/views.py` (1267 lineas) convertido a paquete `accounts/views/`
con 9 modulos por dominio:

- `views/_common.py` (42) — helpers + session keys + logger + User.
- `views/auth.py` (~410) — login + verify MFA.
- `views/profile.py` (~350) — profile page + preferences + avatar + test email.
- `views/password.py` (~285) — change + forgot + reset.
- `views/account.py` (~120) — delete self.
- `views/sessions.py` (~120) — revoke sessions.
- `views/mfa.py` (~225) — 8 MFA endpoints.
- `views/email_change.py` (~210) — 4 email-change endpoints.
- `views/__init__.py` — puro re-export.

`_build_public_base_url` re-exportado desde `views/__init__.py` para tests.

### Fix colateral

`tests/test_code_review_fixes_20260615.py` re-apuntado de
`ameli_web.accounts.services.timezone.now` a
`ameli_web.accounts.services.throttle.timezone.now` (el modulo donde
`_read_throttle_counter_sliding` realmente lee el reloj) tras la extraccion
de `timezone` del top-level de `services/__init__.py`.

### Verificacion

- 1012 tests pass en Windows; 11 pre-existentes de Windows + 1 race
  intermitente del circuit breaker.
- Ruff 0 errores, mypy 0 errores en codigo del paquete.
- S-05 aprobado en `ha-report2`: 29 view symbols importables, 4 rutas
  publicas → 200, 3 privadas → 302, audit chain integro, login manual OK.

## v0.4.1-django — 2026-06-30 (PC-1 cierre)

Refactor interno de `accounts/services.py` (~3793 lineas, un solo modulo) en
un paquete con dominios separados. La API publica esta intacta: todos los
imports de `from ameli_web.accounts.services import X` siguen funcionando.

- Step 2 (commit `58d0061`): `services/audit.py` — cadena de audit, rotacion
  de clave HMAC (462 lineas).
- Step 3 (commit `9bd1233`): `services/throttle.py` — contadores atomicos,
  lockout, rate limits (495 lineas).
- Step 4 (commit `239d34e`): `services/sudo.py` — sudo grants, brute-force
  gate (211 lineas).
- Step 5 (commit `d24b6d8`): `services/email_queue.py` — circuit breaker SMTP,
  outbox pattern, retry queue (426 lineas).
- Step 6 (commit `388e906`): `services/mfa.py` — TOTP, email MFA, recovery
  codes (545 lineas).
- Step 7 (commit `6398881`): `services/session.py` (234 lineas), `services/
  maintenance.py` (83 lineas), `services/password_reset.py` (178 lineas).
- Step 8 (commit `87485f5`): `services/user.py` — CRUD, serialize, avatars,
  password/email change para self, delete account (543 lineas).
- Fix (commit `62c68c8`): lazy imports en `sudo.py` re-targeteados a `.mfa`
  tras el step 6.

`services/__init__.py` queda en 1104 lineas (vs 3793 originales) con
retention sweep, audit reporting, auth-failure alerts y el flow de email
change double-opt-in todavia adentro — esos dominios son candidatos para
futuras iteraciones pero no afectan la limpieza estructural lograda.

Verificacion: 1013 tests pass (mismos 11 failures pre-existentes de Windows,
no son regresion). Ruff 0 errores, mypy 0 errores en codigo del paquete.

## v0.1.0

- Plantilla inicial AMELI para apps Python operacionales.
- Incluye API, dashboard, CLI, workers, PostgreSQL, Alembic, systemd, scripts y
  tests base.

