## AMELI App Template handoff (sesion Claude, 2026-07-16)

Fecha: `2026-07-16`
Agente: `claude-opus-4-8`
Rama de trabajo: `dev` (version `v0.5.7-django`, HEAD `4a6151c`)
Rama estable: `main` (en `v0.5.7-django`, `216a6e7`; al dia)
Sesion previa: [`CLAUDE_HANDOFF_2026-07-15_TEMPLATE_DEV.md`](CLAUDE_HANDOFF_2026-07-15_TEMPLATE_DEV.md)

## §1. Snapshot al inicio

- `dev` **local estancado**: `ae43349`, **0 adelante / 32 detras** de
  `origin/dev` (la sesion 07-12 no habia vuelto a sincronizar). Arbol limpio.
- `main` en **v0.5.6-django**; en el intertanto se cortaron v0.5.4/5/6 (otras
  sesiones). Quedaba un `sbom-v0.5.3.cdx.json` stray (gitignored, obsoleto).
- **Frente abierto** (handoff 07-15 §5): 5 bugs del path Docker/compose de dev,
  **verificados pero SIN arreglar** — punto de arranque explicito.

## §2. Objetivo de la sesion

Ritual de inicio de dia (sync local vs remoto + limpieza + revisar docs para
continuar) → arreglar los 5 bugs Docker/compose de §5 → cortar **v0.5.7** y
**verificar template vs la app hija Starlink** (de donde salieron los bugs).

## §3. Trabajo realizado

| Commit | Tema | Tests |
|---|---|---|
| `7093da5` | fix(docker): 5 bugs del path Docker/compose de dev | green (1126) |
| `05f0c51` | fix(gitattributes): `*.gif binary` (de la verificacion de la hija) | green |
| `4a6151c` | chore(release): v0.5.7-django | green |
| `216a6e7` | merge PR #10 `dev → main` (release commit) | CI 15/15 |

### 3.1. Sync + limpieza local

`git merge --ff-only origin/dev` (0 adelante → ff limpio, sin divergencia) llevo
`dev` local a `e6f8f7e`. Borrado el `sbom-v0.5.3.cdx.json` stray.

### 3.2. Los 5 fixes Docker/compose (`7093da5`)

Todos tocan **solo** el path Docker/dev + line-endings — `src/` y el deploy
systemd/prod **no se afectan**.

1. **compose: env vars inertes.** El codigo lee
   `AMELI_APP_DJANGO_{SECRET_KEY,DEBUG,ALLOWED_HOSTS}` (`config.py:249-250`,
   `base.py:45`); el compose seteaba las formas sin `DJANGO_` → caia al
   SECRET_KEY default inseguro + `DEBUG=False`. Renombradas en `api`+`notifier`,
   `APP_ENV=dev` + `AMELI_APP_MFA_ENCRYPTION_KEY` (Fernet dev) agregadas.
2. **Dockerfile: `ModuleNotFoundError: ameli_web`.** El `.pth` del editable
   apuntaba a `/build/src` (ausente en runtime). Fix: `ENV PYTHONPATH=/app/src`.
3. **Dockerfile: instalaba rangos, no el lock.** `pip install -r
   requirements.txt` → ahora `--require-hashes -r requirements.lock` +
   `pip install -e . --no-deps` (paridad prod) + un target **`dev`** que agrega
   `requirements-dev.lock` para `docker compose run --rm api pytest`; compose
   `api build.target: dev`. Imagen `runtime`/prod queda lean.
4. **Dockerfile: no copiaba `VERSION`** → `/health` = `v0.0.0-dev`. Fix:
   `COPY VERSION ./VERSION`.
5. **Falta `.gitattributes`** → Windows autocrlf rompia `.sh` en Linux. Agregado;
   `git add --renormalize` fue **no-op de contenido** (blobs ya en LF).

Extra: comentario del compose `.venv/bin/ameli-app` → `ameli-app` (venv en
`/opt/venv`). **+6 tests de regresion** en `test_docker_stack.py`.

### 3.3. Verificacion template vs hija Starlink

`AMELI Report Starlink` (fork de v0.5.6, `TEMPLATE_LINEAGE=v0.5.6-django`): su
`Dockerfile` y `docker-compose.yml` son **identicos a las versiones viejas con
bugs** — solo tenia `.gitattributes`. Sin `docker-compose.override.yml` (el que
mencionaba el 07-15 ya no existe). Sin remote `template`. → **valida** que los 5
fixes son correctos y necesarios. Su `.gitattributes` incluia `*.gif binary`
(mejora adoptada en el template, `05f0c51`).

