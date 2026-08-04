## AMELI App Template handoff (sesion Claude, 2026-07-17)

Fecha: `2026-07-17`
Agente: `claude-opus-4-7`
Rama de trabajo: `dev` (version `v0.5.7-django`, HEAD `88700d3` al abrir)
Rama estable: `main` (en `v0.5.7-django`, `216a6e7`; al dia con `dev` menos 3
commits docs-only pendientes de promocion)
Sesion previa: [`CLAUDE_HANDOFF_2026-07-16_TEMPLATE_DEV.md`](CLAUDE_HANDOFF_2026-07-16_TEMPLATE_DEV.md)

> **Sesion en curso** — este handoff se completa durante el dia.

## §1. Snapshot al inicio

- `dev` == `origin/dev` (ahead 0, behind 0), **arbol limpio**. VERSION
  `v0.5.7-django`; `main` en `v0.5.7-django` (`216a6e7`, promovido ayer via
  PR #10).
- **3 commits en `dev` docs-only sin promover** desde v0.5.7: `9ab1202`
  (handoff 2026-07-16), `a5ccf3d` (DECISIONS #8), `88700d3` (correccion
  two-locks). Ninguno urge — la proxima promocion los recoge sola.
- **Entornos activos**: Windows nativo (loop diario, venv desde rangos → Django
  6.x local; suite 1126/58) **y WSL2 Ubuntu 24.04** (paridad Linux completa,
  venv desde ambos locks hash-pinneados → uvloop + django 5.2.16; suite
  **1156/28**, 30 tests mas que Windows).
- **CI verde** en el ultimo commit con codigo (v0.5.7, `216a6e7`).
- **Sin PRs abiertos.**
- **Server** (`ha-report2`): en `v0.5.6-django`, active. v0.5.7 no requiere
  redeploy (cero runtime prod); `/health` sube en el proximo `git pull` sin
  urgencia.

## §2. Objetivo de la sesion

Cerrar **`docs/PRIVACY.md`** (elegido via AskUserQuestion sobre el backlog).
Cierra el bucket "productive/critical" del `DOCUMENTATION_PLAN` junto con el
SBOM ya hecho. Trigger: la hija Starlink va a manejar datos reales.

## §3. Trabajo realizado

### 3.1. `docs/PRIVACY.md` (nuevo)

Documento consolidatorio (**cero cambios de runtime**) que inventaria lo que
YA existe en codigo, con referencias `file:line` verificadas:

- **Inventario de PII** — User, UserSession, MFARecoveryCode,
  MFAEmailChallenge, EmailChangeRequest, OutboundEmail, ThrottleCounter,
  AuditEvent — con proposito, campos y notas de proteccion por store.
- **Ventanas de retencion** — extraidas de
  `services/retention.py:29-33` (30d sessions/emails/email-change, 7d MFA
  email challenges, 1d throttle, AuditEvent indefinido por defecto).
- **Confidencialidad at rest** — argon2, Fernet TOTP secret,
  `salted_hmac` para MFA email (v0.5.5), MFA recovery hashed, audit HMAC
  chain, avatar EXIF/GPS strip pipeline.
- **In transit** — TLS Caddy con HSTS, cookies `__Host-`/`HttpOnly`/Lax.
- **Logs discipline** (V8.3.1) — sin bodies de request, wrap de excepciones
  con PII (`email_queue.py:147`, `av.py:_redact`).
- **Derechos** — access (`/profile`), rectification (form), **erasure
  self-service** (`/profile/delete-account/` → `services/user.py:552`),
  session/MFA management. **Portabilidad marcada como GAP** (no
  implementada en el template).
- **Third-party processors** — SMTP (siempre), HIBP (opt-in, k-anonymity
  → nunca la pw completa), AV, OTel. Todos opt-in salvo SMTP.
- **Trade-off audit vs erasure** — audit rows por default NO se
  cascade-borran al hacer `delete_my_account`; se documenta la opcion de
  `audit_max_age_days` con re-chain.
- **Backups** — cubren PII; nota GPG y de "un backup restaurado despues de
  una erasure debe repurgar".
- **§10 "Lo que el operador debe decidir por deploy"** — base legal, DPO,
  disclosure de transferencias transfronterizas, retention overrides,
  disclosure timeline, endpoint de portabilidad (si aplica), consent
  banner. Deja claro que el template ship los controles **tecnicos**; la
  parte legal es responsabilidad del operador.

Referencias actualizadas:
- `DOCUMENTATION_PLAN.md` — bucket "productive/critical" cerrado (SBOM +
  PRIVACY.md).
- `AGENTS.md` → indice de docs (entre SECURITY.md y THREAT_MODEL.md).
- `CHANGELOG.md` — seccion `## Unreleased (dev)`.

### 3.2. Corte v0.5.8-django (`af540a4`, PR #11)

Elegido por el operador tras cerrar PRIVACY.md: **tagear** el bundle de docs
para que la hija Starlink lo herede desde un tag limpio, en vez de esperar
al proximo release funcional.

Contenido del release (6 commits en `dev` desde v0.5.7):
- `dd69c2f` PRIVACY.md
- `b1e0649` handoff (cierre 07-16 + apertura 07-17)
- `a5ccf3d` DECISIONS #8 — Windows/WSL2/Docker
- `88700d3` two-locks correction (Dockerfile comment + DECISIONS #8 +
  CONTRIBUTING)
- `9ab1202` handoff 07-16 v0.5.7

Ritual: bump 4 archivos (VERSION + pyproject + CHANGELOG + AGENTS state
line). `chore(release): af540a4`. PR #11 abierto contra `main`.
**No requiere validacion en server** (cero cambio de runtime prod, como
v0.5.7). CI dispara porque `VERSION` y `pyproject.toml` estan fuera de
`paths-ignore` (comportamiento intencional del `RELEASE.md`).

**Cierre**: CI **verde** en PR #11 (matriz 3.11-3.14 + E2E + `test-postgres`
+ CodeQL + pip-audit), `MERGEABLE`/`CLEAN`. Merge commit **`c527af9`** en
`main`, tag + GitHub release **v0.5.8-django** publicados. `main` ahora en
v0.5.8-django. `dev` queda 1 commit adelante: `e555778` (este handoff §3.2,
retenido local durante el PR para no romper los required-checks via
`paths-ignore` — patron ya conocido; empujado post-merge).

