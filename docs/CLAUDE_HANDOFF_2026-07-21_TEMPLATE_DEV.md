## AMELI App Template handoff (sesion Claude, 2026-07-21)

Fecha: `2026-07-21`
Agente: `claude-opus-4-7`
Rama de trabajo: `dev` (version `v0.5.9-django`, HEAD `dfac623` al abrir)
Rama estable: `main` (en `v0.5.9-django`, `98f32a5`; al dia con `dev`
menos 2 commits docs-only pendientes de promocion)
Sesion previa: [`CLAUDE_HANDOFF_2026-07-17_TEMPLATE_DEV.md`](CLAUDE_HANDOFF_2026-07-17_TEMPLATE_DEV.md)

> **Sesion en curso** — este handoff se completa durante el dia.

## §1. Snapshot al inicio

- `dev` == `origin/dev` (0/0), **arbol limpio**. `main` promovido a
  **v0.5.9-django** el 2026-07-17 (`98f32a5`); `dev` en `dfac623`, 2
  commits docs-only adelante (`932db99` fix duplicado CHANGELOG + `dfac623`
  cierre honesto §3.3 del handoff previo).
- **Entorno canonico operativo = WSL2 Ubuntu 24.04** (per DECISIONS #9) en
  `/home/hardg/ameli-app-template`, suite **1156/28**. Clone Windows en
  `C:\Users\hardg\AMELI APPS\AMELI_APP_TEMPLATE` esta en sync pero
  **tratado como archivado** — no editar ahi.
- **PR #13 abierto** (Dependabot, 2026-07-20): `chore(ci): Bump actions/
  setup-python from 6 to 7`. `MERGEABLE`/`CLEAN`, esperando review.
- **Server** (`ha-report2`): en **v0.5.6-django**, active. v0.5.7/8/9 son
  docs/Docker-path y **no requieren redeploy**; `/health` sube en el
  proximo `git pull` sin urgencia.
- **CI verde** en el ultimo release (`98f32a5`).

## §2. Objetivo de la sesion

Auditoria de arquitectura para una integracion **outbound** con la API de
**WebFleet**. Flujo: worker/servicio del app llama la REST de WebFleet
(posiciones, drivers, rutas, etc.). Ubicacion (template vs hija) por
decidir; el checklist tecnico es el mismo. **CORS descartado**: la
integracion es server-to-server, cero superficie browser.

## §3. Trabajo realizado

### 3.1. `docs/AUDIT_WEBFLEET_2026-07-21.md` (nuevo)

Auditoria de arquitectura para una integracion outbound Django -> WebFleet
REST API. **Cero cambio de runtime**; el documento inventaria QUE verificar
por superficie (credenciales, wire, rate limits, datos at rest, failure
modes, audit trail, PRIVACY addendum) y QUE piezas del template se
**reusan** en lugar de reinventar. Referencias `file:line` verificadas
contra codigo antes de commitear.

**Hallazgos clave para el que implemente:**
- **CORS descartado** (server-to-server, browser-only). Se documenta
  explicitamente para que el proximo lector no repita la pregunta.
- **`accounts/circuit_breaker.py:40`** ya expone `CircuitBreaker` como
  clase generica; hoy tiene `get_av_breaker` + `get_hibp_breaker` +
  `get_smtp_breaker`. Agregar `get_webfleet_breaker` es ~10 LOC.
- `_handle_template_check` en `cli.py` es la referencia canonica de
  outbound HTTP con stdlib urllib + timeout + sin sorpresas TLS.
- `ThrottleCounter` (`models.py:211`) se reusa para **client-side rate
  limit** (scope=`outbound_webfleet`), no solo para gates de login.
- Retention windows: extender `services/retention.py:29-33` con
  `webfleet_positions_max_age_days` etc. siguiendo el patron existente.
- PRIVACY: la app hija **extiende** su propio PRIVACY.md (no el del
  template) para agregar el processor WebFleet, retention de posiciones,
  legal basis, cross-border a TomTom.

**Ubicacion recomendada:** app hija (Starlink u otra), no el template.
Justificacion: WebFleet es un vertical (fleet mgmt); template lean per
DECISIONS #7. Regla del tres: si una segunda app AMELI tambien lo
necesita, extraer a un `ameli-fleet` package.

**Preguntas abiertas** (documento §6, el implementer las contesta):
1. Auth scheme (API key vs OAuth2)? Determina storage.
2. Volumen (vehiculos, posiciones/hora)? Determina throttle + cache.
3. Persistencia (snapshot vs historico)? El historico dispara PRIVACY.
4. Ubicacion (que hija concreta)?

### 3.2. Overhaul del onboarding — DECISIONS #10 + installer + configurator

**Trigger**: el operador reporto que instalar una hija en el server con
`APP_ENV=prod` requiere seis env vars manuales (SECRET_KEY, DEBUG,
ALLOWED_HOSTS, TRUSTED_PROXIES, AUDIT_HMAC_KEY, MFA_ENCRYPTION_KEY) mas
setup manual de SMTP / TLS / superadmin, y propuso **eliminar `APP_ENV`**
para dejar "un producto estandar".

**Pushback** (documentado en §4): eliminar `APP_ENV` **reversa M1** (v0.5.1,
hallazgo HIGH de auditoria independiente que cerro "silent fallback to dev
disables every guard") y colapsa V2.8 / V7.3.2 / V13.4 / V14.4.5 del ASVS
L2. Los seis guards son armadura defensiva, no naming quirks. El diagnostico
real es DX / onboarding, no arquitectura.

**Plan completo ejecutado** (7 piezas):

1. **`DECISIONS.md` #10** (nuevo) — mantener `APP_ENV`; cerrar el gap con
   installer + configurator. Documenta rechazos explicitos (drop
   `APP_ENV` en modo strict rompe WSL; drop en modo permissive es la
   regresion de M1; renombrar es churn cosmetico).

2. **`scripts/install.sh` + `_common.sh`** — auto-genera las 3 keys
   crypto **idempotente** en `initialize_runtime_env` via nuevo helper
   `gen_env_if_missing`. `SECRET_KEY` = `secrets.token_urlsafe(60)`,
   `AUDIT_HMAC_KEY` = `secrets.token_urlsafe(48)`,
   `MFA_ENCRYPTION_KEY` = `base64.urlsafe_b64encode(os.urandom(32))`
   (shape identica a `Fernet.generate_key()`, verificado con round-trip
   contra cryptography). `.env.example` limpiado del placeholder
   `SECRET_KEY=change-this-django-secret` (dejaba pasar el guard).

3. **`deploy/caddy/Caddyfile.example`** (nuevo) — snippet TLS-auto
   reverse-proxy listo para copiar, con placeholder `__HOSTNAME__` y
   los `X-Forwarded-*` headers necesarios. `install.sh` imprime su
   path con instrucciones al terminar.

4. **`ameli-app configure`** — nuevo subcomando CLI (wizard de ~200
   LOC). 4 secciones (`hosts`, `proxies`, `smtp`, `admin`), interactivo
   si stdin es TTY, no-interactivo via `AMELI_APP_CONFIGURE_*` env
   vars. `--check` (dry-run), `--section` (solo una), `--yes` (CI).
   Salida `2` con lista exacta si faltan requeridos → nunca deja
   deploy medio configurado. Passwords via `getpass` (sin echo).
   Idempotente: re-run con mismos valores no toca el archivo.

5. **`install.sh` smoke post-install** — corre
   `validate_installation.sh` + `curl /health` con retry (15s, primer
   boot puede tomar). Falla loud con `journalctl` pointer; sale
   non-zero para que un install roto no pase por bueno.

6. **9 tests nuevos** (`tests/test_cli_configure.py`) — pure helpers
   (read/write env file, idempotencia, autodetect hosts) + handler
   (check no toca archivo, missing-vars → exit 2, SMTP opcional,
   section filter, sin env file → exit 2 con mensaje). Suite completa
   pasa **1165 / 28** (+9 nuevos vs 1156 baseline). Ruff limpio.

7. **`docs/FIRST_INSTALL_DJANGO.md`** — nueva seccion "Quickstart —
   Debian con `install.sh` (RECOMENDADO)" al frente con el flujo de
   **3 comandos** (`install.sh` → `configure` → Caddy). La antigua
   "Primera instalacion Debian" manual queda como referencia
   troubleshooting con nota al principio.

**Impacto DX** — el path prod baja de "20 pasos manuales + descubrir
cada crash uno por uno" a: `apt install` → `install.sh` → `configure`.
Los guards de seguridad quedan intactos.

**Referencias file:line verificadas** contra codigo real (el helper
existe donde lo cito, los env vars son los que el codigo realmente lee,
el CircuitBreaker es generico como afirmo, etc.).

## §4. Decisiones tomadas

- **CORS descartado** para el caso WebFleet (server-to-server; browser-only).
  Documentado explicito en el audit para que no vuelva a preguntarse.
- **WebFleet vive en la hija, no en el template** (per DECISIONS #7). Rule
  of Three: extraer a `ameli-fleet` package solo si una segunda AMELI app
  tambien lo integra.
- **`APP_ENV` se mantiene**, contra la propuesta del operador de eliminarlo.
  Reversarlo revierte M1 (v0.5.1, HIGH), colapsa V2.8/V7.3.2/V13.4/V14.4.5
  ASVS L2, y contradice PRIVACY.md §4. La pain real era DX, no arquitectura.
  Documentado como DECISIONS **#10**.
- **`install.sh` genera las 3 keys crypto idempotente**, en vez de dejarlas
  como responsabilidad manual del operador. Elimina el 60% del dolor de
  first-install prod.
- **`ameli-app configure` wizard** en vez de scripts sueltos o docs. Un
  solo comando para las 4 decisiones que quedan al operador (hosts,
  proxies, SMTP, superadmin).
- **`docker compose` NO se remueve** del template — solo del loop de dev
  local del operador (per DECISIONS #9). El wizard cubre el flujo "correr
  directo bajo WSL2" que el operador eligio.
- **NO se corta v0.5.10 hoy** — el operador decidio probar la mejora
  primero manana; tag y entrega a la hija despues de la aprobacion.

## §5. Metricas al cierre

- Nuevos docs: **+2** (`docs/AUDIT_WEBFLEET_2026-07-21.md` ~200 LOC;
  `docs/DECISIONS.md` #10).
- Nuevo codigo: **+1** subcomando CLI (`ameli-app configure` ~200 LOC),
  **+1** helper de shell (`gen_env_if_missing`), **+1** Caddyfile snippet.
- Docs re-estructurada: `FIRST_INSTALL_DJANGO.md` gana Quickstart al frente.
- Tests: `1156 → 1165` (+9). 28 skipped (win32-only).
- Ruff: `0 errors`. Bash syntax: `install.sh` + `_common.sh` OK.
- Migraciones: `+0`. Deps: `unchanged`. Cambio runtime prod: `ninguno`.
- ASVS L2: `unchanged` (151 PASS) — los 6 guards de prod intactos.
- `dev` cierra en `3145c65`, **4 commits adelante** de `main`
  (v0.5.9-django).

## §6. Hallazgos / findings

- **[OPS/child]** La hija Starlink instalada con `APP_ENV=prod` sufrio la
  cascada de crashes que motivo esta sesion. Cuando se apruebe manana,
  puede consumir la mejora via `git pull` template + reinstall (idempotente).
- **[OPS]** **PR #13** (Dependabot: setup-python v6→v7) sigue abierto,
  `MERGEABLE`/`CLEAN`. Bump trivial de CI action; revisar/mergear cuando
  cuadre. Sin dependencia del trabajo de hoy.
- **[LOW/docs]** `FIRST_INSTALL_DJANGO.md` crecio a 439 lineas (era 343).
  Aceptable — la nueva Quickstart al frente evita que el operator lea el
  resto. Si en el futuro sobra la seccion manual, se puede podar.
- **[CLOSED]** Bug del `.env.example` que shipeaba
  `SECRET_KEY=change-this-django-secret` como placeholder — se colaba por
  el guard de `base.py` (que solo detectaba el `_INSECURE_DEFAULT_SECRET`
  distinto). Fixed inline con el trabajo de instalador.

## §7. Roadmap actualizado

| # | Item | Effort | Status |
|---|---|---|---|
| — | **Manana: probar `install.sh` + `configure` en server** (nueva hija limpia o snapshot) | S | open — PRIORIDAD |
| — | Una vez aprobado: cortar **v0.5.10-django** (docs + DX; sin runtime change) | S | open — bloquea entrega a hija |
| — | Entregar cambios a la hija Starlink (git pull template + cherry-pick v0.5.10 o reinstall) | S | blocked by testing + tag |
| — | WebFleet: implementar `services/webfleet.py` en la hija (per audit) | M | open (cuando arranque el desarrollo real) |
| — | PR #13 Dependabot review | XS | open |
| — | `/profile/export/` — data portability (gap documentado en PRIVACY) | S | open |
| — | `ameli-app configure`: agregar test-send SMTP | S | open (nice-to-have) |
| — | jsdom DOM-wiring / visual regression | M | open |
| — | Modelo C (`ameli-core` package) | L | deferred (DECISIONS #7) |
| — | Django LTS 6.2 (~dic-2026) | M | premature |

## §8. Continuidad — para el proximo agente (o el operador manana)

**8a. Estado del server `ha-report2`.** En **v0.5.6-django**, `active`.
NO se ha probado nada de v0.5.9 ni del trabajo de hoy en el server aun.
Los releases docs-only no requieren redeploy per RELEASE.md, pero
manana el objetivo es exactamente **probar el trabajo de hoy en un
server** (idealmente uno de dev / snapshot, no `ha-report2` prod).

**8a-bis. Entorno WSL2.** `/home/hardg/ameli-app-template` en `3145c65`,
todo commiteado. Clone Windows en sync.

**8b. Plan de pruebas para manana** (lo que el operador dijo que iba a
hacer):

1. **Snapshot del test target**. Si va a un server dedicado de prueba,
   asegurarse que se puede resetear. Si es una VM efimera, mejor.
2. **Test del install prod desde cero**:
   ```bash
   sudo apt install -y postgresql caddy git
   sudo git clone https://github.com/HarDGameinc/AMELI-App-Template.git \
       /opt/ameli-app-template-prod
   cd /opt/ameli-app-template-prod
   sudo -u postgres createuser --pwprompt ameli_app_prod
   sudo -u postgres createdb -O ameli_app_prod ameli_app_prod
   echo "DATABASE_URL=postgresql+psycopg://ameli_app_prod:PASS@127.0.0.1:5432/ameli_app_prod" \
       | sudo tee -a /etc/ameli-app-template-prod/app.env
   sudo APP_ENV=prod scripts/install.sh
   ```
   **Esperado**: install completa sin errores; las 3 keys se auto-generan;
   `/health` responde OK en el smoke.
3. **Test del wizard interactivo**:
   ```bash
   sudo /opt/ameli-app-template-prod/.venv/bin/ameli-app \
       --env-file /etc/ameli-app-template-prod/app.env configure
   ```
   Debe promptar por hosts, proxies, SMTP (opcional), superadmin.
4. **Test del wizard non-interactive (CI-like)**:
   ```bash
   AMELI_APP_CONFIGURE_ALLOWED_HOSTS=... \
   AMELI_APP_CONFIGURE_TRUSTED_PROXIES=127.0.0.1 \
   AMELI_APP_CONFIGURE_ADMIN_USER=admin \
   AMELI_APP_CONFIGURE_ADMIN_PASSWORD=... \
   sudo ameli-app --env-file /etc/.../app.env configure --yes
   ```
5. **Test del Caddyfile snippet + TLS end-to-end**:
   ```bash
   sudo cp deploy/caddy/Caddyfile.example /etc/caddy/Caddyfile
   sudo $EDITOR /etc/caddy/Caddyfile   # reemplaza __HOSTNAME__
   sudo systemctl reload caddy
   echo "AMELI_APP_SECURE_PROXY_SSL_HEADER=X-Forwarded-Proto=https" \
       | sudo tee -a /etc/.../app.env
   sudo systemctl restart ameli-app-template-prod-api.service
   curl -sf https://HOSTNAME/health | jq .
   ```
6. **Idempotencia**: re-correr `install.sh` una segunda vez. Debe ser
   no-op para las keys ya generadas (no regenera, no rompe estado).

**8c. Ruta de aprobacion y entrega**:

Si el testing sale bien:
1. **Cortar v0.5.10-django** (ritual: bump 4 archivos + PR contra main +
   CI verde + merge + tag). Este release cubre: v0.5.10 = WebFleet audit
   + DECISIONS #10 + installer + configurator. No requiere server
   validation (ya se validara en el test de manana).
2. **Entregar a la hija Starlink**. Prompt sugerido (para pegar en la
   sesion de la hija):

```
Contexto: el template AMELI publico v0.5.10-django con un overhaul del
onboarding (DECISIONS #10 + installer/configurator). Esto resuelve
los crashes de cascada que vimos al instalar con APP_ENV=prod (falta
de SECRET_KEY, AUDIT_HMAC_KEY, MFA_ENCRYPTION_KEY, y setup manual de
ALLOWED_HOSTS, TRUSTED_PROXIES, SMTP, superadmin, Caddy).

Cambios que hereda esta app:
- scripts/install.sh + scripts/_common.sh: auto-genera las 3 keys
  crypto idempotente + smoke post-install (/health).
- src/ameli_app/cli.py: nuevo subcomando `ameli-app configure`
  (wizard 4-secciones, --yes para CI).
- deploy/caddy/Caddyfile.example: snippet listo para copiar.
- .env.example: limpio del placeholder de SECRET_KEY.
- docs/DECISIONS.md #10: justificacion arquitectonica.
- docs/FIRST_INSTALL_DJANGO.md: Quickstart al frente con flujo de
  3 comandos.

Tarea:
1. Configurar remote template si no lo tienes:
   git remote add template https://github.com/HarDGameinc/AMELI-App-Template.git
   git fetch template --tags
2. Merge template/main hasta v0.5.10-django, o cherry-pick el commit
   `3145c65` + los que le siguen. Resolver conflictos si tu Dockerfile
   o compose divergieron.
3. Actualizar TEMPLATE_LINEAGE a v0.5.10-django.
4. RE-INSTALAR en el server con el nuevo install.sh (idempotente; no
   regenera keys ya existentes ni pisa configuracion actual). Debe
   completar sin los crashes de antes.
5. Si aun no lo hicieron, correr `ameli-app configure` para revisar/
   completar hosts, proxies, SMTP, superadmin.

Confirmar antes de commit y reportar si algo no aplica limpio.
```

**8d. Comandos utiles**:
```bash
# S-09 inicio de dia
git fetch origin --prune && git merge --ff-only origin/dev

# WSL diario
wsl && cd ~/ameli-app-template && git pull
APP_ENV=dev .venv/bin/pytest -q

# ¿que hay en dev sin promover? (para decidir si cortar release)
git log --oneline origin/main..origin/dev

# Test rapido local del wizard (sin tocar env real)
AMELI_APP_CONFIGURE_ALLOWED_HOSTS=test.local \
AMELI_APP_CONFIGURE_TRUSTED_PROXIES=127.0.0.1 \
AMELI_APP_CONFIGURE_ADMIN_USER=admin \
AMELI_APP_CONFIGURE_ADMIN_PASSWORD='TestPass!12?' \
.venv/bin/python -m ameli_app.cli --env-file /tmp/test.env configure --yes --check
```

## §9. Archivos clave de la sesion

- `docs/AUDIT_WEBFLEET_2026-07-21.md` — audit outbound integration.
- `docs/DECISIONS.md` (nuevo #10) — mantener `APP_ENV`, closer DX gap.
- `docs/FIRST_INSTALL_DJANGO.md` — Quickstart al frente (3 comandos).
- `scripts/install.sh` + `scripts/_common.sh` — auto-gen keys + smoke.
- `deploy/caddy/Caddyfile.example` — TLS reverse proxy ready-to-copy.
- `src/ameli_app/cli.py` — `ameli-app configure` wizard.
- `tests/test_cli_configure.py` — 9 tests del wizard.
- `.env.example` — limpio del placeholder SECRET_KEY.

## §10. Brief upstream desde la hija Starlink (recibido post-S-10)

Despues del cierre S-10, llego un brief de la sesion 2026-07-20/21 de la
app hija AMELI Report Starlink con 4 items para consideracion upstream,
respaldados por evidencia empirica de un primer push-to-server real bajo
DECISIONS #9. Decision del operador: **documentar todo, implementar nada
hoy** — las pruebas de manana (§8b) siguen priorizadas; los items del
brief se re-evaluan despues.

### 10.1 Propuesta DECISIONS #11: Windows-native + push-to-server (superseder #9)

**Evidencia**: peer bajo #9 WSL2-primary vs peer Linux-nativo trabajando en
paralelo en la hija, ~11h vs ~10h, output ~3x en favor de Linux nativo.
4 modos de friccion medidos: ~20 cp/heredoc sync (~10-15 min), escape de
paths con espacios en `wsl.exe -- bash -c`, CRLF+$-expansion en secrets,
Postgres sin systemd + no preview browser cross-fs. Total ~1h/sesion.

**Analisis (mi push-back medido)**:

- **Las primeras 3 fricciones sugieren #9 mal adoptada**: `cp/heredoc`,
  `wsl.exe -- bash -c` y CRLF son sintomas de editar en Windows y
  sincronizar a WSL manualmente — exactamente lo que #9 dice **no** hacer
  ("editar via UNC `\\wsl.localhost\...` o VS Code Remote-WSL"). Un
  chequeo con la sesion Starlink sobre que herramienta usaba el peer WSL
  para editar cerraria esa duda.
- **La 4ta friccion (Postgres sin systemd, preview cross-fs)** ES
  intrinseca a WSL vs Debian real. Techo genuino.
- **El multiplicador 3x** puede tener componentes no atribuibles: distinto
  scope (SVG chart vs dashboard completo), familiaridad, contexto. La
  friccion es real; el numero exacto no es concluyente.
- **#11 tiene sus propios costos**: cada validacion via `git push + SSH +
  pytest` es lenta comparada con loop local; contencion si hay multiples
  devs; sin server = sin dev; server como validador se acopla al deploy.
- **El CI ya es el validador**: full matrix + e2e + `test-postgres` +
  CodeQL corren en cada PR. #11 duplica ese rol.

**Propuesta upstream**: agregar #11 como **DECISIONS alternativo valido**,
NO superseder #9 wholesale. Documentar la evidencia empirica de Starlink
como contexto. Cada operador/maquina elige #9 o #11 segun fit. Si en 2-3
sesiones mas #11 gana consistentemente en otros contextos, ahi se puede
proponer supersession formal.

**Diferido a**: evaluacion en la sesion de manana tras probar el trabajo
de hoy en server. Puede que la experiencia propia de correr `install.sh`
+ `configure` desde WSL2 pese en la decision.

### 10.2 Follow-up: `install.sh --with-dev`

Bajo cualquier flujo tipo "server dev corre pytest post-push", falta
`requirements-dev.lock`. Hoy es paso manual.

**Diseño propuesto**: flag `--with-dev` opt-in en `install.sh`. Off por
default (matchea la postura prod actual, dev-deps no son supply-chain
surface para produccion). ~10 LOC: parsear flag; si presente, despues de
`install_python_deps` correr `pip install --require-hashes -r requirements-
dev.lock`. Documentar en `CONTRIBUTING.md` "Deploying to the dev server".

**Estado**: acepto, implementable en ~15 min. **Diferido a manana o
folded en v0.5.10 tras aprobacion del testing.**

### 10.3 Follow-up: `conftest.py` autodefensivo con `AMELI_APP_ENV_FILE`

**Bug real diagnosticado en Starlink**: `load_settings()` a nivel modulo
autodetecta `/etc/<slug>-<env>/app.env` por `cwd`; cuando pytest corre
desde el checkout instalado real (`/opt/<slug>-<env>`), inyecta config
prod antes que los tests puedan aserar defaults. 4 tests fallaron
deterministicamente en el primer push-to-server.

**Fix propuesto** (con tweak sobre lo que sugirieron):

```python
# tests/conftest.py, arriba, antes de cualquier import de Django
import os
os.environ.setdefault("AMELI_APP_ENV_FILE", os.devnull)
```

Con `os.devnull` en vez de `/dev/null` literal, es portable
(Windows=`nul`) — no rompe si algun dev corre pytest en Windows-nativo
(fallback per #9 o si se adopta #11). `setdefault` no pisa si el CI o
un dev ya paso su propio env-file. **1 linea, cero side-effect, protege
4+ tests en deploy real.**

**Estado**: acepto, es un bug legitimo. **Diferido a manana o folded en
v0.5.10 tras aprobacion del testing.**

### 10.4 Findings menores (doc-only)

- **Root shell / no sudo**: ya documentado en `CONTRIBUTING.md`
  "Deploying to the dev server". Si al pasar #11 upstream se agregan
  snippets nuevos, cuido de omitir `sudo`. **Nada por hacer hoy.**
- **`.env` con `$` en valores + CRLF**: no aplica al Django boot del
  template (`config.py:144` usa parser Python-nativo que evita el
  problema de shell), pero **vale una nota** en `OPERATIONS.md` o
  `SECURITY.md` sobre "never bash-source an env file with `$` in
  values — use the Python parser or single-quote". ~10 LOC docs.
  **Diferido — cabria en v0.5.10 junto con los otros fixes**.

### 10.5 Actualizacion del §7 roadmap con estos items

| # | Item nuevo del brief Starlink | Effort | Prioridad |
|---|---|---|---|
| — | **§10.3**: `conftest.py` `os.devnull` — 1 linea, cero riesgo | XS | ALTA — bloquea test-post-install en cualquier server |
| — | **§10.2**: `install.sh --with-dev` flag | S | media — cierra el ultimo hueco del install.sh |
| — | **§10.4**: nota `.env` `$`+CRLF en SECURITY.md/OPERATIONS.md | XS | baja — hija-especifico, doc-only |
| — | **§10.1**: DECISIONS #11 como alternativa a #9 | S | evaluar tras propia experiencia en el test de manana |

**Ruta sugerida para manana**:

1. **Primero**: ejecutar §8b (test del install.sh + configure + Caddy en
   server dev) como estaba planeado. Ver la propia experiencia del
   operador con #9 vs lo que dice el brief.
2. **Despues**: decidir cuales de §10.1-.4 entran a v0.5.10:
   - **§10.3 y §10.4**: candidatos claros (chicos, safe, doc-only o 1
     linea).
   - **§10.2**: candidato si el testing revela el pain de installar
     dev-deps manual.
   - **§10.1**: decision arquitectonica; puede ser un DECISIONS #11
     alternativo (mi propuesta) o folded en un release futuro segun mas
     evidencia.
3. **Cortar v0.5.10** con lo que quede en scope.
4. **Entregar a la hija** con prompt actualizado.
