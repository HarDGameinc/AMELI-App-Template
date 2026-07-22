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
