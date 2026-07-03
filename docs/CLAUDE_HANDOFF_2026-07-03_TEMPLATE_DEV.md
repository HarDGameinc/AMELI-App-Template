## AMELI App Template handoff (sesion Claude, 2026-07-03)

Fecha: `2026-07-03`
Agente: `claude-opus-4-8`
Rama de trabajo: `dev` (HEAD `dd910cc` al abrir → `241eea7` al cerrar, `v0.4.9-django`)
Rama estable: `main` (default en GitHub; `dev` va muy adelante)
Sesion previa: [`CLAUDE_HANDOFF_2026-07-02_TEMPLATE_DEV.md`](CLAUDE_HANDOFF_2026-07-02_TEMPLATE_DEV.md)

## §1. Snapshot al inicio

### Estado del repo / entorno

- El repo local (Windows) estaba en un checkout viejo de `main`
  (commit inicial, huerfano tras un force-update de `origin/main`).
  Se creo `dev` local rastreando `origin/dev` (`dd910cc`) y se borro
  `main` local. `origin/main` intacto en GitHub.
- **Entorno local reconstruido**: no habia `.venv`. Se creo con
  `py -3.14` e instalo desde los **rangos** (no el lock — ver §6.1).
  Stack local: Django **6.0.6** / Pillow **12.3** / Python **3.14.6**.
  El server sigue en Django 5.2.15 / Pillow 12.2 / Python 3.13 via lock.
- Version al abrir: `v0.4.7-django`.

### Metricas al abrir (Windows local)

| Indicador | Valor |
|---|---|
| Unit tests | 1067 pass / 28 skip / **1 fail** (Windows-only, ver §6.2) |
| Ruff | 0 errores |
| Node JS tests | 13 pass |

## §2. Objetivo de la sesion

Elegido por el operador: **D-2 — UX de prompts MFA** (el `window.prompt`
/ `confirm` / `alert` nativo → input inline tipo `mfa_disable`).

## §3. Trabajo realizado

### 3.1. D-2 — re-auth MFA inline (commit `fb8e9e1`, v0.4.8)

`templates/accounts/profile.html`: las 3 acciones endurecidas contra
robo de sesion (PHASE_B A1/A2) que pedian la contrasena via
`window.prompt` pasan a **campo de contrasena inline** con toggle de
visibilidad, replicando el flujo de desactivacion que ya estaba bien:

- **Activar 2FA (app)**: input `#profile-mfa-totp-activate-password`.
- **Activar 2FA (email)**: input inline, renderizado **solo cuando hay
  email** (si no, el boton queda `disabled` como antes).
- **Regenerar codigos**: input inline + leyenda de advertencia +
  feedback `aria-live`, reemplazando el trio `confirm()`+`prompt()`+
  `alert()`.

Cada campo se limpia al exito, valida vacio con foco y muestra errores
en linea. **IDs de boton preservados** (`profile-mfa-activate`,
`profile-mfa-email-activate`) → los tests de render apilado siguen
verdes. +3 tests en `test_mfa_stacked_views.py` (campos inline
presentes, `window.prompt` ausente del body, input email oculto sin
email). El unico `confirm()` restante es el de cancelar cambio de email
(fuera de scope MFA).

### 3.2. Fix — tools de recuperacion tras regenerar (commit `9a9d7d8`)

Bug **pre-existente** aflorado en el smoke de D-2: el handler de
regenerar pintaba los codigos pero **nunca llamaba
`setupRecoveryTools()`**, dejando Copiar / Descargar / Imprimir muertos
tras un regenerado (solo funcionaban en el path de enrolamiento). Fix:
reusa `showRecoveryOrReload()`, el mismo helper que ya usan
enrolamiento app/email, para cablearlos consistente.

### 3.3. Fallback de copia en HTTP (commit `3889fbd`)

