# Phase A audit — pre-production review of AMELI App Template

Fecha: 2026-06-24
Agente: claude-opus-4-7 (audit subagente lanzado al cierre del 24-jun)
HEAD `dev`: `38c6160` (15 commits ahead de `main @ 4b36607`)
Server `ha-report2`: `36c4329` del 22-jun (17 commits atras de `dev`)

Este documento es el resultado de Fase A del plan de revision final
pre-produccion (ver `CLAUDE_HANDOFF_2026-06-24_TEMPLATE_DEV.md` §7.1).
NO es una review — es el inventario "ya revisado / pendiente / blind
spots" que enfoca las Fases B-D para no quemar tokens auditando lo
que ya tiene 4 pasadas previas.

## 1. Que ya esta revisado

### ASVS L2 — `docs/COMPLIANCE_ASVS_L2_2026-06-16.md`

- **151 PASS** confirmados (135/149 active rows PASS = 90.6%).
- **0 strict GAPs**, 9 N/A, 9 DEFERRED.
- 2 GAP-accepted con residual risk IDs: V11.1.5 → R-09 (sudo replay),
  V13.1.5 → R-10 (body parsing limit).
- PASS por capitulo: V1=11, V2=21, V3=17, V4=10, V5=15, V6=7, V7=11,
  V8=7, V9=3, V10=3, V11=5, V12=10, V13=7, V14=24.
- Cada PASS tiene file:line evidence + 11 "wire-verified" en
  `ha-report2`.

### Supply chain