### 3.4. Corte v0.5.7 (`4a6151c`, PR #10, `216a6e7`)

Bump de 4 archivos (VERSION/pyproject/CHANGELOG/AGENTS), framing de mantenimiento
sin cambio de runtime. PR #10 **CI 15/15 verde** (matriz 3.11-3.14 + E2E +
test-postgres + CodeQL + pip-audit), merge commit `216a6e7` + tag/release. Se le
paso al operador un **prompt autocontenido** para que la sesion de la hija aplique
u obtenga los fixes.

### 3.5. DECISIONS #8 — estrategia de entorno de dev (`a5ccf3d`)

A raiz de la pregunta del operador ("Docker consume mucho del plan, ¿directo en
Windows, Windows+Docker, o VM Linux?"), quedo formalizada en `DECISIONS.md` #8
la **estrategia por capas**: **Windows directo** es el loop diario por defecto
(mas barato/rapido; CI Linux respalda lo que win32 skipea); **WSL2** para
paridad Linux on-demand (tests shell/systemd, lock hash-pinneado con `uvloop`,
builds Docker mas rapidos — clonar en filesystem Linux, no en `/mnt/c`); **Docker
FUERA del loop del agente** (`test_docker_stack.py` + CI son el guard de
rutina; builds ocasionales/manuales para validar los artefactos). Puntero desde
"Windows notes" de `CONTRIBUTING.md`. No se duplico en memoria: la decision
durable vive en el repo.

### 3.6. Setup WSL2 + correccion two-locks (`88700d3`)

Instalado **Ubuntu 24.04.4 LTS** (WSL v2.7, kernel 6.18) via `wsl --install
-d Ubuntu-24.04 --no-launch` (evita el prompt de crear usuario). Usuario
`hardg` (uid 1000, sudo passwordless, sin contrasena — no se manejaron
credenciales), default en `/etc/wsl.conf`. Repo clonado a **filesystem Linux**
(`/home/hardg/ameli-app-template`) desde `/mnt/c/...`, con `origin` apuntado
al HTTPS publico. Venv desde el lock con `--require-hashes`; **paridad real
verificada**: `uvloop==0.22.1` (imposible en Windows) + `django==5.2.16` (el
pinneado que shipea, no el 6.x que Windows saca de los rangos). El `file`
sobre `scripts/_common.sh` confirmo **LF** (fix #5 validado end-to-end en un
checkout Linux real).

**Hallazgo importante en el camino:** los dos locks son **complementarios,
no superset/subset** (yo habia inferido superset). `requirements.lock` trae
el runtime (`uvicorn[standard]`, `uvloop`, `httptools`); `requirements-dev.
lock` trae el tooling (pytest/ruff/mypy/pip-audit); **`django` esta en ambos
solo porque `pytest-django` lo arrastra** — de ahi la confusion. Un env dev
completo necesita **ambos**. Se corrigio: comentario del `Dockerfile` (el
*comportamiento* siempre fue correcto — el target `dev` hereda de `builder`,
asi que ambos locks quedan en la imagen), `DECISIONS.md` #8 y `CONTRIBUTING.
md` con el procedimiento correcto y numeros medidos.

**Suite completa en WSL2: `1156 passed / 28 skipped`** — 30 tests mas que en
Windows (1126/58): los shell/systemd/backup que win32 skipea, ahora todos
verdes en Linux nativo.

Prompt de adopcion para la app hija Starlink entregado al operador (WSL2 ya
esta machine-wide → la hija solo hace su propio clone Linux-fs y aplica el
mismo procedimiento de ambos locks; incluye el gotcha two-locks para
ahorrarles el mismo tropiezo).

## §4. Decisiones tomadas

- **Docker #3 = target `dev` separado** (no solo corregir el comentario): el
  compose ya documenta `docker compose run api pytest`, hacerlo funcionar de
  verdad vale mas que el costo (Dockerfile un poco mas grande); multi-stage
  mantiene la imagen prod lean. (Operador delego: "segun tu recomendacion".)
- **Adoptar `*.gif binary`** del `.gitattributes` de la hija (el pipeline de
  avatares acepta `image/gif`).
- **v0.5.7 no requiere validacion en server ni redeploy**: cero cambio de runtime
  de prod (solo path Docker/dev). SBOM omitido (deps sin cambio vs v0.5.6).
- **DECISIONS #8 — Windows/WSL2/Docker por capas** (ver §3.5). Trade-off aceptado:
  el drift de Windows (Django 6, ~30 tests skipeados) queda cubierto por CI Linux
  como fuente de verdad; agentes no meten Docker en el inner loop.
- **Ubuntu 24.04 LTS como distro WSL** (no 22.04 ni 26.04): Python 3.12 default,
  matchea el `PYTHON_VERSION=3.12` del Dockerfile.

## §5. Metricas al cierre

- Tests (Windows): `1120 → 1126` (+6 regresion Docker). 58 skipped (win32).
- Tests (**WSL2 nuevo**): **1156 passed / 28 skipped** — 30 tests mas que Windows
  (shell/systemd/backup, ahora corriendo en Linux nativo).
- CI del PR: **green** (full matrix + E2E + test-postgres + CodeQL + pip-audit).
- Migraciones: `+0`. Deps: `unchanged`. Cambio de runtime prod: `ninguno`.
- ASVS L2: `unchanged` (151 PASS).
- **Entornos de dev activos**: Windows nativo (loop diario) + WSL2 Ubuntu 24.04
  (paridad Linux); Docker fuera del loop.

## §6. Hallazgos / findings

- **[OPS/child] La hija Starlink todavia tiene los 5 bugs Docker** (solo aplico
  `.gitattributes`). Necesita heredar v0.5.7. Sin remote `template` configurado →
  el canal de updates (DECISIONS #7) no esta cableado en la hija.
- **[CLOSED] `*.gif` faltaba en el `.gitattributes` del template** — la hija lo
  tenia; adoptado (`05f0c51`).

## §7. Roadmap actualizado

| # | Item | Effort | Status |
|---|---|---|---|
| — | App hija: aplicar fixes v0.5.7 + configurar remote `template` | S | open (prompt entregado) |
| — | Modelo C (`ameli-core` paquete + Dependabot) | L | open |
| — | `PRIVACY.md` (al ir productivo con usuarios reales) | S | open |
| — | jsdom DOM-wiring / visual regression | M | open |
| — | Django LTS 6.2 (~dic-2026) | M | open |

## §8. Continuidad — para el proximo agente

**8a. Estado del servidor `ha-report2`.** En **v0.5.6-django**, `active`. v0.5.7
**no requiere redeploy** (cero runtime prod); `/health` sube a v0.5.7 en el
proximo `git pull` sin urgencia.

**8a-bis. Entorno WSL2 en el workstation.** Ubuntu 24.04 LTS operativo,
`/home/hardg/ameli-app-template` (branch `dev`, HEAD `88700d3`, venv desde
ambos locks, uvloop presente, suite 1156/28). Entrar con `wsl -d Ubuntu-24.04`
(o solo `wsl`, es default); sync por `git pull` normal.

**8b. Orden recomendado.**
1. Si retomas la hija: usar el prompt entregado (revisar diff → copiar los 3
   archivos del template o cherry-pick `7093da5`+`05f0c51` via remote `template`;
   actualizar `TEMPLATE_LINEAGE` a v0.5.7; validar con Docker local; suite+ruff).
2. Si sigues en el template: backlog §7 (Model C / PRIVACY.md son los de mas valor).

**8c. Comandos utiles.**
```bash
# sync inicio de dia (S-09)
git fetch origin --prune && git merge --ff-only origin/dev
# verificar despliegue en server (derivar datos, no adivinar — OPERATIONS ground-truth)
cd /opt/ameli-app-template-dev && APP_ENV=dev bash scripts/validate_installation.sh
# validar imagen Docker (donde haya Docker)
docker compose build && docker compose up -d && curl -s localhost:18080/health
docker compose run --rm api pytest -q
```

## §9. Archivos clave de la sesion

- `Dockerfile`, `docker-compose.yml`, `.gitattributes` — los 5 fixes.
- `tests/test_docker_stack.py` — +6 tests de regresion (guard anti-drift).
- `CHANGELOG.md` / `AGENTS.md` — entrada + estado de v0.5.7.
