## AMELI App Template handoff (sesion Claude, 2026-07-06)

Fecha: `2026-07-06`
Agente: `claude-opus-4-8`
Rama de trabajo: `dev` (HEAD `3daffc5` al abrir; version final `v0.4.11-django`)

> **Nota**: la sesion se extendio tras un primer cierre. Bloque 1 (docs +
> Postgres-CI + a11y, `v0.4.10`) esta abajo; el Bloque 2 (a11y+ tema
> oscuro/teclado `v0.4.11` + doc de theming) se resume en §3.5 y §6.4.
Rama estable: `main` (default en GitHub; congelado hasta v0.5.0/v1.0.0)
Sesion previa: [`CLAUDE_HANDOFF_2026-07-03_TEMPLATE_DEV.md`](CLAUDE_HANDOFF_2026-07-03_TEMPLATE_DEV.md)

## §1. Snapshot al inicio

- `dev` local estaba **16 commits atras** de `origin/dev`, working tree
  limpio → fast-forward a `3daffc5` (traia la sesion 2026-07-03: D-2 MFA +
  split del JS inline, `v0.4.9-django`).
- Version al abrir: `v0.4.9-django`.
- Entorno dev: Windows nativo, venv Python 3.14 desde los rangos (Django
  6/Pillow 12 local; server en Django 5.2.15 LTS via lock). Ver §6 del
  handoff 2026-07-03 para las gotchas de Windows.

## §2. Objetivo de la sesion

Instruccion del operador (del handoff previo §8.1.1): **integrar el set de
docs para agentes ANTES de seguir desarrollando**, y luego continuar con
desarrollo. Se hizo eso: docs → Postgres-en-CI → tests de accesibilidad.

## §3. Trabajo realizado

| Commit | Tema | Tests |
|---|---|---|
| `827467e` | Docs para agentes: CONTRIBUTING + RELEASE + DECISIONS | n/a (docs) |
| `0833102` | CI: correr la suite contra PostgreSQL | verde |
| `1c5dcd1` | Docs: marcar Postgres-in-CI hecho | n/a |
| `8207a01` | Docs: corregir claims stale de SQLAlchemy/Alembic | n/a |
| `254948e` | a11y: smoke axe-core WCAG + fixes de lo que encontro | 4/4 a11y + 1068 unit |
| `c1e2d5f` | Bump `v0.4.10-django` (tras smoke server) | — |

### 3.1. Set de docs para agentes (`827467e`)

Ejecuta `DOCUMENTATION_PLAN.md` (marcado DONE). Consolida el "como
trabajamos" y el "por que" que solo vivian en handoffs fechados:

- **`CONTRIBUTING.md`** (root): ramas (`dev` / `main` congelado), commits
  (Conventional + footer Co-Authored-By), los 4 pre-push checks
  (ruff/mypy/pytest/node), notas de dev en Windows (venv desde rangos,
  mypy `--no-binary`, tests POSIX skipeados, env vars locales).
- **`docs/RELEASE.md`**: esquema `vX.Y.Z-django`, ritual de bump de los 4
  archivos, politica "bump solo tras validacion en server". Nota que
  nada testea `VERSION` == `pyproject` (disciplina, no test).
- **`docs/DECISIONS.md`** (ADR-lite): Django 5.2 LTS (no FastAPI, no 6.0),
  server-rendered + vanilla JS sin build, config via `data-*`,
  Postgres/SQLite, minimalismo de deps, postura de seguridad.
- Registrados en el indice de docs de `AGENTS.md`. Alcance: **Core 3**;
  SBOM/PRIVACY diferidos (crear si se va a "productivo/critico").

### 3.2. PostgreSQL en CI (`0833102`, `1c5dcd1`)

