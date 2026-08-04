## AMELI App Template handoff (sesion Claude, 2026-07-23)

Fecha: `2026-07-23`
Agente: `claude-opus-4-8`
Rama de trabajo: `dev` (HEAD `82ed04e` al cierre)
Rama estable: `main` (en `v0.5.9-django`; `v0.5.10-django` tagueado en `dev`)
Sesion previa: [`CLAUDE_HANDOFF_2026-07-22_TEMPLATE_DEV.md`](CLAUDE_HANDOFF_2026-07-22_TEMPLATE_DEV.md)

## §1. Objetivo

1. Acotar la doc del template a **solo template** (sacar datos de otras
   apps del servidor).
2. Verificar la exposicion a internet de las instancias del template
   (`dev03` = dev del template, `dev04` = hija Starlink): puertos, uso LAN,
   integridad.
3. Verificar que una instalacion nueva cumpla el despliegue ideal
   (instalacion, configuracion, puesta en marcha).

## §2. Doc acotada a template (`4eb5c45`)

- Eliminado `docs/AUDIT_WEBFLEET_2026-07-21.md` (trata de una app hija).
  Copia con nota de reubicacion en scratchpad → mover al repo de WebFleet.
- `SERVER_HARDENING.md`: reformulada la mencion a OMEGA sin nombrar la app.
- Handoff 2026-07-22 dejado como **registro historico** con nota al inicio;
  el estado de red multi-app se consolido en
  `NETWORK_OPS_ha-report2_2026-07-22.md` (scratchpad) → mover a infra.
- `TLS_WITH_CADDY.md` y `OPERATIONS.md` quedan (genericos / servicios
  propios del template).

## §3. Verificacion de red — `dev03` / `dev04`

Criterio N1–N9 (ver detalle en el cuerpo de la sesion). Resultado:
**aprobado**, con un hallazgo que se convirtio en B13.

- N1 backends en loopback ✅ (`127.0.0.1:18080` / `:18090`)
- N2 solo `10.100.100.16:443` expone ✅  · N3 sin reglas de puerto alto ✅
- N4 TLS valido ✅ · N5 headers (HSTS×1, nosniff, DENY) ✅
- N6/N7 cookie `__Host-` Secure (prueba de `is_secure()` True) ✅
- N9 desde la LAN: backend directo **timeout**, 443 **200** ✅
- N8 `/health`: **divergian** — `dev03` restringido, `dev04` abierto → B13.

## §4. B13 — `/health` y `/metrics` abiertos en instalacion prod (`82ed04e`)

`settings/integrations.py` deja `HEALTH_METRICS_ALLOWLIST` vacio =
**abierto** ("public for probes"). Por un proxy eso filtra version, uptime,
disco y el scrape completo de Prometheus a cualquiera que alcance el puerto
publico (version conocida = shortlist de CVEs). Confirmado en `dev04`:
`/health` devolvia `version: v0.1.0-starlink`, `/metrics` HTTP 200, sin auth.

Es **fail-OPEN**, la clase opuesta a `ALLOWED_HOSTS`/`TRUSTED_PROXIES`
(fail-closed, que el instalador ya siembra). El instalador no sembraba
este, asi que **toda instalacion prod nueva quedaba expuesta**.

Fix (postura conservadora elegida por el operador):
- `initialize_runtime_env` siembra `AMELI_APP_HEALTH_METRICS_ALLOWLIST=
  127.0.0.1,::1` en prod, **solo sobre un env file recien creado**. El smoke
  y `validate_installation` pegan a `127.0.0.1:<port>/health` directo
  (permitido); lo que llega por el proxy queda cerrado. Dev queda abierto.
- Por ser fail-open, **no** reescribe una instancia ya provisionada (podria
  servir `/metrics` a un scraper externo a proposito): `warn_insecure_prod_env`
  lo reporta y el operador decide. El default del codigo **no** cambia.
- 3 tests nuevos en `test_install_env_seeding.py`. Doc en `OPERATIONS.md`.

**Deploy:** `dev04` cerrado en el server (`AMELI_APP_HEALTH_METRICS_ALLOWLIST=
127.0.0.1,::1,10.100.100.16`; el `.16` deja pasar chequeos por nombre desde
el propio host). Verificado: `/health` y `/metrics` por Caddy → **403**,
loopback → **200**.

## §5. Aceptacion del instalador — instalacion nueva desde cero

Instancia descartable `tmpl-smoke-prod` en `ha-report2`, clone de `dev`
(`82ed04e`), puertos `18190/18191`. **Los 13 items verdes, sin un solo
toque manual:**

| | |
|---|---|
| I1 3 claves cripto | ✅ |
| I2 ALLOWED_HOSTS + TRUSTED_PROXIES | ✅ |
| I3 app.yaml: prod, paths absolutos en `/var/lib`, email `file` | ✅ |
| I4 DEBUG=false, cookie Secure, sin SESSION_COOKIE_NAME | ✅ |
| I5 puertos explicitos respetados (18190/18191) | ✅ |
| I6 **B13** allowlist `127.0.0.1,::1` | ✅ |
| I7 checkout limpio tras instalar (B12) | ✅ |
| I8 migrate + check, `/health` db+audit true sobre Postgres | ✅ |
| I9 units enabled + running | ✅ |
| I10 `validate_installation` `OK=26 FAIL=0` + `HEALTH_ENDPOINT` (B11) | ✅ |
| I11 B13 end-to-end: loopback 200, `X-Forwarded-For` ajeno 403 | ✅ |
| I12 `configure` crea superadmin (`status: created`) | ✅ |
| I13 idempotencia: SECRET_KEY + allowlist preservadas, checkout limpio | ✅ |

Instancia de prueba **eliminada** al cierre.

