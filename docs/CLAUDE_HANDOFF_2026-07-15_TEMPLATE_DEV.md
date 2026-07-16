## AMELI App Template handoff (sesion Claude, 2026-07-15)

Fecha: `2026-07-15`
Agente: `claude-opus-4-8`
Rama de trabajo: `dev` (version `v0.5.5-django`)
Rama estable: `main` (en `v0.5.5-django`)
Sesion previa: [`CLAUDE_HANDOFF_2026-07-14_TEMPLATE_DEV.md`](CLAUDE_HANDOFF_2026-07-14_TEMPLATE_DEV.md)

## §1. Snapshot al inicio

- `dev` == `origin/dev` (ahead 0, behind 0), **arbol limpio**. VERSION
  `v0.5.5-django`; `main` tambien en `v0.5.5-django` (`b7d0172`).
- **3 commits en `dev` sin promover**, todos **docs/CLI/CI** (sin cambio de
  runtime de la app): `cd7c0f4` bump de actions + Dependabot→dev, `2bfe6ad`
  fixes del dry-run (encoding de `template-check`, hint de rate-limit,
  correccion de `BUILDING_NEW_APP §2`), `766d167` handoff.
- **CI verde** en el ultimo commit con codigo (`2bfe6ad`). **Sin PRs abiertos.**
- **Server** (`ha-report2`): corriendo `v0.5.5-django`. Los fixes del dry-run
  (`2bfe6ad`, docs/CLI) aun no sincronizados — sin efecto runtime.
- **Toggles del repo aun DISABLED** (verificado via API): `secret_scanning`,
  `push_protection`, `dependabot_security_updates`. Accion del operador.
- Sin apps hijas; camino de fork validado y corregido la sesion pasada.

## §2. Objetivo de la sesion

**Promover `v0.5.6` de mantenimiento** — llevar a `main`/release los 3 commits
docs/CLI/CI que quedaron sobre el tag v0.5.5, para que las correcciones del
camino de fork esten en un release (una app hija forkea desde `main`/un tag).

## §3. Trabajo realizado

### 3.1. Validacion en server (regla "bump solo tras validar")

v0.5.6 **no tiene cambio de runtime de la app** (codigo del servicio identico a
v0.5.5); lo unico runtime-adjacent es el CLI `template-check`. Validado en
`ha-report2`: `git pull` a `766d167`, y `template-check` corrio **limpio en la
caja imprimiendo el 🔴 de las notas de v0.5.5 sin crashear** — o sea, valida en
vivo el fix de encoding (`2bfe6ad`). `/health` `v0.5.5-django` OPERATIVO,
servicio intacto (sin restart, codigo identico).

### 3.2. Bump v0.5.6 + promocion (`b98a868`, PR #9)

Ritual de bump (VERSION+pyproject+CHANGELOG+AGENTS). CHANGELOG framea v0.5.6
como **mantenimiento sin cambio de runtime**: correccion de `BUILDING_NEW_APP
§2` (keep-names = default; el "must rename" dejaba ~740 refs rotas), fixes del
CLI `template-check` (encoding UTF-8 + mensaje de rate-limit), y bumps de
actions + Dependabot→dev. Suite **1120 passed**, ruff limpio. PR #9 **CI 8/8
verde**, merge commit (`0657ef7`) + tag/release **v0.5.6-django**. `main` =
`v0.5.6-django`, 0 commits de contenido sin promover.

## §4. Pendiente / proximos pasos

- **Sync del server a v0.5.6: HECHO.** `git pull` + restart (`__version__` es
  cacheado al import), `/health` → `v0.5.6-django`, servicio `active`.
- **Toggles del repo: ACTIVADOS** (verificado via API). `secret_scanning`,
  `secret_scanning_push_protection`, Dependabot **alerts** y Private
  Vulnerability Reporting = **enabled**. Se dejaron OFF a proposito: Dependabot
  *security updates* / *grouped* (chocan con el lockfile hash-pinneado). El set
  de seguridad de supply-chain quedo completo.
- **App hija #1 (Starlink dashboard): en otra conversacion.** Recon de la
  Starlink Enterprise API hecho (OAuth2 client-credentials V2, base
  `https://starlink.com/api/public/v2/`, `POST /data-usage/query` = consumo por
  ciclo/mensual; diario via self-accumulation del capture worker con manejo de
  reset de ciclo). Prompt de arranque consolidado entregado.
- **Backlog** (bajo valor): jsdom DOM-wiring, visual regression, Model C
  (`ameli-core` paquete), Django LTS 6.2 (~dic-2026).
- **Historial git**: ground-truth viejo; decision previa = aceptar (no purgar).
- Sin apps hijas todavia; camino de fork probado y corregido (release v0.5.6).

## §5. Docker/compose dry-run — 5 bugs VERIFICADOS, pendientes de fix