Top pick de `TECH_EVOLUTION.md`. El CI + local corrian en **SQLite** pero
prod es **Postgres**, y el comportamiento diverge — sobre todo
`select_for_update()` (el gate de throttle) es un lock real en Postgres y
casi un no-op en SQLite. Nuevo job `test-postgres` en `ci.yml`:
`services: postgres:16`, `DATABASE_URL` apuntando ahi
(`settings/database.py` conmuta a Postgres cuando esta seteado), Python
3.13 (la del server), `migrate` + suite unitaria. Sin coverage gate (la
matriz SQLite ya lo tiene); este job es por fidelidad de backend. Verde
en CI. Doc actualizada (top pick hecho).

### 3.3. Correccion de docs stale de SQLAlchemy/Alembic (`8207a01`)

Investigando el item #2 de `TECH_EVOLUTION.md` ("remove SQLAlchemy/
Alembic") resulto que **ya estaba hecho**: no esta en `pyproject.toml` /
`requirements*.txt` / `requirements.lock` ni se importa en `src/`.
`ameli_app/database.py` ya reemplazo su motor SQLAlchemy (health probe
`SELECT 1`) por `connection.cursor()` de Django. El unico residuo es
intencional (el parser de DSN tolera esquemas `postgresql+psycopg://`).
Se corrigieron los 3 docs que lo daban por "configured-but-unused"
(`TECH_EVOLUTION.md`, `AGENTS.md` "what not to port", `DECISIONS.md` #4)
para que un futuro agente no persiga un cleanup inexistente.

### 3.4. Tests de accesibilidad + fixes (`254948e`)

Cierra el gap "no accessibility tests". Enfoque que encaja con el stack
(sin dep pip nueva, sin tocar el lock): **axe-core 4.10.2 vendoreado**
(`tests/e2e/vendor/axe.min.js`, MPL-2.0, test-only) inyectado via
`page.evaluate` (corre sobre CDP → sortea la CSP sin relajarla). Gatea
**critical + serious** (WCAG 2.1 A/AA) en login/dashboard/profile/admin.
Va a `tests/e2e/` → el job e2e del CI lo corre solo.

El primer run encontro violaciones **reales**, arregladas:

- **`select-name` (critical)**: los 4 `<select>` de filtro admin sin
  nombre accesible → `aria-label` (`users_role`, `users_status`,
  `audit_outcome`, `admin_sessions_status`).
- **`color-contrast` (serious)**: `--muted` (#687385) y `--warn`
  (#b46a00) del tema claro caian apenas bajo 4.5:1 sobre fondos
  casi-blancos → #5b6472 / #a15e00.
- **`.password-policy-item.fail`** usaba un durazno claro (#ffcfbf)
  pensado para fondo oscuro (~1.3:1 en blanco) → `var(--bad)`, por-tema
  (#b42318 claro / #e5564a oscuro), legible en ambos.

Atribucion axe-core en `THIRD_PARTY_LICENSES.md`; gap de a11y de
`AGENTS.md` actualizado.

### 3.5. a11y+ — tema oscuro + teclado (commits `5a86106`, `dcd2a17`, v0.4.11)

Extension del smoke a11y (§3.4). Ahora axe corre cada pagina en **claro
Y oscuro** (`page.emulate_media`), se agrega `/login/forgot/` y 2 checks
de **teclado** (skip-link es el primer Tab stop y apunta a `<main>`; el
form de login es alcanzable). El mensaje de fallo imprime fg/bg/ratio.

El tema oscuro destapo contraste sistematico que el claro no tenia: el
palette oscuro reusa colores brillantes (correctos como texto/iconos)
como **fondos rellenos** con texto blanco, cayendo bajo 4.5:1 — botones
primarios (3.16:1), status pills (2.83:1), danger. Fix con **tokens
`--*-fill`** (color de fondo relleno bajo texto blanco): claro = base,
oscuro = variantes mas oscuras que superan 4.5:1. Estructura de tokens
durable (un futuro D-1 la conserva). 12/12 a11y verde (5 pag x 2 temas +
2 teclado). Bump `v0.4.11` tras smoke visual del tema oscuro en server.

### 3.6. Doc de theming (`docs/THEMING.md`)

Nuevo doc que explica los 3 modos (Claro/Oscuro/Auto), que Auto delega en
`prefers-color-scheme`, y el gotcha que confundio al operador (§6.4).
Registrado en el indice de `AGENTS.md`.

## §4. Decisiones tomadas

1. **Docs primero** (instruccion del operador): Core 3 como archivos
   separados; SBOM/PRIVACY diferidos.
2. **Postgres en CI en un solo Python (3.13)** — la matriz ya cubre el
   spread de versiones en SQLite; este job es fidelidad de backend, no
   cobertura.
3. **axe-core vendoreado, no dep pip** — evita regenerar el lock hasheado
   (que no se puede en Windows por `uvloop`); test-only, MPL sin impacto
   en la licencia MIT.
4. **Gate a11y en critical+serious** (no moderate/minor) — bar accionable
   sin perseguir cada nit cosmetico el dia 1.
5. **`.fail` → `var(--bad)`** en vez de un color hardcoded por tema —
   una sola regla que funciona en claro y oscuro.
6. **Bump `v0.4.10`** tras smoke visual en server (los cambios de
   contraste son user-visible).

## §5. Metricas al cierre

| Indicador | Valor |
|---|---|
| Unit tests (Windows local) | **1068 pass / 37 skip / 0 fail** |
| a11y (Playwright axe) | 4/4 (login/dashboard/profile/admin) |
| Node JS tests | 13 pass |
| Ruff | 0 errores |
| CI (dev) | verde: matriz 3.11-3.14 + **test-postgres** + e2e + js-unit + pip-audit |
| Version | `v0.4.9` → **`v0.4.10-django`** |
| HEAD | `c1e2d5f` |

### Validacion en servidor (`ha-report2`)

- Sync a `c1e2d5f`, `manage.py check` 0 issues, servicio `active`,
  `/health` → `v0.4.10-django`.
- Smoke visual: checklist de politica de contraseña con items no
  cumplidos en **rojo legible** (era durazno casi invisible), dropdowns
  de filtro admin OK, nada roto por el cambio de contraste.
- Nota: el server NO corre axe (sin Playwright/chromium por regla del
  proyecto) — la a11y se valida en CI Linux; el smoke server es visual.

## §6. Hallazgos / findings

### 6.1. El gate a11y encontro 3 clases de violaciones reales

Ver §3.4. Todas arregladas. Quedan (no bloqueantes hoy): a11y del **tema
oscuro** no se testea (chromium default = claro); sub-vistas admind mas
alla del panel; flujos de teclado. Candidatos a cobertura mas profunda.

### 6.2. Carrera de restart en el smoke de `/health`

`systemctl restart` retorna antes de que uvicorn levante; un `curl`
inmediato pega cuerpo vacio → `json.load` explota. No es bug: esperar
readiness (`for i in $(seq 1 10); do curl -sf .../health && break; sleep
1; done`) antes de leer la version.

### 6.4. Tema "Auto" oscuro en Firefox — NO es bug (documentado)

En el smoke de a11y+, el operador vio la app oscura con tema **Auto**
aunque Windows se veia claro. Diagnostico completo (con capturas):

- `matchMedia('(prefers-color-scheme: dark)').matches` → **`true`** → el
  navegador reporta oscuro, asi que Auto se ve oscuro **correctamente**.
- Reproducido en **Firefox** solamente; Chrome/Brave/Edge se veian claros.
- **Modo de resolucion de problemas** de Firefox (extensiones off) →
  seguia `true` → **NO es una extension** (se descarto FortiClient), es
  **politica de la org / pref del SO** (`ui.systemUsesDarkTheme`). El
  Firefox estaba "administrado por su organizacion".

**La app es correcta** — `active_theme=""` en Auto → sin `data-theme` →
`@media prefers-color-scheme` manda. Fix es del lado del navegador
(Website appearance → Claro) o usar el tema explicito del perfil.
Documentado en `docs/THEMING.md` para que no vuelva a confundir.

## §7. Roadmap actualizado

**Docs + Postgres-CI + a11y + a11y+ cerrados.** Version
`v0.4.11-django`. La cola high/medium de `TECH_EVOLUTION.md` quedo
**agotada** (el #2 SQLAlchemy ya estaba hecho; solo restan Low/optional:
`django-csp`/`prometheus_client`, Ansible, jsdom-level JS tests — ninguno
urgente).

### Pendientes ordenados

| # | Item | Costo | Notas |
|---|---|---|---|
| ~~a11y+~~ | ~~Tema oscuro + teclado~~ | — | **CERRADO 2026-07-06** (§3.5) — claro+oscuro + keyboard; tokens `-fill`; v0.4.11 |
| a11y++ | Modales (sudo/MFA) con focus-trap | 1h | Menor; lo que resta de a11y |
| D-1 | Identidad visual | 6-8h | Solo si operador decide — ver `FRONTEND_DESIGN_REVIEW.md` |
| Promote | `dev → main` v0.5.0 | — | `main` congelado; requiere instruccion explicita |
| Low/opt | `django-csp`, Prometheus lib, Ansible, jsdom | — | Ninguno urgente (`TECH_EVOLUTION.md`) |

### OPS — branch protection (latente, no accionable)

Sigue bloqueado por el plan Free privado (`gh api .../protection` → 403).
Nada gatea `main` hoy; el payload en `OPERATIONS.md` esta listo para el
dia que se suba a Pro/Team o se haga publico. No es olvido.

## §8. Continuidad — para el proximo agente

### 8.0. Snapshot al cierre

- Rama **`dev`**, version **`v0.4.11-django`**, todo pusheado.
  `main` congelado.
- Sesion: docs para agentes (CONTRIBUTING/RELEASE/DECISIONS) + Postgres en
  CI + correccion de docs SQLAlchemy + tests de accesibilidad (axe-core,
  claro+oscuro + teclado) + fixes de contraste (tokens `-fill`) +
  `docs/THEMING.md`.
- Validado: CI dev totalmente verde (matriz 3.11-3.14 + Postgres + e2e con
  12 checks a11y + js-unit + pip-audit); smoke visual en `ha-report2`
  (tema oscuro impecable). El tema Auto/oscuro en Firefox se diagnostico
  como browser/politica, no bug (§6.4, `THEMING.md`).
- Entorno dev = Windows nativo (ver `CONTRIBUTING.md` "Local dev
  environment"). `gh` CLI conectado (en `C:\Program Files\GitHub CLI\`,
  no en PATH de las shells — invocar por ruta).

### 8.1. Primer paso (siguiente agente)

Elegir del roadmap §7. No hay item "obligatorio" pendiente — la deuda
tecnica y de docs esta al dia. Candidatos: a11y mas profundo (bounded),
D-1 identidad visual (grande, requiere decision del operador), o Low/opt.

### 8.2. Restricciones criticas (siguen vigentes)

- Server pull SIEMPRE de `dev`. `main` congelado hasta v0.5.0/v1.0.0;
  solo por instruccion explicita, via PR.
- Deploy (root, sin `sudo`): `git fetch && git reset --hard origin/dev` →
  `pip install --require-hashes -r requirements.lock` (no-op si no
  cambiaron deps) → `migrate` → `check` → `systemctl restart
  ameli-app-template-dev-api.service`. Esperar readiness antes de leer
  `/health` (§6.2).
- No revertir `current_password` en `start_mfa_*`,
  `regenerate_recovery_codes`, `change_email_for_self`.
- No romper la API publica de `services/` ni de `views/`.
- Correr ruff + mypy + pytest + node tests antes de cada push.
- Bump solo por cierre de fase validado en servidor.
- No instalar Playwright/chromium en el servidor (a11y/e2e se validan en
  CI Linux).