El boton Copiar usaba solo `navigator.clipboard`, gateado a **contexto
seguro** (HTTPS / localhost). En el dev server HTTP degradaba a "copia
manual". Se agrego un fallback legacy (`<textarea>` temporal +
`document.execCommand('copy')`) que corre **solo** cuando
`window.isSecureContext === false`. Un deploy HTTPS/Caddy toma la rama
de la Clipboard API moderna y **nunca ejecuta `execCommand`** → el path
viejo se auto-desactiva en prod sin flag (respuesta a la duda de
seguridad del operador).

### 3.4. Docs — quitar `sudo` de comandos de deploy (commit `4bfcaab`)

El server corre como **root** sin binario `sudo` (`sudo: orden no
encontrada`). Se quito el prefijo `sudo` de los comandos de
deploy/install/ops en los 4 docs operativos vivos: `OPERATIONS.md`,
`TLS_WITH_CADDY.md`, `BUILDING_NEW_APP.md`, `FIRST_INSTALL_DJANGO.md`
(este ultimo: `sudo -u postgres psql` → `su - postgres -c psql`). **NO**
se toco el feature "sudo mode" de la app (`services/sudo.py`, sudo
grants, `@sudo_required`, prompt de re-auth admin) ni los handoffs con
fecha / snapshots de compliance/threat.

### 3.5. OPS — CI setup-node@v4 → v6 (post-release)

GitHub avisaba que `actions/setup-node@v4` apunta al runtime node20
(deprecado; lo fuerza a node24 con warning). Se bumpeo a `@v6` (ultima
major, node24) en el job `js-unit` de `ci.yml`. `checkout@v5` y
`setup-python@v6` ya estaban en node24. Sin cambio de `node-version`
(sigue "22" LTS).

### 3.6. Split del JS inline → estáticos (commits `1dcb8ff`, `8e1e5e6`; v0.4.9)

Cierra la deuda frontend "split inline JS". Los 2 `<script>` inline
grandes salen a estáticos externos con SRI, servidos desde `'self'`
(CSP `script-src 'self'`, sin nonce). Refactor sin cambio de conducta,
validado en servidor (ambas páginas responden igual, DevTools limpio).

- **Fase 1** `profile.html` (−532 líneas) → `static/js/profile.js`. Los
  9 `{% url %}` viajan por `data-*` en `#profile-js-config`; CSRF sigue
  del input oculto. Include gateado por `not must_change_password`.
- **Fase 2** `admin/panel.html` (−601 líneas) → `static/js/admin-panel.js`.
  URLs ya eran literales `/admin/*`; único valor inyectado: CSRF vía
  `data-csrf-token` en `#admin-js-config`.
- `base.html`: nuevo `{% block extra_scripts %}` tras `app.js`.
- **Sin collectstatic**: `_serve_static` (urls.py) resuelve `/static/*`
  con `finders.find()` directo de `STATICFILES_DIRS` (git pull + restart
  basta). Confirmado en server: `GET /static/js/{profile,admin-panel}.js`
  → 200 con `integrity`.
- Extracción hecha con script Python (no a mano) para evitar errores de
  transcripción en ~1130 líneas; `node --check` verde en ambos archivos.

### 3.7. De-flake del e2e password-change (commit `ab45de9`)

`test_change_password_then_login` flakeaba ~66% (pegó en 2 de 3 runs
post-split). **No era regresión** (código idéntico pasó en Phase 2):
carrera client-side. Tras el cambio, el JS reescribe el status y recarga
a los ~450ms; el test esperaba `networkidle` (dispara en ese hueco) y
luego enviaba el logout POST → esa POST corría concurrente con el reload
sobre la misma fila de sesión mientras el cambio revoca sesiones →
`SessionStore UpdateError: "Forced update did not affect any rows"` → la
página no navegaba → `Page.fill` timeout. Fix test-only: esperar la
señal determinista `"…Recargando…"` en el feedback y llegar a estado
anónimo con `page.context.clear_cookies()` en vez de correr el logout
POST. Local 5/5 en el test target + 4/4 suite e2e; 2 runs Linux CI
verdes consecutivos. Sin bump (test-only).

### 3.8. Hygiene: `.gitignore` + doc de validate (commits `ce8aa38`, `241eea7`)

- `.gitignore` ahora ignora `*.sqlite3` (las DB locales de dev/e2e
  aparecían untracked; Postgres es la DB real).