### 3.3. Correccion same-day: DECISIONS #9 supersede a #8 + corte v0.5.9

**Trigger**: tras cerrar el S-10, el operador senalo que #8 (recien
shipeado en v0.5.8) documentaba una estrategia "Windows daily + WSL2 para
paridad" que fuerza **double work** — dos venvs, dos locks, dos suites,
dos sets de deps sincronizados a mano — exactamente lo opuesto al objetivo
("usemos WSL para desarrollo y pruebas, junto con despliegue local; despues
un paso a produccion en VM linux"). Mi lectura original de #8 fue
equivocada; correccion necesaria mismo dia.

**Cambios** (`8fe4832` + `34ee2f5` + `28b7438` + `4a6151c` merge + fix cosmetico `932db99`):
- **`DECISIONS.md` #9** supersede a #8. WSL2 Ubuntu 24.04 **ES** el
  entorno de dev (un clone, un venv desde ambos locks hash-pinneados =
  mismos deps que shipea a prod). **Despliegue local corre en WSL2
  directo** (`python -m ameli_app.api` contra Postgres local) — **sin
  Docker** (operator preference). Produccion sigue en la VM Linux
  `ha-report2`. Venv Windows-nativo = fallback (mypy DLL / emergencias);
  el clone en `C:\...` se trata como archivado. Edicion desde Windows
  via UNC `\\wsl.localhost\Ubuntu-24.04\...` o VS Code Remote-WSL.
- **#8 se marca "superseded by #9" in place**, no se borra (regla
  archive-history del propio `DECISIONS.md`).
- **`CONTRIBUTING.md`** invertida: WSL2 setup + Postgres local + daily
  loop al frente; Windows-nativo movido a subseccion "fallback deprecated".
