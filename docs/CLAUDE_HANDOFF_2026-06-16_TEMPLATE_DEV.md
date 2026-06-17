## AMELI App Template handoff (sesion Claude, 2026-06-16)

Fecha: `2026-06-16`
Agente: `claude-opus-4-7`
Rama de trabajo: `dev` (HEAD `<this-commit>` — el commit del handoff mismo)
Rama estable: `main` (en `ecea971`; al dia)
Sesion previa: [`CLAUDE_HANDOFF_2026-06-15_TEMPLATE_DEV.md`](CLAUDE_HANDOFF_2026-06-15_TEMPLATE_DEV.md)

Primer handoff que sigue el formato canonico definido en
[`HANDOFF_TEMPLATE.md`](HANDOFF_TEMPLATE.md). Mantener este
contrato para todas las sesiones siguientes.

## §1. Snapshot al inicio

- Estado del repo: `dev` en `2bebf47` (handoff cierre de la sesion
  del 15-06). `main` en `644599b` — 65 commits atras.
- Tests: 693/693 green local. CI: rojo desde `0077fb0` (15-06) por
  causa no diagnosticada al arrancar la sesion.
- Frente abierto: promocion `dev` → `main` pendiente; el roadmap
  ASVS L2 del 15-06 dejo 16 items abiertos.

## §2. Objetivo de la sesion

Cerrar el ciclo de cambios pendiente: pip-audit del server, license
del template, smoke test en `ha-report2`, diagnostico y fix del CI
rojo, promocion `dev` → `main`, y handoff estandarizado para que
cualquier agente o developer pueda retomar.

## §3. Trabajo realizado

| Commit | Tema | Tests |
|---|---|---|
| `5383268` | declare MIT license + THIRD_PARTY_LICENSES.md | 693 green |
| `8dd5232` | relax dep pins (`~=` → `>=,<N+2`) tras CVEs detectados por pip-audit | 693 green |
| `ecea971` | fix ruff lint que bloqueaba CI desde `0077fb0` | 693 green |
| `<this>` | handoff 2026-06-16 + HANDOFF_TEMPLATE canonico | unchanged |

### `5383268` — License + atribuciones de terceros

- **Que**: agrega `LICENSE` (MIT, copyright HarDGame inc.), declara
  `license = "MIT"` + `license-files = ["LICENSE"]` + `authors` en
  `pyproject.toml`, y crea `docs/THIRD_PARTY_LICENSES.md` con mapping
  per-dep (Django BSD-3, Pillow MIT-CMU, psycopg LGPL-3.0+ con su
  nota de uso por API pública, pyotp MIT, python-dateutil Apache-2.0,
  PyYAML MIT, qrcode BSD-3, SQLAlchemy MIT, uvicorn BSD-3, alembic
  MIT, argon2-cffi MIT).
- **Por que**: el repo no declaraba licencia — bajo default copyright
  eso lee como "all rights reserved", lo opuesto de lo que necesita
  un template abierto. Cierra ASVS V1.1.1 colateral.
- **Decision**: MIT (max permisividad para reuso; ver §4).
- **Tests**: ninguno nuevo (cambio de metadata + docs).
- **Side effects**: pip / pip-audit / SBOM tooling ahora detectan
  la licencia automaticamente.

### `8dd5232` — Relax dep pins (CVE fix path)

- **Que**: cambia `requirements*.txt` de `~=X.Y` a `>=X.Y,<N+2` en
  todos los paquetes. Concretamente: `Pillow ~=11.0` → `Pillow >=11.3,<13`
  (cierra 5 CVEs + 1 PYSEC en 11.x), `pytest ~=8.0` → `pytest >=9.0,<11`
  (cierra CVE-2025-71176). El resto siguio la misma logica para que
  Dependabot pueda saltar dentro del rango cuando hay un security
  major.
- **Por que**: el sync del server con `~=` instalo Pillow 11.3 y
  pytest 8.4 (los caps del compatible-release); pip-audit detecto
  8 CVEs. El pin original me obligaba a un PR manual para cada
  security major, lo cual es lo opuesto a lo que la sesion del 15
  pretendia ("Dependabot puede shippear fixes").
- **Decision**: aceptamos que un major surpresa lleve PR cuando esta
  mas alla de N+2; los N+1 quedan en piloto automatico (ver §4).