- `FIRST_INSTALL_DJANGO.md` §6: el ejemplo de `validate_installation.sh`
  ahora lleva `APP_ENV=dev` (ver §6.3).

## §4. Decisiones tomadas

1. **Bump `v0.4.7` → `v0.4.8-django`** tras validacion en servidor
   (`VERSION` + `pyproject.toml` + CHANGELOG + linea de estado de
   AGENTS.md). D-2 + los 2 fixes de recuperacion van juntos.
2. **Fallback de copia gateado por `isSecureContext`** en vez de un
   flag de config: el path legacy se apaga solo en HTTPS.
3. **Fix del regenerado** aunque era pre-existente: estaba en el handler
   que D-2 tocaba y el operador lo detecto en el smoke.
4. **Docs sudo**: solo comandos shell, no el feature. Solo docs vivos,
   no historicos.

## §5. Metricas al cierre

| Indicador | Valor |
|---|---|
| Unit tests (Windows local) | **1072 pass / 29 skip / 0 fail** |
| Ruff | 0 errores |
| Node JS tests | 13 pass |
| e2e (local + CI Linux) | 4/4; password-change de-flakeado (§3.7) |
| Mypy | limpio salvo 1 falso positivo Windows (`socket.AF_UNIX`, ver §6.1) |
| CI (dev) | verde: matriz 3.11-3.14 + pip-audit + js-unit + e2e |
| Version | `v0.4.9-django` |
| HEAD | `241eea7` |

### Validacion en servidor (`ha-report2`, v0.4.9 contra Postgres)

- `validate_installation.sh` (con `APP_ENV=dev`): **OK=23 / WARN=0 / FAIL=0**.
- `verify-audit`: `{"checked": 301, "ok": true}`.
- `/health/deep`: `db_write` + `fs_write` ok (write path real).
- Smoke navegador: D-2 (MFA inline app/email + regenerar + tools), panel
  admin (mantenimiento, cola email, sudo, CRUD) — todo OK, DevTools limpio.

## §6. Hallazgos / findings

### 6.1. Entorno Windows del operador (nuevo)

- **mypy**: la DLL compilada (mypyc) la bloquea "Control de aplicaciones"
  de Windows (`ImportError: DLL load failed ... Una directiva de Control
  de aplicaciones bloqueo este archivo`). Fix por-venv: reinstalar puro
  Python — `pip install --no-binary mypy --force-reinstall --no-deps
  "mypy==2.1.0"`. Tras eso corre; queda **1** falso positivo
  Windows-only: `accounts/av.py: Module has no attribute "AF_UNIX"`
  (`socket.AF_UNIX` es POSIX-only; el CI Linux da 0 errores).
- **venv**: instalar desde los rangos, NO desde `requirements.lock`
  `--require-hashes` — el lock fija `uvloop` sin marcador de plataforma
  y no compila en Windows (desde los rangos, uvicorn lo omite). Los
  rangos traen Django 6/Pillow 12; suite verde en ambos stacks.

### 6.2. `test_restore_verify_rejects_corrupted_manifest` — win32 skip

El unico fail Windows-only que quedaba del 02-jul: `restore.sh` pasa a
`tar` una ruta con letra de unidad (`C:\...`) que GNU tar interpreta
como host remoto (`Cannot connect to C:`). Se le puso `skipif
sys.platform == "win32"` puntual (no de modulo: varios tests del archivo
si corren y aportan en Windows). Validado en CI Linux. Suite Windows
local ahora **0 fail**.

### 6.3. `validate_installation.sh` defaultea a `APP_ENV=prod`

El script hace `export APP_ENV="${APP_ENV:-prod}"` (a diferencia de
`_common.sh` que defaultea a `dev`). Correrlo pelado en una instancia
**dev** chequea la instancia *prod* (paths + units `*-prod-*` que no
existen) → FAIL espurios (visto en `ha-report2`: OK=0/WARN=11/FAIL=8
mientras `verify-audit` + `/health/deep` daban verde). Con
`APP_ENV=dev bash scripts/validate_installation.sh` → **OK=23**. Se
documento en `FIRST_INSTALL_DJANGO.md` §6 (no se cambio el default del
script para no sorprender a operadores de prod).