- **`AGENTS.md`** narrativa actualizada.
- **Migracion practica**: WSL2 clone en `/home/hardg/ameli-app-template`
  quedo como canonico operativo; commits del dia hechos desde WSL para
  probar el flujo desde el minuto uno.

**Corte v0.5.9-django** (`4a6151c` bump + merge `98f32a5`, PR #12,
tag/release publicados): ritual de 4 archivos, CI **16/16 verde** (matriz
+ E2E + `test-postgres` + CodeQL + pip-audit + Analyze js/py),
`MERGEABLE`/`CLEAN`, merge autorizado por el operador. `main` avanza a
**v0.5.9-django**. Follow-up cosmetico post-merge: header duplicado
`## v0.5.7-django` en CHANGELOG (`932db99`, docs-only).

**Memoria actualizada**: `windows-local-dev-env` **invertida** — WSL2
primario, Windows fallback (antes decia "keep Windows for the daily loop",
ahora dice lo contrario). `MEMORY.md` index idem. `promote-to-main-
milestone` bumpeada a v0.5.9 con nota sobre docs-only releases no
requiriendo server validation.

## §4. Decisiones tomadas

- **PRIVACY.md documenta lo existente, no agrega runtime.** Nada en `src/`
  cambia; el documento consolida y expone gaps (portabilidad).
- **Portabilidad = gap documentado, no implementada.** La operacion queda
  en `admin export` o un endpoint futuro por-deploy. No la anadi hoy
  porque el bucket original la marcaba como "operator-per-deploy".
- **Audit NO cascade-borrado por default.** Trade-off explicito en §8 del
  documento (integridad de cadena vs erasure completo).
- **Cortar v0.5.8 solo para docs.** Justificado porque la hija Starlink
  quiere heredar PRIVACY + DECISIONS #8 + two-locks desde un tag limpio;
  esperar al proximo release funcional obligaria a la hija a cherry-pickear
  varios commits sueltos.
- **WSL2 es EL entorno de dev, no un fallback** (correcion §3.3). La
  vision del operador es una sola cadena: WSL para dev+tests+despliegue
  local -> VM Linux para produccion. Windows-nativo baja a fallback.
- **Sin Docker en el loop local.** WSL2 emula el server directamente
  (`python -m ameli_app.api` contra Postgres local). Docker queda solo
  para artefactos que shipean (guard por `test_docker_stack.py` + CI).
- **Cortar v0.5.9 same-day para superseder v0.5.8**. Un fork nuevo
  onboardeando hoy consumiria la estrategia mala si el tag mas reciente
  es v0.5.8. Vale el tag corrector para que v0.5.9 sea la fuente.
- **Migracion practica al clone WSL** ejecutada durante la misma sesion
  (commits `8fe4832`+ desde ahi, via UNC `\\wsl.localhost\...`). El
  clone Windows queda en sync como archivo, no se edita.

## §5. Metricas al cierre

- Nuevos docs: **+1** (`docs/PRIVACY.md`, ~145 lineas).
- Runtime code / tests / migraciones: `unchanged`. Deps: `unchanged`.
- CI del release (`af540a4`): **verde** — matriz 3.11-3.14 + E2E +
  `test-postgres` + CodeQL + pip-audit. El push del handoff §3.2
  (`e555778`) NO disparo CI: `paths-ignore` lo salto como debia.