El path Docker/compose de dev nunca se habia ejercitado. Un dry-run real (app
hija en Windows + Docker 29.6.1 / Compose v5.3.0) encontro 5 bugs; **los
verifique uno por uno a la altura de `d4fd2c2`** (todos confirmados). **NO
estan arreglados todavia** — arrancar la proxima sesion por aca. La app hija ya
tiene workarounds locales (`docker-compose.override.yml` + `.gitattributes`),
asi que NO esta bloqueada; el fix va en el TEMPLATE para que la flota lo herede
(la hija lo cherry-pickea via el remote `template`). Los fixes tocan **solo el
path Docker/dev + line-endings** — `src/` y el path systemd/prod no se afectan.

**#1 — `docker-compose.yml`: env vars con nombres viejos (INERTES).**
El codigo lee `AMELI_APP_DJANGO_SECRET_KEY` (config.py:249), `AMELI_APP_DJANGO_DEBUG`
(config.py:250), `AMELI_APP_DJANGO_ALLOWED_HOSTS` (base.py:45); el compose setea
`AMELI_APP_SECRET_KEY`/`AMELI_APP_DEBUG`/`AMELI_APP_ALLOWED_HOSTS` (en `api` y
`notifier`) → inertes → cae al SECRET_KEY default inseguro + DEBUG=False.
**Fix:** renombrar a los `AMELI_APP_DJANGO_*` + agregar `APP_ENV=dev` y una
`AMELI_APP_MFA_ENCRYPTION_KEY` (Fernet dev) en ambos servicios. (Matiz:
`app.yaml.example` setea `environment: dev`, por eso el fail-closed de APP_ENV no
dispara y "arranca"; MFA key solo requerida fuera de dev — ambas son defensivas.)

**#2 — `Dockerfile`: editable install con path mismatch → `ModuleNotFoundError: ameli_web`.**
builder `WORKDIR /build` + `pip install -e .` → el `.pth` apunta a `/build/src`;
runtime `WORKDIR /app`, copia a `/app/src`, sin `PYTHONPATH`. `/build/src` no
existe en runtime. **Fix:** `ENV PYTHONPATH=/app/src` en el stage runtime (el
`.pth` viejo queda inerte, inofensivo).

**#3 — `Dockerfile`: instala rangos (no el lock) + sin dev-deps.**
Dockerfile:38 `pip install -r requirements.txt` (requirements.txt tiene
`Django>=5.2,<7` → puede traer Django 6; el lock pinnea `django==5.2.16`).
Contradice la postura hash-pinned (ASVS V14.2.3). Y `requirements-dev.txt` se
copia pero NO se instala → sin pytest en la imagen (el comentario del compose
`docker compose run --rm api pytest` no funciona). **Fix:** builder
`pip install --require-hashes -r requirements.lock` + `pip install -e . --no-deps`
(paridad prod). **DECISION ABIERTA:** para pytest, agregar un target `dev` que
instale `requirements-dev.lock` y apuntar `build.target: dev` del servicio api
(imagen runtime/prod queda lean) — vs solo corregir el comentario. Preguntar al
operador.

**#4 — `Dockerfile`: no copia `VERSION` → `/health` reporta `v0.0.0-dev`.**
version.py:5 resuelve `parents[2]/VERSION` = `/app/VERSION`; el Dockerfile no lo
copia → fallback `"v0.0.0-dev"`. **Fix:** `COPY VERSION ./VERSION` en runtime (y dev).

**#5 — falta `.gitattributes` → CRLF rompe los `.sh` en Linux al clonar en Windows.**
No existe `.gitattributes`; los blobs `.sh` estan en LF en el repo (verificado)
pero con `autocrlf=true` (default Windows) se checkoutean CRLF → bash falla al
sourcear `_common.sh` en Linux/containers. Rompe ~18 tests de shell/systemd/backup
que en win32 se skipean (invisible en CI Linux y en dev Windows). **Fix:** agregar
`.gitattributes` (`* text=auto eol=lf`; `*.ps1/*.bat/*.cmd text eol=crlf`;
binarios `*.png/*.jpg/*.ico/*.woff2/*.pdf/*.sqlite3 binary`), luego
`git add --renormalize .` y confirmar que el diff sea sano (deberia ser no-op de
contenido: los blobs ya estan en LF).

**Validacion propuesta:** suite completa + ruff (regla), y si hay Docker a mano,
buildear la imagen + `docker compose up` para confirmar #1-#4 end-to-end (import
de `ameli_web`, `/health` = version correcta, `docker compose config` con los
nombres corregidos). #5 se valida corriendo los tests de shell en un contenedor
Linux con el arbol montado (en win32 se skipean). Despues, evaluar si amerita un
**v0.5.7** para que la hija lo cherry-pickee limpio.
