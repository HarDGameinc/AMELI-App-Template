## AMELI App Template handoff (sesion Claude, 2026-07-14)

Fecha: `2026-07-14`
Agente: `claude-opus-4-8`
Rama de trabajo: `dev` (version `v0.5.4-django`)
Rama estable: `main` (en `v0.5.3-django`)
Sesion previa: [`CLAUDE_HANDOFF_2026-07-13_TEMPLATE_DEV.md`](CLAUDE_HANDOFF_2026-07-13_TEMPLATE_DEV.md)

## §1. Snapshot al inicio

- `dev` == `origin/dev` (ahead 0, behind 0), **arbol limpio**. VERSION
  `v0.5.4-django`.
- **24 commits en `dev` sin promover** a `main` (que sigue en `v0.5.3-django`,
  `2efe4ba`). Contenido v0.5.4: CSP style-src sin `'unsafe-inline'`, Pillow
  12.3.0 (5 CVEs), hardening HSTS (override + default opt-in), tests de
  migraciones (reversibilidad + backfill `0012`) y auditoria aria-live.
- **CI: bloqueado por billing** (verificado: anotacion "job was not started
  because recent account payments have failed or your spending limit needs to
  be increased"). No es codigo. PR #4 (`dev`->`main`) **OPEN + MERGEABLE**,
  todos los checks abortan en <5s. Reset estimado ~1-ago-2026.
- Promocion v0.5.4 **DIFERIDA** por la regla "main solo con CI verde".

## §2. Objetivo de la sesion

**Destrabar y ejecutar la promocion `v0.5.4 -> main`.** El operador notó que
GitHub Actions es **gratis para repos publicos** → hacer el repo publico
elimina el bloqueo de billing sin esperar al reset de ~1-ago.

## §3. Trabajo realizado

### 3.1. Auditoria de secretos previa a publicar (limpia)

Antes de exponer el repo se auditó **todo el historial** buscando secretos
reales: env-vars de secreto de la app, archivos `.env`/`.pem`/`.key`, patrones
Fernet/SECRET_KEY/private-key, passwords en configs, y `detect-secrets` (1.5.0,
con `.secrets.baseline`). **Sin secretos reales** — solo placeholders de doc
(`change-this-django-secret`, `django-insecure-...`), archivos `.example`,
constantes (RECOVERY_ALPHABET), hashes de integridad, y el default dev
`_INSECURE_DEFAULT_SECRET` (rechazado por boot-guard fuera de dev).

### 3.2. Sanitizacion del ground-truth (`a51cf47`)

`OPERATIONS.md`: la tabla hardcodeada de "ground truth" (host, paths, unit
names, puertos) → reemplazada por la instruccion de derivarlo en la caja
(`validate_installation.sh`), alineado con la propia filosofia del doc. El
endpoint publico `dev03.ameli.cl:18480` → placeholders `example.com` en AGENTS
/ SERVER_HARDENING / TLS_WITH_CADDY (ademas hace los docs del template
genericos). **Pendiente/decidido no perseguir:** el nombre de caja `ha-report2`
(bajo valor, ~172 menciones en handoffs archivados) y el **historial git**
(que ya quedó publico un rato antes de sanitizar; purga = reescritura
destructiva, desproporcionada para info de valor modesto). Decision del
operador: aceptar.

### 3.3. Repo publico -> CI destrabado -> 2 hallazgos reales del gate

Con el repo publico, el CI del PR #4 **corrió de verdad** (no mas billing).
Core verde (Python 3.11-3.14 + Postgres + JS). Dos fallas legitimas que el
gate cazó y se arreglaron (`d0ff3f2`):
- **E2E** (test nuevo `test_a11y_announce`): `page.wait_for_function` evalua un
  string en la pagina → lo bloquea el **CSP estricto** de la app (sin
  `'unsafe-eval'`). Fix: `expect(...).to_contain_text()` (via CDP, esquiva el
  CSP como la inyeccion de axe).
- **pip-audit**: `PYSEC-2026-3447` en `setuptools==82.0.1` (dep de build en
  `requirements-dev.lock`, no se despliega), fix en `83.0.0`. Bump manual con
  hashes de PyPI.
Re-run: **8/8 jobs verdes**, PR #4 `MERGEABLE`/`CLEAN`.

### 3.4. Promocion v0.5.4 -> main (EJECUTADA)

Per `RELEASE.md`: **merge commit** (no squash) de PR #4 (`a4db2af`) + **tag +
GitHub release `v0.5.4-django`** en `main` con las notas del CHANGELOG. `main`
ahora en `v0.5.4-django`. Release:
https://github.com/HarDGameinc/AMELI-App-Template/releases/tag/v0.5.4-django

### 3.5. Tooling de seguridad desbloqueado por el repo publico (`1911e59`)

Gratis para repos publicos. **CodeQL** (SAST, python + JS) + **Dependabot**
solo para `github-actions`.

**Dependabot para `pip` NO se habilito, a proposito** (documentado en el propio
`dependabot.yml` para que nadie lo "arregle"): los locks son
`requirements*.lock` (pip-compile, hash-pinned) — nombres que Dependabot no
descubre. Abriria PRs bumpeando los `.txt` sueltos dejando el `.lock` stale →
CI en rojo y `pip-audit` viendo el pin viejo. Y `pip-audit` **ya corre sobre el
lock real** en cada push **y en el cron semanal** (`ci.yml`), que es lo que cazo
PYSEC-2026-3447. Es mas preciso que Dependabot para este layout.

### 3.6. CodeQL: 16 alertas -> 1 hallazgo REAL, arreglado (`8f666f8`)

Triage completo (14 FPs, 2 reales). CodeQL se pago solo en la primera corrida.

**🔴 REAL — `py/weak-sensitive-data-hashing` en `mfa.py:hash_email_code`:**
el codigo MFA por email es de **6 digitos** (10⁶ ≈ 2²⁰) y su digest se persiste
en `MFAEmailChallenge.code_hash` con **SHA-256 plano** → cualquiera que **lea**
esa tabla (SQLi, backup filtrado, dump robado) agota el espacio en milisegundos
y recupera el segundo factor vivo. **Contradecia el propio modelo de amenaza**:
el `mfa_secret` (TOTP) ya se encripta at-rest justamente por esto; el codigo de
email era el hueco. **Fix:** `django.utils.crypto.salted_hmac` — keyea el digest
en `SECRET_KEY` (que nunca vive en la DB) con domain separation. La DB sola ya
no sirve. `hash_recovery_code` **mantiene SHA-256 a proposito** (~60 bits de
entropia; keyearlo invalidaria todos los codigos ya emitidos) — hay test que
fija esa asimetria. **Verificado: CodeQL bajo de 4 a 3 alertas de esa regla.**

**🟠 REAL (rastreado desde el sink) — echo de excepciones SMTP:** `auth.py`,
`mfa.py` y `profile.py` ecoaban `{exc.__class__.__name__}: {exc}` al cliente.
`auth.py` es alcanzable **PRE-MFA** (solo `@require_POST`) y los otros dos son
solo `@login_required` → nombres de mail-host y fallos de auth/TLS se filtraban
a usuarios sin privilegio. El comentario de `profile.py` decia que era una
afordancia de operador, pero **la vista no estaba gateada a superadmin**. Fix:
`auth`/`mfa` devuelven mensaje generico; `profile` **conserva el detalle solo
para superadmins** (que ya tienen acceso total). `logger.exception` sigue
guardando el traceback en el journal en los tres.

**14 FPs descartados** en el Security tab con razon auditable (HIBP SHA-1 es
protocolo; `audit.py` es HMAC-SHA256 correcto; recovery codes de alta entropia;
`settings_summary` redacta el DSN; el export es `attachment` no-HTML; `/health`
es IP-allowlisted; el resto son asserts de test). **Security tab: 0 abiertas.**

Suite **1118 passed / 58 skipped**, ruff limpio.

### 3.7. Release de seguridad v0.5.5 (`57ba3c0`) + server sync

Cortado y promovido **v0.5.5-django** (bump ritual: VERSION+pyproject+
CHANGELOG+AGENTS) con el fix de MFA de §3.6 como headline. Validado en server
(`manage.py check` 0 issues, arranque limpio, `/health` OK), PR #5 **CI 8/8
verde incluido el E2E de email-MFA** (que ejercita el flujo con el hash
keyeado nuevo), merge commit + release con **nota de seguridad** para apps
hijas (per `DECISIONS.md #7`). `main` = `v0.5.5-django`; server pulleado y
corriendo v0.5.5.

### 3.8. Dependabot encarrilado (`cd7c0f4`)

Dependabot abrio sus primeros 3 PRs (bumps de actions) — todos verdes 11/11
pero **apuntando a `main`** (saltea el flujo). Aplicados los bumps en `dev`
(checkout v5→v7, codeql-action v3→v4, setup-node v6→v7) + `target-branch: dev`
en `dependabot.yml` para que futuros PRs sigan la promocion. PRs #6/#7/#8
cerrados como superseded.

### 3.9. Dry-run "build a child app" — 3 bugs reales (`2bfe6ad`)

**El camino que justifica el template nunca se habia ejecutado.** Dry-run
completo (app hija en scratch, siguiendo `BUILDING_NEW_APP.md`):
- **§2 estaba mal**: decia que el rename de paquetes `ameli_app`/`ameli_web`
  era obligatorio (tabla de 5 filas). Realidad: **conservar los nombres
  funciona out-of-the-box** (1118 tests + ruff + `check` 0 issues); seguir la
  tabla deja **~740 refs rotas en ~250 archivos** y la app **ni arranca**. Y
  el tip de verificacion (`pytest` post-rename) da **falso positivo** si el
  template esta `pip install -e` en el venv (caimos en la trampa). Reencuadrado:
  keep-names = default; rename = opcional/cosmetico, refactor scripteado en
  venv limpio.
- **`cli._json()` crasheaba** con output no-ASCII (`print` + consola cp1252) →
  `UnicodeEncodeError`. **Ironia**: el 🔴 de nuestras notas de v0.5.5 rompia
  `template-check`, la herramienta con la que una hija se entera de esa misma
  nota. Fix: reconfigure UTF-8.
- **`template-check`** daba `github api 403` opaco al ratelimitear (anon =
  60/h por IP). Fix: detecta `X-RateLimit-Remaining: 0` → mensaje accionable
  (set `GITHUB_TOKEN`).
- El **diseño del update-channel es correcto** (con token: reporta current/
  latest/status/URL/excerpt). Solo los bordes estaban rotos.

+2 tests de regresion. Suite **1120 passed**, ruff limpio.

## §4. Pendiente / proximos pasos

- **Sync del server: HECHO.** `ha-report2` pulleado a v0.5.4 (branch `dev`,
  `3038588`), `-api.service` reiniciado, `/health` → `v0.5.4-django` OPERATIVO,
  region a11y `#a11y-live` verificada servida en `/login/`. Runtime deps sin
  cambio (no reinstall); estaticos servidos desde el source dir (no
  collectstatic). **Fix de estado git:** el `dev` local de la caja no tenia
  upstream → `git pull` caia al HEAD del remoto (`main`) y aterrizo en el merge
  commit `a4db2af`; se corrigio con `git branch --set-upstream-to=origin/dev
  dev` (+ se borro un `main` local espurio). Ahora `dev` trackea `origin/dev`.
- **Sync del server a v0.5.5: HECHO** (§3.7). Pendiente: pullear
  `2bfe6ad` (fixes del dry-run) — todo docs/CLI, sin efecto runtime; puede
  esperar a la proxima release.
- **Toggles del repo (tuyos, no los toca el agente):** al cierre la API
  reportaba `secret_scanning`, `push_protection` y `dependabot_security_updates`
  = **disabled**. Activar en Settings → Code security: secret scanning + push
  protection + **Dependabot alerts** (NO las *security updates* automaticas —
  chocan con el lockfile hash-pinneado) + Private Vulnerability Reporting.
- **Historial git**: ground-truth viejo; decision = aceptar (no purgar).
- **Backlog** (bajo valor): jsdom DOM-wiring, visual regression, Model C
  update-channel (`ameli-core` paquete), Django LTS 6.2 (~dic-2026).
- **No hay apps hijas todavia.** El camino de fork quedo **probado y
  corregido** (§3.9) — la primera hija real deberia arrancar sin sorpresas.