- Suite: `unchanged` (WSL2 1156/28, Windows 1126/58).
- Releases cortados: **v0.5.8-django** (`c527af9`) y luego
  **v0.5.9-django** (`98f32a5`, correccion same-day de #8 → #9). `main`
  cierra el dia en v0.5.9. Sin server validation ni redeploy (cero
  runtime prod).
- ASVS L2: `unchanged` (151 PASS).

## §6. Hallazgos / findings

- **[OPS]** La hija Starlink todavia no consume el canal template — no
  tiene remote `template` configurado ni cherry-picks aplicados. Ahora
  **v0.5.9** le suma la estrategia WSL2 correcta (#9) + PRIVACY + los 5
  fixes Docker. Prompt actualizado entregado al operador apuntando a
  `v0.5.9-django` (NO `v0.5.8`).
- **[OPS]** **PR #13 abierto** (Dependabot, 2026-07-20 UTC): `chore(ci):
  Bump actions/setup-python from 6 to 7`. Bump menor de CI action; no
  urgente. Revisar y mergear cuando corresponda.
- **[LOW/docs]** `PRIVACY.md` marca **portabilidad** como GAP
  documentado (no implementada en el template). Si la hija Starlink lo
  necesita, agregar un `/profile/export/` (dump JSON) es del orden de S.
- **[CLOSED]** DOCUMENTATION_PLAN bucket "productive/critical" cerrado
  (SBOM + PRIVACY.md).

## §7. Roadmap actualizado

| # | Item | Effort | Status |
|---|---|---|---|
| — | App hija Starlink: consumir **v0.5.9** (fixes Docker + PRIVACY + DECISIONS #9) | S | open (prompt actualizado entregado, requiere sesion de la hija) |
| — | Revisar/mergear **PR #13** (Dependabot: setup-python v6→v7 en CI) | XS | open |
| — | `/profile/export/` — data portability endpoint | S | open (gap documentado en PRIVACY.md §6) |
| — | Postgres local en WSL2 para despliegue local (`apt install postgresql` + createuser/createdb, ver CONTRIBUTING) | XS | open (cuando quieras hacer el primer smoke local) |
| — | jsdom DOM-wiring tests | M | open |
| — | Visual regression tests | M | open |
| — | Modelo C (`ameli-core` paquete) | L | deferred (DECISIONS #7) |
| — | Django LTS 6.2 (~dic-2026) | M | premature (5.2 LTS support hasta ~2028) |

## §8. Continuidad — para el proximo agente

**8a. Estado del servidor `ha-report2`.** En **v0.5.6-django**, `active`.
Ni v0.5.7 ni v0.5.8 requieren redeploy (cero runtime prod). `/health`
sube a v0.5.8 en el proximo `git pull` sin urgencia.

**8a-bis. Entorno WSL2 = CANONICO OPERATIVO** (per DECISIONS #9). Ubuntu
24.04 en `/home/hardg/ameli-app-template`, branch `dev` en `932db99`,
venv desde ambos locks (`uvloop` + `django 5.2.16`), suite **1156/28**.
Entrar con `wsl`. Commits del dia hechos desde WSL para practicar el
flujo. El clone en `C:\...\AMELI_APP_TEMPLATE` esta sincronizado pero
tratado como archivado — no editar ahi.

**8b. Orden recomendado.**
1. **Retomar la hija Starlink** — el prompt entregado apunta a
   `v0.5.7-django` + ahora `v0.5.8-django`. La hija debe: configurar
   remote `template`, cherry-pickear los tags (o copiar los 3 archivos
   Docker + `docs/PRIVACY.md` + `docs/DECISIONS.md` #8), y actualizar
   `TEMPLATE_LINEAGE`.
2. Si sigues en el template: `/profile/export/` (portabilidad, S) es el
   proximo hueco util. Si no, jsdom DOM-wiring (M) o **Modelo C** cuando
   la flota crezca.

**8c. Comandos utiles.**
```bash
# S-09 inicio de dia
git fetch origin --prune && git merge --ff-only origin/dev
# WSL2 (paridad Linux)
wsl -d Ubuntu-24.04
cd ~/ameli-app-template && git pull && .venv/bin/pytest -q
# server ground-truth (nunca adivinar)
cd /opt/ameli-app-template-dev && APP_ENV=dev bash scripts/validate_installation.sh
# proximo release: bump los 4 archivos + PR + tag
# (RELEASE.md ritual; no server validation si no toca src/)
```

## §9. Archivos clave de la sesion

- `docs/PRIVACY.md` — nuevo documento canonico de privacidad.
- `VERSION`, `pyproject.toml`, `CHANGELOG.md`, `AGENTS.md` — ritual v0.5.8
  en sync.
- `docs/CLAUDE_HANDOFF_2026-07-16_TEMPLATE_DEV.md` — cerrado con §3.5
  (DECISIONS #8) + §3.6 (WSL2 setup + two-locks).
