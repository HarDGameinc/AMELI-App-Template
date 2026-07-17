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

## §4. Decisiones tomadas

- **PRIVACY.md documenta lo existente, no agrega runtime.** Nada en `src/`
  cambia; el documento consolida y expone gaps (portabilidad).
- **Portabilidad = gap documentado, no implementada.** La operacion queda
  en `admin export` o un endpoint futuro por-deploy. No la anadi hoy
  porque el bucket original la marcaba como "operator-per-deploy".
- **Audit NO cascade-borrado por default.** Trade-off explicito en §8 del
  documento (integridad de cadena vs erasure completo).

## §5. Metricas al cierre

- Nuevos docs: **+1** (`docs/PRIVACY.md`, ~145 lineas).
- Runtime code / tests / migraciones: `unchanged`. Deps: `unchanged`.
- CI: no dispara (docs-only, `paths-ignore`).