- `requirements.lock` + `requirements-dev.lock` con
  `pip-compile --generate-hashes` (cerrado 2026-06-18 roadmap #14).
- `pip install --require-hashes` en CI (`ci.yml:69`) y en deploy
  (`scripts/_common.sh:install_python_deps`).
- `pip-audit --strict` hard-fail desde 2026-06-17 (roadmap #15/#22 —
  `continue-on-error` dropped, `ci.yml:131-166`).
- `tests/test_lockfile_hashes.py` pin del contrato.

### Threat model — `docs/THREAT_MODEL.md`

- Scope: T1 reverse proxy / T2 Django / T3 DB / T4 CLI / T5 workers.
  STRIDE por boundary.
- 10 attack scenarios S-01..S-10 con first-line + second-line defence.
- Review cadence definido (§6).
- Out-of-scope explicito (compromised proxy, compromised operator, CI
  compromise, side-channels, coercion).

### Tests + coverage

- **1004 unit pass** + **4 e2e pass** (handoff 24-jun §5).
- Coverage 85% floor en `pyproject.toml [tool.coverage.report]`. Wired
  a CI (`ci.yml:128`).
- 91 archivos de test (incluyendo `conftest.py` y `e2e/`).
- 5 tests dedicados a hardening blocks
  (`test_security_hardening_block{1,2,3,4}.py`) +
  `test_settings_boot_guards.py` + `test_hardening_20260615.py`.

### CI gates (`.github/workflows/ci.yml`)

- Lint+Test matrix Python 3.11 + 3.12: ruff (`S` ruleset =
  bandit-equivalent), ruff format, bandit `-ll -ii`, mypy
  (django-stubs), `manage.py check`, `makemigrations --check`,
  pytest+coverage.
- `supply-chain-audit` job hard-fail.
- `e2e` job (Playwright + chromium).
- Concurrency: cancel-in-progress.

### Crypto key custody — `docs/SECURITY.md`

- 3 secret classes documentadas con procedure: `SECRET_KEY`,
  `AUDIT_HMAC_KEY`, `MFA_ENCRYPTION_KEY` (+ `BACKUP_GPG_RECIPIENT`).
- Rotation cadence: 12 meses cada una.
- Boot guards verificados en `settings.py:386-394` (AUDIT_HMAC_KEY) y
  `:468-477` (MFA_ENCRYPTION_KEY). Cerrados R-11 y R-12 por
  independent audit 2026-06-19.

### Independent security re-audit (handoff 19-jun)

- 2 latent bugs encontrados por agente paralelo: `AUDIT_HMAC_KEY` sin
  boot guard (HIGH) y `AV_ENDPOINT` scheme sin validar (MED). Ambos
  cerrados (R-11, R-12).
- Mejor evidencia disponible de que el 151 PASS aguanta una segunda
  mirada.

## 2. Pendientes / gaps claros

### Doc-drift / red flags

- `docs/SECURITY.md:172` dice "ASVS 4.0.3 L2: 63 PASS / 24 GAP /
  5 N/A / 10 DEFERRED" referenciando el doc del 06-15 —
  **inconsistente con el 06-16 que dice 151 PASS / 0 GAP / 9 N/A /
  9 DEFERRED**.
- Handoff 24-jun §7.1 menciona "services.py (2956 lineas)"; el wc
  real es **3793 lineas** (152 KB).
- `docs/COMPLIANCE_ASVS_L2_2026-06-15.md` aun esta en repo;
  referencias cruzadas en `THREAT_MODEL.md:9` apuntan al 06-15.

### Modulos grandes sin code-review humano-equivalente

- **`accounts/services.py`** 3793 lineas, 121 def/class. Tocada por
  circuit_breaker, OTel hooks, breakers AV/HIBP/SMTP, throttle ceil
  fix. Solo ruff/bandit + tests por endpoint; no aparece como
  "revisada modulo entero" en ningun handoff.
- **`accounts/views.py`** 1185 lineas. Misma situacion — Bug F
  (selectores por ID, JS inline en `profile.html:588-606`) sugiere
  zonas del view + template no exploradas.
- **`accounts/middleware.py`** 411 lineas. Critica (CSP, sudo,
  cache-control, absolute session ceiling). Tests dedicados sí
  existen pero el modulo entero no fue sweep estructural.
- **`accounts/admin.py` + `ameli_web/admin_views.py`** (745 lineas
  combinadas). El admin panel custom no aparece en handoffs reciente
  como "review focal".
- **`accounts/mfa.py`** 221 lineas — TOTP + email MFA. Crypto critica.
  Flujo MFA stacked TOTP+email (anadido en `cd84d99/3226857`) merece
  confirmacion explicita de que threat model T2 lo cubre.

### Threat model gaps (post-mapping 06-16)

- **MFA flow stacked (TOTP + email)** anadido post 2026-06-16.
  `THREAT_MODEL.md` §3 T2 menciona MFA pero la STRIDE no diferencia
  los 2 metodos ni el flow donde el atacante puede degradar TOTP →
  email.
- **OpenTelemetry** (shipped 22-jun) no aparece en threat model. Si el
  operador setea endpoint untrusted, exfiltracion de DB queries
  (psycopg auto-instrument captura SQL+args).
- **django-silk** (shipped 22-jun, opt-in con boot guard prod). Si se
  activa accidentalmente, leak de request/response bodies. Boot guard
  refuse-in-prod existe pero no esta en `THREAT_MODEL.md`.
- **Circuit breakers** (shipped 22-jun) crean side-channel: estado
  process-local. Threat model no menciona ataque "force breaker open"
  para denial of MFA email/AV scan.

### Ops + runbook

- **Backup automatizado**: timer `ameli-app-backup.timer` instalado
  (handoff 19-jun PT-4); primer trigger 2026-06-20 04:11 — el
  handoff 20-jun no confirma el wire test del trigger automatico.
- **Restore esta probado**: `restore.sh verify` en handoff 19-jun
  contra archive real. Pero **no hay test de full destructive restore
  wired en CI**.
- **Secret rotation**: documentado en `SECURITY.md` pero nunca
  ejercitado wire. `AUDIT_HMAC_KEY` rotation tiene CLI + tests;
  `SECRET_KEY` rotation solo doc; `MFA_ENCRYPTION_KEY` tiene un
  caveat enorme (migrate 0011 → 0012 sin el cual pierde secrets),
  pero no hay wire test ni runbook step-by-step en `OPERATIONS.md`.
- **Onboarding "motor para otras apps"**: NO existe documento.
  `AGENTS.md` §"Documentation baseline" lista archivos pero no hay
  `BUILDING_NEW_APP.md` ni similar.

## 3. Blind spots probables

### Fuera del scope ASVS L2

- **Dev deps no escaneadas igual que runtime**: `pip-audit -r
  requirements-dev.lock` corre, pero el blast radius de un dev dep
  comprometido (pytest, ruff, mypy plugins) afecta CI runner / dev
  machines. No hay separacion de policy.
- **Data retention para PII en backups**: backup retention=30 days,
  pero `purge_inactive_users` corre sobre live DB. Si user pidio
  delete-my-account → la fila se borra del live DB pero sigue en los
  30 dias de backups. Probable gap GDPR si el template apunta a EU.
- **Side channels**: declarado out-of-scope en `THREAT_MODEL.md` §5.
- **Time-of-check vs time-of-use** en `verify_audit_chain`: cron-timer
  corre periodicamente; entre runs un tamper con re-stamp bajo live
  key seria invisible. R-02 lo acepta pero el threat model T3 no lo
  dice explicitamente.

### Claims en handoffs sin validacion en CI

- **"151 PASS"** vive solo en `COMPLIANCE_ASVS_L2_2026-06-16.md`. No
  hay CI gate que verifique que un control ASVS no regresione (e.g.
  un test que valide "HSTS aun activo outside dev"). Cada PASS es un
  snapshot manual.
- **"4/4 e2e pass"** confirmado local Windows 06-24 + CI run
  `28103042736` "in_progress→✓ esperado" — handoff cierra antes de
  confirmar CI verde.
- **Boot guards** de `AUDIT_HMAC_KEY` y `MFA_ENCRYPTION_KEY` existen
  en `settings.py:386,468`. CI no los ejercita porque corre con
  `APP_ENV=dev` implicito + `AMELI_APP_AUDIT_HMAC_KEY` deliberadamente
  unset (`ci.yml:35-40`). Solo `tests/test_settings_boot_guards.py`
  valida que el `RuntimeError` se levanta — pero ese test corre como
  unit, no como integration. No hay deploy smoke en `ha-report2` que
  confirme que el server prod requiere las keys.
- **Server `ha-report2` corre `36c4329` del 22-jun**. 17 commits de
  `dev` no estan deployados — incluye cosmetico breaker + e2e fixes
  + bug fix throttle ceil. El claim "production-ready" debe
  contemplar que el ultimo deploy es de 2 dias atras.

### Codigo runtime cambiando frecuente

- `circuit_breaker.py` (162 lineas) shipped 22-jun, modificado 24-jun.
  13 tests pero solo un sweep estructural revelaria si el
  state-machine es race-safe bajo concurrencia ASGI.
- `telemetry.py` (9545 bytes) shipped 22-jun con 3 commits de fix.
  Tests `test_telemetry.py` existe pero el modulo no aparece en
  handoffs como "review focal".

## 4. Prioridad recomendada para Fases B-D

| # | Trabajo | Costo | Skill / metodo |
|---|---|---|---|
| 1 | Security review focal sobre `services.py` + `views.py` + `middleware.py` | ~45 min | `security-review` skill (effort high) |
| 2 | Threat model gap analysis post-22-jun (MFA stacked, OTel, silk, breakers) | ~20 min | inline / agente |
| 3 | Reconciliar doc-drift compliance (`SECURITY.md`, `THREAT_MODEL.md`, §7.1 line count) | ~10 min | inline |
| 4 | Code review estructural de `services.py` | ~30 min | `code-review` skill |
| 5 | Crear `BUILDING_NEW_APP.md` (motor-as-template onboarding) | ~30 min | inline |
| 6 | (opcional) backup destructive restore wire test | ~15 min | inline |

### Comandos de validacion sugeridos al operador

- `gh run list --workflow=ci.yml -L 5` — confirmar que el ultimo run
  del `e2e` job esta verde.
- `wc -l src/ameli_web/accounts/services.py` — confirmar 3793.
- `grep -n "63 PASS\|151 PASS" docs/SECURITY.md docs/COMPLIANCE*.md` —
  identificar el doc-drift en compliance posture.
- `git log --since=2026-06-16 --name-only -- docs/THREAT_MODEL.md` —
  confirmar si el threat model se actualizo post-MFA-stacked.
- `journalctl -u ameli-app-template-dev-backup.service --since
  2026-06-20` (en `ha-report2`) — confirmar primer trigger automatico
  del backup timer.