- **Tests**: 693/693 sigue green con la dep matrix actualizada.
- **Side effects**: ninguno en código; el script de CI sigue corriendo
  pip-audit y ahora reporta "No known vulnerabilities found".

### `ecea971` — Fix ruff lint bloqueando CI

- **Que**: `tests/test_code_review_fixes_20260615.py:201` tenia
  `from datetime import datetime, timedelta` aunque solo usaba
  `timedelta` (F401), y el bloque de imports estaba desordenado
  (I001). `ruff check .` salia `exit 1` antes de pytest, abortando
  el job de CI desde `0077fb0` (15-06, 6 commits atras).
- **Por que**: el runbook local solo corria `pytest`, no `ruff check`.
  Los tests pasaban localmente pero CI moria en lint. **Esto es la
  raiz de por que casi todo el historial visible en GitHub Actions
  aparece rojo, no porque haya regresion funcional**.
- **Decision**: agregamos `ruff check .` al runbook pre-push (item
  #1 del roadmap §7) — proxima sesion arranca con ese hábito.
- **Tests**: 9/9 del archivo afectado siguen green; `ruff check .`
  reporta "All checks passed!" sobre todo el repo.
- **Side effects**: CI #13 verde en 2m 18s con los 3 jobs (Python
  3.11 + 3.12 + supply-chain audit).

### Promocion `dev` → `main`

- Fast-forward `644599b..ecea971` (80 commits, 122 archivos,
  +14,857 / −2,791 lineas). Sin conflictos, sin divergencia (0
  commits en `main` que no esten en `dev`).
- Verificado post-push: `main == origin/main` en `ecea971`.

### Server smoke test en `ha-report2`

Bloques 1–4 verde, bloque 5 con OPS gap del deploy (ver §6).
Detalles en §8a.

## §4. Decisiones tomadas

- **Licencia del template = MIT**. Trade-off aceptado: max
  permisividad para que cualquier deploy commercial / interno
  pueda agarrarlo sin friccion legal. Apache-2.0 quedo descartada
  por la cláusula de patentes (over-kill para este scope); AGPL
  descartada por copyleft fuerte (no es modelo open-core).
- **Pinning strategy `>=X.Y,<N+2`**. Trade-off aceptado: Dependabot
  puede shippear security majors (Pillow 11→12) sin PR, pero un
  truly-new generation (Django 7, Pillow 13, pytest 11) sigue
  requiriendo aprobacion. Lockfile con hashes via `pip-compile`
  queda como roadmap item #14.
- **LGPL de psycopg NO se contagia**. Documentado en
  `docs/THIRD_PARTY_LICENSES.md`: el template solo usa la API
  publica de psycopg, lo cual no activa la clausula copyleft de
  LGPL-3.0. Operadores que forkeen psycopg deben respetar LGPL en
  ese fork; el template sigue MIT.
- **Backup OPS gap no bloquea promocion**. El script
  `scripts/backup.sh` esta validado (LOW A2 cerrado, exit-2
  contract honrado en wire). El hecho de que en `ha-report2` no
  haya timer + PG solo escucha socket Unix es deploy ops, no
  template. Sigue como item #2 del roadmap.
- **CI ruff regresion = miss del runbook, no bug**. El fix de
  `ecea971` es de 2 lineas; la falla real fue no correr
  `ruff check .` antes de pushear. Habito incorporado al
  template (S-07 skill + checklist S-08).
