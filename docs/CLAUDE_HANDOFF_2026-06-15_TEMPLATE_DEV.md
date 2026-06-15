## AMELI App Template handoff (sesion Claude, 2026-06-15)

Fecha: `2026-06-15`

Continuacion de
[`CLAUDE_HANDOFF_2026-06-13_TEMPLATE_DEV.md`](CLAUDE_HANDOFF_2026-06-13_TEMPLATE_DEV.md)
(que a su vez es el doc retroactivo que esta sesion escribio para
cerrar el gap dejado por la sesion del 13).

Sesion dedicada al frente de seguridad y compliance: security review,
code review, ASVS L2 gap analysis, y dos batches de fixes que
cerraron 7 findings HIGH+MEDIUM del code review, 6 gaps top del ASVS
y los 3 LOW del code-review.

### Estado general al cierre

- Repo: `HarDGameinc/AMELI-App-Template`
- Rama estable: `main` (todavia en `644599b` — promocion pendiente)
- Rama de trabajo: `dev` (HEAD `42efbd4`)
- **693/693 tests verde** (`pytest -q`), 0 regresiones
- 4 commits funcionales + 3 docs nuevos esta sesion

### Resumen ejecutivo

La sesion arranco con el repo en una situacion de continuidad rota:
la sesion anterior del 2026-06-13 habia pusheado 13 commits a `dev`
(CI workflow, Docker, backup, metrics, request_id, maintenance mode,
etc.) y llego al limite de contexto sin escribir el handoff de cierre.
La sesion del 15 empieza re-construyendo ese handoff retroactivo,
despues ejecuta el plan que el usuario planteo ("revisemos todos los
puntos y recien pasamos a main"):

1. **Security review** sobre `main..dev` (61 commits sin auditar).
   Veredicto: limpio. Cero hallazgos HIGH+MEDIUM con >=7 confidence.
2. **Code review** sobre el mismo diff con 7 angulos paralelos
   (line-by-line, removed-behavior, cross-file, reuse, simplificacion,
   eficiencia, altitud). Resultado: 10 findings. 7 HIGH+MEDIUM se
   parchearon con tests, 3 LOW quedaron para el batch siguiente.
3. **ASVS L2 gap analysis** completo (V1-V14) contra `dev`. Score:
   63 PASS / 24 GAP / 5 N\\A / 10 DEFERRED. Headline: el stack de
   identidad / sesion / audit / crypto-at-rest esta sobre el bar L2;
   los gaps clusterizan en supply-chain hygiene, disclosure
   plumbing, y drift spec-vs-codigo (los handoffs viejos mencionan
   API tokens y webhooks que se removieron en `641ece1`).
4. **Top 6 gaps ASVS + 3 LOW code-review** cerrados en un solo
   batch: HSTS default, Cache-Control no-store, SECURITY.md,
   THREAT_MODEL.md, PII purge CLI, self-service delete-account,
   deps con `~=`, pip-audit en CI, backup.sh exit-2 contract,
   record_audit Decimal-safe, retention worker try/except.

### Bloque del dia (4 commits)

| Commit | Tema | Tests |
|---|---|---|
| `2114427` | handoff retroactivo 2026-06-13 | — |
| `0077fb0` | code review fixes — 7 HIGH+MEDIUM | 670 → 679 |
| `67579aa` | ASVS L2 gap analysis (doc) | — |
| `42efbd4` | top 6 ASVS gaps + 3 LOW code-review | 679 → 693 |

#### `2114427` — Handoff retroactivo 2026-06-13

Reconstruyo el handoff de cierre que la sesion del 13 nunca alcanzo
a escribir. Documenta los 13 commits entre `5b0a718` (close handoff
bloque 4) y `bc747fe` (HEAD pre-esta-sesion): `/health` extendido,
request_id correlation end-to-end, maintenance-mode singleton,
retention sweep worker, `/metrics` Prometheus, sessions pagination
fix, GitHub Actions CI workflow, Docker dev stack, backup pipeline
con restore verify, ruff baseline cleanup, env fixes de CI.

#### `0077fb0` — Code review fixes (7 HIGH+MEDIUM)

| # | Fix | Severidad |
|---|---|---|
| 1 | `_prune_audit_with_anchor` re-chains survivors bajo la live key en vez de demote a `hmac=""`. Tampering post-prune se sigue detectando. | HIGH |
| 2 | `MaintenanceModeMiddleware.BYPASS_PREFIXES` agrega `/profile/password/` y `/profile/email-change/`. User con `must_change_password=True` no queda atrapado en read-only window. | HIGH |
| 3 | `_operational_allowlist_block` matchea contra `REMOTE_ADDR` primero, despues `client_ip`. Operador que setea `HEALTH_METRICS_ALLOWLIST=['127.0.0.1']` ya no recibe 403 cuando los probes vienen via Caddy. | HIGH |
| 4 | Sliding-window throttle nuevo (`_read_throttle_counter_sliding`) usado por login, forgot-password y MFA-resend. Cierra el burst de ~2x el cap en el borde de bucket. | MEDIUM |
| 5 | `ProfilePreferencesForm` dropea `email` de `Meta.fields`. UI ya no miente al user. | MEDIUM |
| 6 | `RequestIdMiddleware` setea `X-Request-Id` dentro del try block y expone `process_exception`. Correlation sobrevive el error path. | MEDIUM |
| 7 | `change_password_view` rama HTML llama `revoke_sudo` igual que la rama JSON. | MEDIUM |

Tests: 9 nuevos en `tests/test_code_review_fixes_20260615.py` +
ajuste de `tests/test_maintenance_mode.py` (cambia el probe canonico
de "non-staff write" de `/profile/password/` a `/profile/preferences/`).

#### `67579aa` — ASVS 4.0.3 L2 gap analysis

Mapping completo de los 14 capitulos contra el HEAD de `dev`.
**63 PASS / 24 GAP / 5 N\\A / 10 DEFERRED**. Headline:

- Identidad / sesion / audit / crypto-at-rest: sobre el bar L2.
- Gaps clusterizados en:
  - Supply chain (deps `>=`, no SBOM, no pip-audit)
  - Disclosure plumbing (sin SECURITY.md, sin threat model)
  - PII lifecycle (sin purge, sin self-service delete)
  - Hardening de segunda linea (HSTS off, no Cache-Control no-store,
    TOTP unencrypted at rest)
- Drift spec-vs-codigo: handoffs viejos mencionan API tokens y
  webhooks que se removieron en `641ece1`.

El doc en `docs/COMPLIANCE_ASVS_L2_2026-06-15.md` cierra con un
roadmap ordenado de 20 gaps (Small / Medium / Large), citando
cada uno por control id y proponiendo el fix.

#### `42efbd4` — Top 6 ASVS + 3 LOW code-review

Items cerrados en este batch:

**ASVS V14.4.5 / V9.1.2 — HSTS on by default outside dev.**
`SECURE_HSTS_SECONDS=31536000` + `includeSubDomains` cuando
`ENV_NAME != "dev"`. Operador puede opt-out con
`AMELI_APP_HSTS_SECONDS=0`. `PRELOAD` queda en False porque la
sumision a hstspreload.org es efectivamente irreversible.

**ASVS V8.2.1 — Cache-Control: no-store en respuestas autenticadas.**
`SecurityHeadersMiddleware` stampa `no-store, max-age=0` + `Pragma:
no-cache` cuando el usuario esta autenticado AND no hay
`Cache-Control` explicito en la response (asi una vista que
deliberadamente decide cachear no se sobrescribe).

**ASVS V8.3.3 — self-service delete-account.**
`/profile/delete-account/` requiere current password (sesion robada
no alcanza), refusa superadmins (deben promover a otro primero),
audit row tombstone, logout post-delete.

**ASVS V8.3.4 — PII purge CLI.**
`ameli-app purge-inactive-users [--days N] [--dry-run]` borra
usuarios `is_active=False` mas viejos que `--days`. Skipea
superadmins. Cada delete escribe `user_purged_for_inactivity`
audit row.

**ASVS V14.2.1 / V14.2.2 / V14.2.3 — supply chain hygiene.**
`requirements*.txt` pasan de `>=` a `~=` (compatible release):
Dependabot puede shippear 5.2.3 -> 5.2.4 pero Django 6.0 requiere
PR explicito. Nuevo CI job `supply-chain-audit` corre `pip-audit
--strict` contra ambos archivos. `continue-on-error: true` mientras
el baseline se estabiliza — promover a hard fail en follow-up.

**ASVS V1.1.1 — SECURITY.md.**
Disclosure policy, supported versions, key custody (SECRET_KEY,
AUDIT_HMAC_KEY, BACKUP_GPG), residual-risk register (R-01..R-08),
operator security checklist, compliance posture, out-of-scope.

**ASVS V1.1.2 — THREAT_MODEL.md.**
STRIDE-style pass sobre 5 trust boundaries (T1 reverse proxy / T2
Django / T3 DB / T4 CLI / T5 workers), 10 attack scenarios
nombrados (S-01..S-10), cadencia de review.

**LOW code-review A2 — backup.sh exit code 2.**
`scripts/_common.sh:fail` ahora acepta un primer arg numerico
opcional como exit code. `backup.sh` lo usa para distinguir DB
dump failed (2) de errores genericos (1).

**LOW code-review A4 — record_audit canonical bytes.**
`_normalise_audit_payload` round-trips el payload via
`DjangoJSONEncoder + json.loads` antes del INSERT. Decimal /
datetime / UUID / tuple landean en su forma JSON que la DB
round-trippea de vuelta, asi `verify_audit_chain` no reporta
phantom tamper.

**LOW code-review C4 — retention worker robusto.**
`_run_retention` envuelve `run_retention_sweep` en try/except
y retorna `{ok:false, error:...}` en caso de excepcion. Systemd
journal sigue carrying la tick line.

Tests: 14 nuevos en `tests/test_hardening_20260615.py`.

### Numeros del dia

- 4 commits funcionales pusheados a `dev`
- **693 tests verde** (670 al inicio del dia → 693, +23 tests)
- 3 docs nuevos (`SECURITY.md`, `THREAT_MODEL.md`,
  `COMPLIANCE_ASVS_L2_2026-06-15.md`)
- 1 nueva ruta web (`/profile/delete-account/`)
- 1 nuevo CLI subcommand (`purge-inactive-users`)
- 1 nuevo CI job (`supply-chain-audit`)
- 0 migraciones nuevas
- 0 dependencias Python nuevas (pip-audit ya estaba conceptualmente
  en el roadmap)
- 0 regresiones

### Decisiones tomadas (no re-discutirlas)

- **Re-chain survivors en lugar de demote**: el prune de audit
  re-stampa hmacs con la live key. Sacrifica el link al head
  borrado pero preserva integrity post-prune. Operador que
  necesita los hmacs originales debe archivar la tabla externa.
- **`/profile/password/` siempre bypassed en maintenance**: un user
  con must_change_password atrapado no es opcion.
- **Allowlist matchea REMOTE_ADDR + upstream**: opcion B del review.
  `127.0.0.1` matchea tanto local directo como local via proxy.
- **Sliding-window aproximacion**: time-weighted previous bucket.
  Suficiente para cerrar el burst de 2x sin pagar el costo de un
  log per-event.
- **`PRELOAD` queda False**: HSTS preload es efectivamente
  irreversible; el operador lo activa explicitamente.
- **Cache-Control respeta headers explicitos**: si una vista
  deliberadamente cachea, no la sobrescribimos.
- **Superadmins no se auto-eliminan**: ni el endpoint ni el CLI
  los borran. Promover otro superadmin primero.
- **`pip-audit` continue-on-error mientras estabiliza**: zero-day
  no debe bloquear merges no relacionados. Promover a hard fail
  cuando el baseline este limpio.
- **Drift spec-vs-codigo**: webhooks y API tokens NO van a
  re-implementarse en el template baseline. Los handoffs viejos
  deberian barrerse para reflejarlo.

### Snapshot al cierre — postura ASVS L2

| Capitulo | Antes (commit `0077fb0`) | Despues (commit `42efbd4`) |
|---|---|---|
| V1 Architecture | 1 PASS / 3 GAP | 3 PASS / 1 GAP (SECURITY.md + THREAT_MODEL.md cerraron 1.1.1 + 1.1.2) |
| V8 Data protection | 3 PASS / 3 GAP | 5 PASS / 1 GAP (8.2.1 + 8.3.3 + 8.3.4 cerrados) |
| V9 Communications | 2 PASS / 1 GAP | 3 PASS / 0 GAP (HSTS default cierra 9.1.2) |
| V14 Configuration | 7 PASS / 4 GAP | 9 PASS / 2 GAP (14.4.5 + parcial 14.2.1/.2/.3) |

Score total estimado: 63 → ~69 PASS de los controles activos.

### Pendientes del roadmap ASVS (16 items)

| # | Item | Effort | Capitulo |
|---|---|---|---|
| 1 | TOTP secret encrypt at rest (Fernet) | M | V2.8 |
| 2 | Email alert al user en N consecutive auth failures | S | V2.2.3 |
| 3 | Absolute session ceiling | S | V3.3.3 |
| 4 | `/media/` owner-only (no solo auth-only) | S | V4.2.1 |
| 5 | SRI hashes para CDN o vendor swagger/redoc | S | V10.3.1 |
| 6 | bandit + ruff S310 hard fail en CI | S | V10.1.1 |
| 7 | AV scan opcional sobre avatares | M | V12.4.1 |
| 8 | handler404 / handler500 personalizados | S | V7.4.1 |
| 9 | Authz centralizada en `accounts/permissions.py` | M | V1.4.4 |
| 10 | Contract test OpenAPI doc vs realidad | S | V13.2.2 |
| 11 | Boot-guard que refusa `MESSAGE_STORAGE` no-JSON | S | V5.5.1 |
| 12 | `__Host-ameli_session` cookie name por default | S | V3.4.4 |
| 13 | `RedactingFilter` en logs para scrub PII | S | V7.1.1 |
| 14 | Lockfile con hashes (`pip-compile --generate-hashes`) | M | V14.2.3 |
| 15 | Promote `pip-audit` a hard fail | S | V14.2.2 |
| 16 | Doc drift cleanup en handoffs viejos | S | (no ASVS, housekeeping) |

### Items LOW del code-review que quedan sin cerrar

(Ninguno — los 3 LOW de la sesion del 0077fb0 ya estan en `42efbd4`.)

### Para el proximo agente

- Rama de trabajo: `dev` (HEAD `42efbd4`)
- Rama estable: `main` (en `644599b`; **66 commits atras** —
  promocion pendiente)
- Sin migraciones nuevas
- Server dev `ha-report2`: no recibio el codigo de los ultimos 4
  commits. `git fetch && reset --hard origin/dev` + `migrate`
  (no-op) + `systemctl restart`.
- CI: workflow corriendo, el job `supply-chain-audit` se activa
  en el proximo push a `main`/`dev`.

### Orden recomendado para retomar

1. **Decidir promocion a `main`**: el snapshot esta solido
   (693 tests, security review limpia, ASVS L2 cerca de 70%).
2. Antes de promover, hacer el sweep de drift en docs viejos:
   `docs/CLAUDE_HANDOFF_2026-06-09.md` y posteriores mencionan
   webhooks y API tokens como features activos pero se removieron
   en `641ece1`. Add a footer "este texto referencia subsistemas
   que se eliminaron del baseline en `641ece1`" — preserva
   continuidad sin re-escribir historial.
3. Despues de promover, atacar el roadmap ASVS en este orden:
   - Items 2, 3, 4, 8, 11, 12, 13 (Small, ~1 dia)
   - Items 1, 7, 9, 14 (Medium, ~3 dias)
   - Items 5, 6, 10, 15, 16 (Small follow-ups)

### Comandos utiles de continuidad

Sync local + server al hash `42efbd4`:

```bash
# Local
git fetch origin && git checkout dev && git reset --hard origin/dev

# Server dev
cd /opt/ameli-app-template-dev
git fetch origin && git reset --hard origin/dev
.venv/bin/ameli-app shell -c "from django.core.management import call_command; call_command('migrate')"
systemctl restart ameli-app-template-dev-api.service
```

Probar el nuevo endpoint self-service delete (requiere user no-superadmin):

```bash
curl -X POST http://10.100.100.16:18080/profile/delete-account/ \
    -H "Content-Type: application/json" \
    -H "Cookie: <session>" \
    -d '{"password": "<current>"}'
# Esperado: {"ok": true, "deleted_username": "..."} + session destroyed
```

Probar el CLI de purge en dry-run:

```bash
.venv/bin/ameli-app purge-inactive-users --days 365 --dry-run
# Imprime {ok:true, dry_run:true, candidates:[...], count:N, cutoff:...}
```

Promover dev → main (cuando se decida):

```bash
git checkout main && git merge --ff-only dev && git push origin main
# Si --ff-only falla, dev divergio — investigar antes de force-merge
```

Tests + CI local:

```bash
DATABASE_URL= /tmp/venv/bin/pytest -q
# 693/693 green
ruff check .                        # clean
pip-audit --strict -r requirements.txt -r requirements-dev.txt
```

### Archivos clave de la sesion

- `docs/COMPLIANCE_ASVS_L2_2026-06-15.md` — gap analysis completo
- `docs/SECURITY.md` — disclosure + key custody + residual risks
- `docs/THREAT_MODEL.md` — STRIDE + attack scenarios
- `src/ameli_web/accounts/middleware.py` — Cache-Control no-store +
  `BYPASS_PREFIXES` extendido
- `src/ameli_web/accounts/services.py` — sliding-window throttle,
  `_prune_audit_with_anchor` re-chain, `_normalise_audit_payload`,
  `purge_inactive_users`, `delete_my_account`
- `src/ameli_web/accounts/views.py` — `delete_my_account_view`
- `src/ameli_web/accounts/forms.py` — drop `email` de prefs form
- `src/ameli_web/accounts/urls.py` — `/profile/delete-account/`
- `src/ameli_web/dashboard/views.py` — allowlist match REMOTE_ADDR
- `src/ameli_web/request_id.py` — header en try + process_exception
- `src/ameli_web/settings.py` — HSTS default outside dev
- `src/ameli_app/cli.py` — `purge-inactive-users` subcommand
- `src/ameli_app/workers/maintenance.py` — sweep try/except
- `scripts/_common.sh` — `fail` con exit code opcional
- `scripts/backup.sh` — exit 2 propagado
- `.github/workflows/ci.yml` — `supply-chain-audit` job
- `requirements.txt` + `requirements-dev.txt` — `~=` pins
- Tests nuevos: `test_code_review_fixes_20260615.py` (+9),
  `test_hardening_20260615.py` (+14)