## §7. Roadmap actualizado

**D-2 + split inline JS cerrados y validados en servidor.** Version:
`v0.4.9-django`.

### Pendientes ordenados

| # | Item | Costo | Notas |
|---|---|---|---|
| ~~D-2~~ | ~~UX MFA prompts~~ | — | **CERRADO 2026-07-03** (§3.1) — validado smoke navegador en `ha-report2`; bump v0.4.8 |
| ~~Templates~~ | ~~Split inline JS `admin/panel.html` + `profile.html`~~ | — | **CERRADO 2026-07-03** (§3.6) — a `static/js/{profile,admin-panel}.js` con SRI; validado en server; bump v0.4.9 |
| D-1 | Identidad visual | 6-8h | Solo si operador decide |
| Promote | `dev → main` v0.5.0 | — | Requiere instruccion explicita |

### OPS — branch protection (BLOQUEADO por plan, no accionable)

Sumar `Lint + Test (Python 3.13)` y `(Python 3.14)` a los required
status checks de branch protection de `main` **no se puede hoy**:
`gh api .../branches/main/protection` devuelve **403 "Upgrade to GitHub
Pro or make this repository public"**. En el plan Free privado la
feature no existe (ni configurable por API) — o sea, **nada** gatea
`main` actualmente (ni los 3.11/3.12). El payload documentado en
`OPERATIONS.md` §"Branch protection" ya lista los 4 Pythons + pip-audit,
listo para aplicarse el dia que se suba a GitHub Pro/Team o se haga
publico el repo. Sacar de la lista de "pendientes" — es latente, no
olvidado.

## §8. Continuidad — para el proximo agente

### 8.0. Snapshot al cierre

- Rama: **`dev @ 241eea7`**, version **`v0.4.9-django`**. `main` local no
  existe; `origin/main` es el default (congelado — ver 8.2).
- Sesion completa: D-2 (re-auth MFA inline) + 2 fixes de recuperacion +
  docs sudo + CI node24 + **split completo del JS inline** + de-flake del
  e2e password-change + hygiene (gitignore, doc validate).
- **Validado en servidor** (`ha-report2`, Postgres): `validate_installation.sh`
  OK=23/0/0, `verify-audit` 301 ok, `/health/deep` ok, smoke navegador de
  D-2 + panel admin limpio. CI dev totalmente verde.
- Entorno de dev es Windows nativo — ver §6.1 antes de correr checks.

### 8.1. Primer paso (siguiente agente)

Roadmap casi vacio camino a v0.5.0/1.0.0. Queda:
1. **D-1** — identidad visual del template (6-8h; solo si el operador lo
   decide — ver `docs/FRONTEND_DESIGN_REVIEW.md`).
2. **Promote `dev → main`** — bloqueado hasta milestone v0.5.0/1.0.0 por
   decision del operador (8.2); requiere instruccion explicita.
3. Menores: OPS branch-protection (latente, §7), bump `actions/setup-node`
   ya hecho.

### 8.2. Restricciones criticas (siguen vigentes)

- Server pull SIEMPRE de `dev`. `main` **congelado** hasta milestone
  **v0.5.0 o v1.0.0** (decision del operador 2026-07-03); solo avanza por
  instruccion explicita.
- Deploy en el server (root, sin sudo): `git fetch && git reset --hard
  origin/dev` → `.venv/bin/pip install --require-hashes -r
  requirements.lock` (no-op si no cambiaron deps) → `manage.py migrate`
  → `manage.py check` → `systemctl restart
  ameli-app-template-dev-api.service`. Solo template → el restart basta.
- No revertir `current_password` en `start_mfa_*`,
  `regenerate_recovery_codes`, `change_email_for_self`.
- No romper la API publica de `services/` ni de `views/`.
- Correr ruff + mypy + pytest + node tests antes de cada push.
- Bump solo por cierre de fase validado en servidor.