- **Promocion via fast-forward directo, no PR**. El usuario
  autorizo explicitamente en chat. La proxima vez que activemos
  branch protection en GitHub, esto va a forzar un PR (apuntado
  como item #15 del roadmap).

## §5. Metricas al cierre

- Tests: 693 → 693 (unchanged; el fix de lint no toco logica)
- ASVS L2 score: 90.6% PASS de las 149 rows activas (re-evaluado en
  `docs/COMPLIANCE_ASVS_L2_2026-06-16.md` con metodologia row-counted
  consistente). Subio respecto al 15-06 por los 8 controles cerrados
  en `42efbd4` (V1.1.1, V1.1.2, V1.5.x, V1.6.1, V6.3.x, V8.2.1,
  V8.3.3, V8.3.4, V9.1.2, V14.4.5) + 2 partials (V14.2.1, V14.2.2).
  14 GAPs strict pendientes (= items #1..#15 menos las dobles del
  roadmap), todos sin severidad HIGH.
- Open code-review findings: 0 HIGH / 0 MEDIUM / 0 LOW de las sesiones
  del 15-16. El backup OPS gap esta etiquetado OPS en §6, no
  code-review.
- CI status del HEAD: **green** en `ecea971` (run #13, 2m 18s, 3
  jobs green, 3 warnings de Node-20 deprecation).
- Migration count delta: +0
- Dep changes:
  - **Major upgrade** (security): Pillow 11 → 12.2 (Tras el `>=11.3,<13`
    pin)
  - **Major upgrade** (security): pytest 8.4 → 9.1 (tras el `>=9.0,<11` pin)
  - **New dev dep**: pip-audit `>=2.7,<4`
  - **New runtime dep** (PM session): cryptography `>=48.0.1,<50`
    (closes 6 CVEs in 45.x, backs Fernet for ASVS V2.8).
  - Resto: unchanged.
- License declared: MIT (era: undefined).

## §5b. Wire validation 2026-06-16 PM (items #1 + #2)

Despues del cierre formal del 2026-06-16 AM, la sesion del PM cerro
los items #1 y #2 del roadmap end-to-end con smoke test en
`ha-report2` (HEAD `8d9ab91`).

### Items cerrados

| # | ASVS | Commits | Tests | Wire evidence |
|---|---|---|---|---|
| 1 | V2.8.1-2.8.6 (TOTP encrypt at rest) | `1523904` + `6ab443a` | +14 (`tests/test_mfa_secret_encryption.py`) | admin's `mfa_secret` re-encrypted in DB (db_len=140, fernet_shape=True), runtime decrypts back to 32-char base32 |
| 2 | V2.2.3 (auth-failures alert) | `56e7046` | +11 (`tests/test_auth_failures_alert.py`) | 5 fails on `tester` user fired exactly one `auth_failures_alert_sent` audit row + email delivered to real inbox (carlos.urbina@agnov.cl) |
| 3 | V3.3.3 (absolute session ceiling) | `f6e7232` | +8 (`tests/test_session_absolute_ceiling.py`) | 18 sessions of `tester` backdated 31 days → next GET /profile/ returned 302 → /login/ + `session_expired_absolute` audit with `session_age_seconds=2678400, max_age_seconds=2592000` |
| 4 | V4.2.1 (avatar IDOR closed) | `c39d750` | +7 (`tests/test_media_auth_gate.py`) | 4 wire paths confirmed: owner GET 200, superadmin GET 200, ephemeral other-user GET 403 + `media_access_denied` audit (target=tester, actor=smoke-other-#4, reason=not_owner), malformed → 404 |
| 5 | V10.3.x (OpenAPI SRI policy) | `148518b` | +12 (`tests/test_openapi_sri_policy.py`) | 4 endpoint paths confirmed (dev no-SRI → 200, prod no-SRI → 503 with operator-actionable body, prod opt-out → 200, prod with hashes → 200 with 3× `integrity=`) + `tools/sri_compute.py` ran successfully from server and emitted verified sha384 digests for swagger-ui-dist@5.20.0 + redoc@2.1.5 |
| 6 | V10.1.1 + V5.2.8 (SAST hard-fail in CI) | `c72b40e` | suite stays green | ruff `check .` with S ruleset + bandit `-r src/ -ll -ii` both clean on the server (ha-report2): "All checks passed!" + "Medium: 0 / High: 0" with 3 issues skipped via `# nosec` rationale. Service restart + /health verde post-deploy |
| — | Runbook + migration hardening | `8d9ab91` | suite stays green | bash env-loader IFS bug fixed in HANDOFF_2026-06-16 §8c; migration 0012 now raises with operator-actionable message when key is unparseable |

### Lecciones operacionales aprendidas

1. **Bash `IFS='='` come trailing `=`**. El runbook del 2026-06-16 AM
   shippeo un snippet de carga de env que perdia silenciosamente el
   `=` final de valores como las Fernet keys (44 chars -> 43 chars).
   Fix en `8d9ab91`: usar `IFS= read -r line` + `${line%%=*}` /
   `${line#*=}`. Cualquier sesion futura que use el handoff template
   ya no tropieza con esto.
2. **`pip-audit` lower bound debe ir contra current CVE-clean
   floor**. La primera pin de `cryptography>=43,<46` (commit `1523904`)
   pinneo el lower bound al rango que el unit test estaba ejecutando,
   no al rango CVE-libre. Resultado: CI red en `supply-chain-audit`
   por 6 CVEs en `cryptography 45.x`. Fix en `6ab443a`: bumpear
   lower bound al primer release CVE-clean (`48.0.1`). Esta lesson
   se incorpora al S-08 checklist para la proxima vez.
3. **Cuando una key se "pega en el chat" para diagnostico**, hay que
   tratarla como comprometida para el environment de produccion.
   Para `dev` aceptable (la conversation no se publica, el deploy
   es interno); cuando promovamos a prod hay que generar key NUEVA
   y NO copiarla al chat.

### Estado tras el cierre PM (post-#2; mantenido como snapshot intermedio)

- `main == dev == 8d9ab91`
- Suite: **718/718 green**, ruff clean, pip-audit clean
- CI: ultimos 4 runs (`#21..#24`) todos green
- ASVS L2: **137/149 PASS = 91.9%**, **12 strict GAPs restantes**, **0 HIGH**
- Server `ha-report2`: HEAD `8d9ab91`, migraciones 0012 + 0013
  aplicadas, MFA encryption key configurada (entorno dev), `tester`
  user recibio email de prueba del ASVS V2.2.3 trigger.

### Estado FINAL al cierre del 2026-06-16 (post-#6)

La sesion siguio mucho mas alla del snapshot intermedio anterior.
Items #3 a #6 se cerraron tambien dentro del mismo dia con la
misma disciplina (closed-and-wire-verified + CI-verified).

- `main == dev == 846fd5d`
- Suite: **745/745 green** (+27 sobre el snapshot intermedio); ruff
  con S-ruleset clean; bandit `-ll -ii` Medium 0 / High 0 (3 issues
  skipped via `# nosec`); pip-audit clean.
- CI: ultimos 12 runs (`#33..#44`) todos verde — 6 commits
  funcionales + 6 wire-evidence commits.
- ASVS L2: **142/149 active PASS = 95.3%** (era 91.9%). **7 strict
  GAPs restantes** (era 12). **0 HIGH** severidad.
- Capitulos completos al bar L2: **V2, V3, V4, V5 (1 GAP remaining),
  V10** (capitulo V10 entero PASS, cero gaps cero deferred).
- Server `ha-report2`: HEAD `846fd5d`, migraciones aplicadas, MFA key
  configurada, todos los smoke tests verdes (admin TOTP encrypted +
  decrypted, tester recibio el email del auth-failures alert,
  session-ceiling cierra a los 31 dias, avatar IDOR bloqueado +
  audit, OpenAPI SRI 4 paths confirmados + helper script corrio
  exitosamente desde el server).

### Items cerrados en el dia (6 roadmap + 2 ASVS controls en #6)

| # | ASVS | Functional commit | Wire-evidence commit | Tests Δ |
|---|---|---|---|---|
| 1 | V2.8.1-2.8.6 | `1523904` + `6ab443a` | `d35e6a0` | +14 |
| 2 | V2.2.3 | `56e7046` | `d35e6a0` | +11 |
| 3 | V3.3.3 | `f6e7232` | `82edebd` | +8 |
| 4 | V4.2.1 | `c39d750` | `6e4fc48` | +7 |
| 5 | V10.3.x | `148518b` | `b6e0cfc` | +12 |
| 6 | V10.1.1 + V5.2.8 | `c72b40e` | `846fd5d` | suite-only |
| — | infra hardening | `8d9ab91` | — | — |

Trabajo total del dia: **6 items cerrados, 7 ASVS controls
promovidos a PASS, 52 tests nuevos, 19 commits a `main`**.

### Lecciones nuevas (post-#3) que cierran disciplinas para el futuro

4. **Cuando un sub-agente devuelve un nombre de campo erroneo**,
   confiar pero verificar. La sesion del item #1 uso un Explore
   agent que reporto `totp_enabled` pero el campo real era
   `mfa_enabled` — los tests fallaron en el primer run hasta que
   abrimos el `models.py` manualmente. Lesson: cuando spawneamos
   un Explore, los nombres de identificadores criticos (fields,
   funciones) que el sub-agente reporta hay que verificarlos en
   el archivo real ANTES de redactar codigo que los referencia.
5. **Fail-closed por default es preferible a "shippear hashes
   inverificables"**. Cuando el sandbox de la sesion no pudo
   descargar los bundles del CDN para computar los SRI hashes,
   la tentacion era shippear hashes "tentativos". La decision
   correcta (item #5) fue fail-closed outside dev + helper
   script para que el operator genere los hashes localmente. El
   wire test confirmo que el server SI tiene egress al CDN y el
   helper corrio limpio — la decision es robusta en ambos casos.
6. **Los annotations de bandit y ruff son diferentes**. Bandit
   usa `# nosec BXXX`, ruff usa `# noqa: SXXX`. Para silenciar
   ambos engines en una linea: `# noqa: SXXX  # nosec BXXX` (los
   dos en orden). Esto va al S-07 del playbook como sub-pattern
   cuando hagamos un nuevo bandit/ruff lift.
7. **`cycle_key()` resetea el ceiling absoluto y eso esta bien**.
   Cada cycle_key site en el codebase esta gateado por una
   re-autenticacion fresca (MFA, sudo). Resetear el ceiling ahi
   es consistente con ASVS V3.3.3 ("max session lifetime without
   re-authentication"). Pinneado por
   `test_ceiling_anchor_is_per_user_session_row` para que un
   futuro intento de "preservar anchor original" se cazasse en
   code review.

### Carry-over al 2026-06-17

Items pendientes del roadmap (numeracion estable):

| # | Gap | Effort | Status |
|---|---|---|---|
| 7 | **12.4.1** AV scan opcional sobre avatares | M | open |
| 8 | **7.4.1** custom handler404 / handler500 | S | open |
| 9 | **1.4.4** authz centralizada en `accounts/permissions.py` | M | open |
| 10 | **13.2.2** contract test OpenAPI vs realidad | S | open |
| 11 | **5.5.1** boot-guard contra `MESSAGE_STORAGE` no-JSON | S | open |
| 12 | **3.4.4** cookie prefix `__Host-` por default | S | open |
| 13 | **7.1.1** `RedactingFilter` para PII en logs | S | open |
| 14 | **14.2.3** lockfile con hashes (`pip-compile --generate-hashes`) | M | open |
| 15 | **14.2.2** promover `pip-audit` a hard-fail (drop `continue-on-error`) | XS | open |
| 16 | Doc drift en handoffs viejos (webhooks/tokens removidos) | S | open |
| 17 | `ruff check .` en runbook pre-push | XS | **closed-2026-06-16** |
| 18 | Instalar `backup.timer` en `ha-report2` | S | open (ops) |
| 19 | PG TCP listener en `ha-report2` o user con rol PG | S | open (ops) |
| 20 | `manage.py` auto-loadea `APP_CONFIG` | S | open (code) |
| 21 | Bump `actions/checkout@v5+`, `setup-python@v6+` cuando Node-24 release | XS | open (hygiene) |
| 22 | Promover `supply-chain-audit` a hard-fail | XS | open |
| 23 | Branch protection en `main` (require PR + CI green) | S | open (gh) |

Orden recomendado para el 17:

1. Arrancar fresco con el handoff `CLAUDE_HANDOFF_2026-06-17`
   leyendo en orden: `AGENTS.md` → `HANDOFF_TEMPLATE.md` → este
   handoff → SECURITY.md → COMPLIANCE_ASVS_L2_2026-06-16.md
   (todos en el repo).
2. Recargar el env del server con el snippet corregido (S-04 + el
   IFS-fix del 2026-06-16).
3. Confirmar `main == dev == 846fd5d`, suite verde, CI verde.
4. Frente recomendado: arrancar con #15 (XS, ya hay baseline limpio
   de `pip-audit`) + #21 (XS) + #22 (XS) en un solo commit para
   cerrar los XS hygiene de un saque. Despues #8 (S handler404),
   #11 (S boot guard), #12 (S `__Host-` cookie), #13 (S PII
   redact). Despues los M reales (#7 AV scan, #9 authz, #14
   lockfile-hashes).

### Comandos utiles para arrancar el 17

Sync del server al ultimo HEAD:

```bash
cd /opt/ameli-app-template-dev
git fetch origin dev && git reset --hard origin/dev
git rev-parse HEAD   # esperado: 846fd5d (o posterior)
.venv/bin/pip install -r requirements.txt -r requirements-dev.txt
systemctl restart ameli-app-template-dev-api.service
```

Cargar env (IFS-fix obligatorio para que el `=` final de Fernet keys
no se coma):

```bash
set -a
while IFS= read -r line; do
    case "$line" in ''|'#'*) continue ;; esac
    key="${line%%=*}"; value="${line#*=}"
    [[ -z "$key" ]] && continue
    declare "$key=$value"
done < /etc/ameli-app-template-dev/app.env
set +a
export APP_CONFIG=/etc/ameli-app-template-dev/app.yaml
export DJANGO_SETTINGS_MODULE=ameli_web.settings
```

Smoke baseline (S-04 abreviado):

```bash
.venv/bin/python -m ruff check .          # All checks passed!
.venv/bin/python -m bandit -r src/ -ll -ii # Medium 0 / High 0
.venv/bin/pip-audit -r requirements.txt -r requirements-dev.txt
curl -s http://10.100.100.16:18080/health | python3 -c "import sys,json; d=json.load(sys.stdin); print(d['ok'], d['checks']['audit_chain']['detail']['match'])"
```

## §6. Hallazgos / findings

Findings que NO son bugs de esta sesion pero estan vivos en el
sistema.

- **OPS-01 (HIGH)** — `ameli-app-template-dev-backup.timer` no
  existe en `ha-report2`. La sesion del 13 dejo el script
  (`scripts/backup.sh`) pero el deploy no instalo el unit + timer
  de systemd. **Owner**: ops. **Donde**: `/etc/systemd/system/`
  del deploy. **Impacto**: nunca corrio un backup en producción de
  ese box; el manifest.sha256 + el rotativo no existen.
- **OPS-02 (HIGH)** — PostgreSQL en `ha-report2` solo escucha el
  socket Unix, y el rol `root` no existe en PG. Cuando se corre
  `backup.sh` como root manualmente, peer auth falla con "no
  existe el rol root". **Owner**: ops. **Fix**: o (a) configurar
  el timer para correr como user `ameli-app-template-dev` (que
  si tiene rol PG via password en `app.env`), o (b) habilitar
  `listen_addresses = 'localhost'` en PG y usar el DATABASE_URL
  TCP del `app.env`.
- **OPS-03 (MEDIUM)** — `manage.py migrate --check` y `python -m
  django` fallan cuando se corren fuera de systemd porque no
  cargan automaticamente el `APP_CONFIG=/etc/.../app.yaml`. El
  CLI `ameli-app` si lo hace bien (`config-check`, `verify-audit`,
  etc. funcionan sin tunear env). **Owner**: code. **Fix
  propuesto**: en `manage.py`, hacer un auto-load de `APP_CONFIG`
  via `ameli_app.config.load_settings()` si la env var esta
  configurada, antes de `execute_from_command_line()`.
- **CODE-01 (LOW)** — CSP `style-src` sigue con `'unsafe-inline'`
  pese a que el docstring de `build_csp()` dice que se reemplaza
  con nonce. Es decision de diseño (Permissions-Policy + CSP
  script-src nonce ya bloquean ejecución JS; inline style solo
  afecta layout). Si se cierra: hay que rewriting todos los
  `style=""` inline en templates. **Owner**: code. **Donde**:
  `src/ameli_web/accounts/middleware.py:35`.
- **HYGIENE-01 (LOW)** — Workflows de GitHub Actions usan
  `actions/checkout@v4` + `actions/setup-python@v5` (Node-20).
  GitHub deprecation: forzado a Node-24 desde 16-sep-2026. **Owner**:
  ops. **Fix**: bump cuando releaseen v5/v6 con Node-24.
- **HYGIENE-02 (LOW)** — `pip-audit` job en CI todavia tiene
  `continue-on-error: true`. Pensado como baseline soft; ahora que
  esta limpio (Pillow + pytest cerrados), se puede promover a hard
  fail. **Owner**: code. **Donde**: `.github/workflows/ci.yml`.

`[CLOSED]` Findings cerrados en esta sesion:

- `[CLOSED]` Lint regression en `test_code_review_fixes_20260615.py:201`.
  Fix: `ecea971`.
- `[CLOSED]` 8 CVEs en Pillow + pytest. Fix: `8dd5232`.
- `[CLOSED]` License undefined. Fix: `5383268`.

## §7. Roadmap actualizado

Numeracion estable; los items #1–#16 de la sesion del 15-06 se
preservan. Items nuevos arrancan en #17.

| # | Item | Effort | Status |
|---|---|---|---|
| 1 | TOTP secret encrypt at rest (Fernet) | M | open |
| 2 | Email alert al user en N consecutive auth failures | S | open |
| 3 | Absolute session ceiling | S | open |
| 4 | `/media/` owner-only (no solo auth-only) | S | open |
| 5 | SRI hashes para CDN o vendor swagger/redoc | S | open |
| 6 | bandit + ruff S310 hard fail en CI | S | open |
| 7 | AV scan opcional sobre avatares | M | open |
| 8 | handler404 / handler500 personalizados | S | open |
| 9 | Authz centralizada en `accounts/permissions.py` | M | open |
| 10 | Contract test OpenAPI doc vs realidad | S | open |
| 11 | Boot-guard que refusa `MESSAGE_STORAGE` no-JSON | S | open |
| 12 | `__Host-ameli_session` cookie name por default | S | open |
| 13 | `RedactingFilter` en logs para scrub PII | S | open |
| 14 | Lockfile con hashes (`pip-compile --generate-hashes`) | M | open |
| 15 | Promote `pip-audit` a hard fail en CI | S | open |
| 16 | Doc drift cleanup en handoffs viejos (webhooks/tokens removidos) | S | open |
| 17 | **NUEVO** Agregar `ruff check .` al runbook pre-push local | XS | closed-2026-06-16 (regla incorporada al S-07 + S-08; pendiente: persistirlo en pre-commit hook) |
| 18 | **NUEVO** Instalar `backup.timer` + service en `ha-report2` | S | open (OPS-01) |
| 19 | **NUEVO** Habilitar `listen_addresses` TCP en PG de `ha-report2` o cambiar el timer a user con rol PG | S | open (OPS-02) |
| 20 | **NUEVO** `manage.py` auto-loadea `APP_CONFIG` | S | open (OPS-03) |
| 21 | **NUEVO** Bump `actions/checkout@v4` → `v5+`, `setup-python@v5` → `v6+` cuando GitHub release Node-24 | XS | open (HYGIENE-01) |
| 22 | **NUEVO** Promover `supply-chain-audit` job a hard-fail | XS | open (HYGIENE-02) |
| 23 | **NUEVO** Habilitar branch protection en GitHub para `main` (require PR + CI green) | S | open |

## §8. Continuidad — para el proximo agente

### 8a. Estado del servidor `ha-report2`

- HEAD del deploy: `ecea971` (smoke test del 2026-06-16, blocks 1–4
  green; block 5 OPS gap, ver OPS-01 y OPS-02).
- DB: PostgreSQL local (socket Unix). `audit_chain.tail_id = 591,
  match = true` segun `/health`.
- Servicio systemd: `ameli-app-template-dev-api.service` activo
  desde 09:44 hora local (jun 16).
- Timers activos: `worker.timer` (cada ~5 min), `maintenance.timer`
  (cada 24h), `notifier-worker.timer`. **NO HAY** `backup.timer`.
- `pip-audit` clean. `ruff check .` clean. 693/693 green.
- Cache-Control: no-store + CSP nonce + request-id sanitization +
  cross-origin headers — todos validados via Django test Client +
  curl en wire para anonymous.

### 8b. Orden recomendado para retomar

1. **Si el frente es ops** (lo mas urgente segun el roadmap): cerrar
   OPS-01 + OPS-02 + OPS-03 en ese orden. Items #18, #19, #20.
2. **Si el frente es compliance** (ASVS): retomar el roadmap por
   los Smalls: #2 (email alert auth-fail) → #3 (session ceiling) →
   #4 (media owner-only) → #8 (handler404/500) → #11 (MESSAGE_STORAGE
   guard) → #12 (`__Host-` cookie) → #13 (PII redact filter). ~1 dia
   los 7 juntos.
3. **Si el frente es supply chain hardening**: #14 (lockfile con
   hashes), #15 / #22 (promover pip-audit a hard fail), #23 (branch
   protection).
