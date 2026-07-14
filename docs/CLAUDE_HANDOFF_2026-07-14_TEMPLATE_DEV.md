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

## §4. Pendiente / proximos pasos

- **Sync del server: HECHO.** `ha-report2` pulleado a v0.5.4 (branch `dev`,
  `3038588`), `-api.service` reiniciado, `/health` → `v0.5.4-django` OPERATIVO,
  region a11y `#a11y-live` verificada servida en `/login/`. Runtime deps sin
  cambio (no reinstall); estaticos servidos desde el source dir (no
  collectstatic). **Fix de estado git:** el `dev` local de la caja no tenia
  upstream → `git pull` caia al HEAD del remoto (`main`) y aterrizo en el merge
  commit `a4db2af`; se corrigio con `git branch --set-upstream-to=origin/dev
  dev` (+ se borro un `main` local espurio). Ahora `dev` trackea `origin/dev`.
- **Historial git**: quedó con el ground-truth viejo; decision de aceptar (no
  purgar). Si en el futuro se quiere purgar → `git filter-repo` + force-push
  (destructivo, coordinar).
- **Backlog** (bajo valor): jsdom DOM-wiring, visual regression, Model C
  update-channel, Django LTS 6.2 (~dic-2026).
