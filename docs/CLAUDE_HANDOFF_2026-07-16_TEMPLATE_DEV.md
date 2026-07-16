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

## §4. Decisiones tomadas

- **Docker #3 = target `dev` separado** (no solo corregir el comentario): el
  compose ya documenta `docker compose run api pytest`, hacerlo funcionar de
  verdad vale mas que el costo (Dockerfile un poco mas grande); multi-stage
  mantiene la imagen prod lean. (Operador delego: "segun tu recomendacion".)
- **Adoptar `*.gif binary`** del `.gitattributes` de la hija (el pipeline de
  avatares acepta `image/gif`).
- **v0.5.7 no requiere validacion en server ni redeploy**: cero cambio de runtime
  de prod (solo path Docker/dev). SBOM omitido (deps sin cambio vs v0.5.6).

## §5. Metricas al cierre

- Tests: `1120 → 1126` (+6 regresion Docker). 58 skipped (win32).
- CI del PR: **green** (full matrix + E2E + test-postgres + CodeQL + pip-audit).
- Migraciones: `+0`. Deps: `unchanged`. Cambio de runtime prod: `ninguno`.
- ASVS L2: `unchanged` (151 PASS).

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