4. **Si hay un security frente nuevo del usuario**: correr S-01 +
   S-02 sobre `main..HEAD` ANTES de tocar codigo. Documentar
   findings en §6 del nuevo handoff.

### 8c. Comandos utiles

Sync local + server al HEAD de `dev`:

```bash
# Local (Windows / WSL / Linux)
git fetch origin --prune
git checkout dev
git reset --hard origin/dev

# Server ha-report2
cd /opt/ameli-app-template-dev
git fetch origin && git reset --hard origin/dev
.venv/bin/pip install -r requirements.txt -r requirements-dev.txt
systemctl restart ameli-app-template-dev-api.service
```

Cargar el env del systemd en una shell para correr `python` directo.
**IMPORTANTE**: la version anterior de este snippet usaba
``IFS='='`` + ``read key value`` lo cual COME el trailing ``=`` de
valores como las Fernet keys (descubierto el 2026-06-16 wire-testing
item #1). La version correcta lee la linea entera y parte por el
primer ``=`` con expansion de parametros:

```bash
set -a
while IFS= read -r line; do
    case "$line" in ''|'#'*) continue ;; esac
    key="${line%%=*}"
    value="${line#*=}"
    [[ -z "$key" ]] && continue
    declare "$key=$value"
done < /etc/ameli-app-template-dev/app.env
set +a
export APP_CONFIG=/etc/ameli-app-template-dev/app.yaml
export DJANGO_SETTINGS_MODULE=ameli_web.settings
```

Validar middleware con Client autenticado (bypaseando MFA):

```bash
.venv/bin/python <<'PY'
import sys; sys.path.insert(0, '/opt/ameli-app-template-dev/src')
import django; django.setup()
from django.test import Client
from django.contrib.auth import get_user_model
u = get_user_model().objects.filter(role='superadmin').first()
c = Client(); c.force_login(u)
r = c.get('/profile/')
print(f"GET /profile/ -> {r.status_code}")
for k in ['Cache-Control', 'Permissions-Policy', 'Cross-Origin-Opener-Policy',
          'Cross-Origin-Resource-Policy', 'X-Request-Id', 'Content-Security-Policy']:
    print(f"  {k}: {r.headers.get(k, '<<MISSING>>')[:80]}")
PY
```

Pre-promotion checklist (S-08 del playbook):

```bash
cd /home/user/AMELI-App-Template       # o tu clone
DATABASE_URL= AMELI_APP_SECRET_KEY=test-secret-key-not-for-production-xxxxxxxxxxxxxxx \
    AMELI_APP_ALLOWED_HOSTS='*' AMELI_APP_TRUSTED_PROXIES='127.0.0.1,::1' \
    .venv/bin/pytest -q
.venv/bin/python -m ruff check .
.venv/bin/python -m pip-audit -r requirements.txt -r requirements-dev.txt
```

Promocion `dev` → `main` (S-05 del playbook):

```bash
git fetch origin --prune
git checkout main
git reset --hard origin/main
git merge --ff-only origin/dev
git push origin main
[[ "$(git rev-parse main)" == "$(git rev-parse origin/main)" ]] && echo "OK"
```

Diagnostico de CI rojo (S-07 del playbook):

```bash
# Via gh-MCP en una sesion Claude:
mcp__github__get_job_logs(
    owner="HarDGameinc", repo="AMELI-App-Template",
    run_id=<RUN_ID>, failed_only=true,
    return_content=true, tail_lines=120)
```

## §9. Archivos clave de la sesion

- `docs/HANDOFF_TEMPLATE.md` — **NUEVO**. Esqueleto canonico + skills
  playbook S-01 a S-08. Lectura obligatoria para la proxima sesion.
- `docs/CLAUDE_HANDOFF_2026-06-16_TEMPLATE_DEV.md` — este archivo.
- `LICENSE` — **NUEVO**. MIT, copyright HarDGame inc. 2026.
- `docs/THIRD_PARTY_LICENSES.md` — **NUEVO**. Atribucion per-dep +
  LGPL note + Apache NOTICE aggregation + compatibility matrix.
- `pyproject.toml` — `license = "MIT"`, `license-files = ["LICENSE"]`,
  `authors`.
- `requirements.txt` + `requirements-dev.txt` — pin strategy `>=X.Y,<N+2`.
- `.github/workflows/ci.yml` — job `supply-chain-audit` con `pip-audit
  --strict`.
- `tests/test_code_review_fixes_20260615.py:201` — import block
  re-ordenado (regla I001 + F401).