## §5b. Revision + endurecimiento del ciclo day-2 (`e745c2a`)

Revision de los scripts de mantenimiento contra el estandar del
instalador. `backup.sh`, `restore.sh`, `maintenance` y
`purge-inactive-users` ya estaban solidos (pg_dump custom, manifest
sha256, GPG, retencion acotada, verify/restore con guard, retention sweep,
dry-run). Dos huecos, cerrados:

- **M1** — `update.sh` corria `backup.sh || true` antes de `migrate`. El
  backup previo es la unica via de recuperacion de una migracion
  irreversible; el `|| true` tragaba un pg_dump fallido o un disco lleno.
  Ahora **detiene** el update, con opt-out `AMELI_APP_UPDATE_SKIP_BACKUP=1`.
- **M4** — `update.sh` **verifica** el backup recien hecho
  (`restore.sh verify`) antes de tocar la DB. GPG sin clave local: WARN,
  no halt.
- **M3** — `uninstall.sh` suma `--purge --yes`: toma un backup **final**
  (a `/var/backups`, sobrevive a la purga), borra dirs + usuario/grupo via
  el nuevo `purge_instance()` en `_common.sh`, e **imprime** los
  `dropdb`/`dropuser` (parseados de `DATABASE_URL`) en vez de tocar una DB
  que el instalador no crea.

Tests: `test_lifecycle_scripts.py` (6 estaticos + 1 de comportamiento de
purga). Doc en `OPERATIONS.md`.

**Aceptacion en servidor (`ha-report2`, `tmpl-smoke`):**

| | |
|---|---|
| `update.sh` happy path: backup→verify→migrate→validate | ✅ `RESUMEN OK=26 FAIL=0` |
| M1: backup roto → update se detiene (exit 1, 0 "Actualizacion lista") | ✅ |
| opt-out `AMELI_APP_UPDATE_SKIP_BACKUP=1` salta y procede | ✅ |
| `--purge` sin `--yes` → rechaza, instancia intacta | ✅ |
| `--purge --yes` → backup final sobrevive, 0 dirs, usuario ausente, DB commands impresos | ✅ |

Instancia de prueba eliminada al cierre (con el propio `--purge`).

## §5c. Prompt de entrega a Starlink + normalizacion de puertos (`57e1bb5`)

**Prompt de entrega reescrito** (scratchpad
`to-move/STARLINK_DELIVERY_PROMPT_v0.5.10.md`). El draft del 2026-07-21
§8c quedo obsoleto: asumia "solo overhaul de onboarding, sin validacion de
servidor". El nuevo refleja el alcance real (B1-B12 + B13 + day-2), el
modelo git (fork + merge/cherry-pick, DECISIONS #7), las DOS capas (deploy
de `dev04` ya al dia vs codigo del fork pendiente), el wrinkle dev/main, y
la tabla de WARN literales que el reinstall puede tirar.

**Arquitectura aclarada + convencion de puertos normalizada.** Al revisar
puertos con el operador se confirmo que el template es un **monolito
Django**: un proceso ASGI (`ameli_web.asgi`) sirve dashboard HTML **y** API
JSON; **no hay frontend separado** (ese recuerdo era de WebFleet, app hija
con node dist + api python). Cambios (solo docs/comentarios, sin runtime):

- `OPERATIONS.md` nueva seccion "Architecture and ports": diagrama del
  flujo real (internet → Caddy → ASGI → PG; workers fuera del path),
  **el `api_port` es el unico que bindea y el que ve el proxy**, convencion
  **prod 80XX / dev 18XX** (overridable), y que **`APP_ENV` -no el puerto-
  decide el comportamiento prod** (un prod en 18XXX es normal en host
  compartido — es el caso de Starlink).
- **`web_port` / `web.service` NO es config muerta**: es un **seam
  reservado** (ya documentado en `web.py`) — el gancho para que una hija
  swapee la implementacion, y para la **evolucion futura a frontend
  separado**. Documentado en `.env.example`, `_common.sh` y una nota de
  roadmap. **No se removio** (habria sacado justo ese gancho).
- Naming api/web aclarado en `api.py` / `web.py`.

**Decision registrada:** el monolito es la forma intencional **por ahora**;
el split frontend/API queda como **evolucion de tech futura**.

Relevante para Starlink: corre `api-worker-maintenance` → **1 solo puerto
activo** (api 18090, loopback); `web_port=8081` reservado sin bindear.
Config mixta (api en rango dev, `APP_ENV=prod`) — correcta, override por la
colision del 8080 en el host.

## §6. Estado y pendientes

- `dev` en `57e1bb5`; `v0.5.10-django` tagueado en `dev`. **B13, el
  endurecimiento del ciclo day-2 (M1/M4/M3) y la normalizacion de puertos
  estan sin release**: entran en el proximo corte (o re-tag) cuando vuelva
  el CI.
- Red del template: `dev03`/`dev04` cumplen el criterio N1–N9 + B13.
- Ciclo day-2 completo y validado en servidor: install / update(+backup
  gate) / uninstall(+purge) / backup / restore / maintenance /
  purge-users / verify-audit / rotate-audit-key.
- Arquitectura + convencion de puertos documentada; monolito por ahora,
  frontend split como evolucion futura (§5c).
- Pendientes del template: **entrega de `v0.5.10`+B13+day-2 a Starlink**
  (prompt listo en scratchpad; sumar la seccion de convencion de puertos),
  PR #13, y al volver el CI (2026-08-01) promover `main` + borrar el bloque
  provisorio de `CONTRIBUTING.md`.
- Red multi-app (dev01 fase 2, WebFleet, firewall) y sus docs: **fuera del
  template**, en `NETWORK_OPS_ha-report2_2026-07-22.md` (scratchpad → infra).
