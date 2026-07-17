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

## §5. Metricas al cierre

- Nuevos docs: **+1** (`docs/PRIVACY.md`, ~145 lineas).
- Runtime code / tests / migraciones: `unchanged`. Deps: `unchanged`.
- CI del release (`af540a4`): **verde** — matriz 3.11-3.14 + E2E +
  `test-postgres` + CodeQL + pip-audit. El push del handoff §3.2
  (`e555778`) NO disparo CI: `paths-ignore` lo salto como debia.
- Suite: `unchanged` (WSL2 1156/28, Windows 1126/58).
- Release cortado: **v0.5.8-django** (`main` = `c527af9`). Sin server
  validation ni redeploy (cero runtime prod).
- ASVS L2: `unchanged` (151 PASS).

## §6. Hallazgos / findings

- **[OPS]** La hija Starlink todavia no consume el canal template — no
  tiene remote `template` configurado ni cherry-picks aplicados. Ahora
  v0.5.8 le suma **PRIVACY.md + DECISIONS #8 + two-locks** al bundle que
  ya venia con v0.5.7 (5 fixes Docker). Prompt para su sesion sigue
  vigente y ahora apunta a un tag limpio.
- **[LOW/docs]** `PRIVACY.md` marca **portabilidad** como GAP
  documentado (no implementada en el template). Si la hija Starlink lo
  necesita, agregar un `/profile/export/` (dump JSON) es del orden de S.
- **[CLOSED]** DOCUMENTATION_PLAN bucket "productive/critical" cerrado
  (SBOM + PRIVACY.md).

## §7. Roadmap actualizado

| # | Item | Effort | Status |
|---|---|---|---|
| — | App hija Starlink: consumir v0.5.7 + v0.5.8 (fixes Docker + PRIVACY + DECISIONS #8) | S | open (prompts entregados, requiere sesion de la hija) |
| — | `/profile/export/` — data portability endpoint | S | open (gap documentado en PRIVACY.md §6) |
| — | jsdom DOM-wiring tests | M | open |
| — | Visual regression tests | M | open |
| — | Modelo C (`ameli-core` paquete) | L | deferred (DECISIONS #7) |
| — | Django LTS 6.2 (~dic-2026) | M | premature (5.2 LTS support hasta ~2028) |

## §8. Continuidad — para el proximo agente

**8a. Estado del servidor `ha-report2`.** En **v0.5.6-django**, `active`.
Ni v0.5.7 ni v0.5.8 requieren redeploy (cero runtime prod). `/health`
sube a v0.5.8 en el proximo `git pull` sin urgencia.

**8a-bis. Entorno WSL2.** Ubuntu 24.04 en `/home/hardg/ameli-app-template`,
branch `dev`, venv desde ambos locks, `uvloop` + `django 5.2.16`, suite
1156/28. Entrar con `wsl` (o `wsl -d Ubuntu-24.04`).

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
