## AMELI App Template handoff (sesion Claude, 2026-06-25)

Fecha: `2026-06-25`
Agente: `claude-opus-4-7`
Rama de trabajo: `dev` (HEAD `3fef62b` al abrir)
Rama estable: `main` (`4b36607`, sin tocar — 22 commits atras)
Sesion previa: [`CLAUDE_HANDOFF_2026-06-24_TEMPLATE_DEV.md`](CLAUDE_HANDOFF_2026-06-24_TEMPLATE_DEV.md)

## §1. Snapshot al inicio

### Estado del repo

- `dev @ 3fef62b` (sync local == origin). Commit del dia trae: `.agents/`
  bundle de skills, `skills-lock.json`, `AGENTS.md` reescrito + 2 nuevos
  reviews docs (`docs/SKILLS_REVIEW.md`, `docs/FRONTEND_DESIGN_REVIEW.md`).
- `main @ 4b36607` (sync local == origin), 22 commits atras de `dev`
  post cierre del 24-jun.
- Convencion ratificada el 21-jun: server pullea SIEMPRE `dev`;
  `main` solo avanza por instruccion explicita "milestone".
- Tests: **1027 unit pass** (1004 base + 13 cookie-thief A1-A4 + 10
  phase-b B1-B7) + 4 e2e collected (skip por default).
- Coverage: 85% (floor pinned).
- mypy: 0 errores en 51 archivos src.
- ruff: clean local.
- bandit: clean local.
- Version: `v0.4.0-django`.
- Server `ha-report2`: corriendo `36c4329` (codigo del 22-jun) — 22
  commits atras del HEAD de dev. Los fixes del 24-jun (cookie-thief
  Bloque A + Bloque B) NO estan deployados todavia.
- ASVS L2: **151 PASS / 0 strict GAP** (`COMPLIANCE_ASVS_L2_2026-06-16.md`).
- Mini-roadmap: **12/12 wire-validated** (e2e 4/4 cerrado el 24-jun).

### Metricas de masa critica (post Bloque A+B)

| Archivo | Lineas | Notas |
|---|---|---|
| `src/ameli_web/accounts/services.py` | 3880 | +87 vs 24-jun (B-fixes) — 121 def/class. **God object**. |
| `src/ameli_web/accounts/views.py` | 1267 | +82 vs 24-jun (A-fixes + B5 interstitial) — 36 def/class |
| `src/ameli_web/admin_views.py` | 745 | sin cambio |
| `src/ameli_web/settings.py` | 746 | sin cambio |
| `src/ameli_web/templates/accounts/profile.html` | ~990 | +30 lineas inline JS por window.prompt() del A1/A2 |
| Inline JS profile.html | ~470 | crecio de 340 por A1/A2 |
| Inline JS admin/panel.html | ~650 | sin cambio |

### Nuevos artefactos del dia (commit `3fef62b`)

| Archivo | Proposito |
|---|---|
| `docs/SKILLS_REVIEW.md` | Audit cruzado por 7 skills (accessibility / bash / django / security / testing / sqlalchemy / seo). Findings P0-P3 con file:line evidence. |
| `docs/FRONTEND_DESIGN_REVIEW.md` | Critica visual + propuesta concreta de identidad (paleta navy+teal, DM Sans+IBM Plex, sparkline signature). |
| `.agents/skills/` | 10 skills locales (django-expert/patterns/security, sqlalchemy + alembic, python-testing-patterns, frontend-design, accessibility, bash-defensive-patterns, seo, find-skills, python-executor). |
| `skills-lock.json` | Lockfile de skills. |
| `AGENTS.md` reescrito | Estructura limpia: reading order, arquitectura, runtime, security model, CLI, testing, decisions, "state of the project" con deuda arquitectonica explicita. |

### Que NO esta en el repo al abrir

- Handoff de hoy 25-jun (lo abrimos en este push).
- Phase B item #2 (threat model gap analysis post-22-jun) — pending de ayer.
- Phase C (code review estructural services.py) — pending de ayer.
- Phase D (BUILDING_NEW_APP.md) — pending de ayer.
- Backup destructive restore wire test (opcional).
- UX polish del Bloque A (window.prompt → input inline) — opcional.

## §2. Objetivo de la sesion

Triagear los findings de los 2 nuevos reviews docs (SKILLS + FRONTEND)
contra el roadmap pendiente del 24-jun y ejecutar los quick wins que
no requieren decisiones del operador.

### Bloque inmediato — quick wins (esta sesion, ~30 min)

| # | Item | Origen | Costo |
|---|---|---|---|
| QW-1 | `Math.random` fallback en `app.js:54-59` debe negarse a generar si `crypto.getRandomValues` no esta — log warning + return falsy. | SKILLS §4 Security MEDIUM | 5 min |
| QW-2 | Anadir `<meta name="robots" content="noindex,nofollow">` a `base.html`. Template interno, no debe indexarse. | SKILLS §7 SEO recomendacion | 1 min |
| QW-3 | Decidir Alembic: `migrations/versions/` vacio. Opciones: (a) remover `alembic.ini` + `migrations/` + dep, (b) wire-up con un migration test inicial, (c) documentar como vestigial. | SKILLS §6 SQLAlchemy MEDIUM | 10-30 min (depende de la opcion) |
| QW-4 | Tests de regresion para QW-1 (JS) y QW-2 (template smoke). | follow-up | 10 min |

### Bloque siguiente — pivot pre-prod (post-quick wins)

| # | Item | Origen | Costo |
|---|---|---|---|
| PB-2 | Phase B item #2: threat model gap analysis post-22-jun (MFA stacked, OTel, silk, breakers) | Plan del 24-jun §7.1 | ~20 min |
| PC-1 | Phase C — split `services.py` por dominio (`services/user.py`, `services/mfa.py`, `services/email.py`, `services/audit.py`). HIGH en ambos reviews. | Plan 24-jun + SKILLS §3 HIGH | 3-4h |
| PC-2 | Phase C — split `views.py` por dominio. HIGH. | SKILLS §3 HIGH | 2-3h |
| PC-3 | Phase C — split `settings.py` en `settings/{base,prod,dev}.py`. Low. | SKILLS §3 LOW | 1h |
| PD-1 | Phase D — `BUILDING_NEW_APP.md`. Onboarding doc para apps hijas. | Plan 24-jun §7.1 | 30 min |

### Bloque decisorio — requiere visto bueno del operador

| # | Item | Origen | Decision necesaria |
|---|---|---|---|
| D-1 | Identidad visual del template (FRONTEND §9): implementar paleta navy+teal, type pairing DM Sans+IBM Plex, signature element (sparkline). | FRONTEND P0/P1 | ¿Template debe tener identidad propia (~6-8h trabajo de frontend) o quedarse neutro para que apps hijas pongan su brand (decision "by design")? |
| D-2 | UX MFA prompts: cambiar `window.prompt()` por input inline tipo `mfa_disable` (que ya esta bien). | Frontend agravado por A1/A2 | ¿Lo arreglamos en esta etapa o queda como deuda? ~45 min. |
| D-3 | Backup destructive restore wire test en CI nightly. | Plan 24-jun opcional | ¿Suma valor o esta cubierto con el verify? ~15 min. |
| D-4 | JS test framework (Jest o Vitest) para validar password generator, strength evaluator, debounce. | SKILLS §5 Testing MEDIUM | ¿Vale el setup overhead? ~2h setup + tests. |
| D-5 | Promover `dev → main` como milestone "v1.0 production-ready" cuando Phase C cierre. | Plan 24-jun | Instruccion explicita del operador. |

## §3. Trabajo realizado

### 3.1. Vestigial cleanup — barrido + decisiones

Barrido dirigido para identificar codigo / archivos / deps que nunca
se usaron. Hallazgos:

| Item | Diagnostico | Decision |
|---|---|---|
| `migrations/env.py` + `script.py.mako` + `alembic.ini` + dep `alembic>=1.13,<3` | 0 migrations generadas en toda la historia (`migrations/versions/` no existe). 1 commit `fc1611d` que solo cuela el env. 0 imports de `alembic` en src/. | **Remover** (commit #2) |
| `src/ameli_app/templates/dashboard.html` + `admin.html` | 0 referencias en src/ tests/ docs/. Solo aparecen en egg-info autogenerado. Pre-Django legacy. | **Remover** (este commit) |
| `src/ameli_app/database.py` + dep `SQLAlchemy>=2.0,<3` | Hace solo un `SELECT 1` (7 lineas utiles). 2 callers: `cli.py:db-status` + `dashboard/views.py:health`. Django ORM puede hacer lo mismo. | **Refactor a Django ORM** (commit #3) |
| `src/ameli_app/web.py` | 14 lineas, alternate uvicorn launcher (vs `api.py`). Apuntado por `systemd/ameli-app-web.service`. | **Mantener** + docstring que aclare es alias (este commit) |
| `src/ameli_app/workers/capture.py` | 17 lineas, placeholder que solo retorna `{"message": "Capture worker placeholder executed."}`. Apuntado por `systemd/ameli-app-capture@.service` (template con sufijo @). | **Mantener** + docstring que aclare es extension point para apps hijas (este commit) |
| `services.py:change_email_for_self` (B3 del 24-jun) | 0 callers en views. 4 tests en `test_profile_email.py` lo ejercitan como service unit. Ya tiene `current_password` gate (defensa-en-profundidad). | **Mantener as-is** — gate cierra el riesgo, tests pinean contrato. |

## §4. Decisiones tomadas

1. **SQLite: Opcion A — mantener como esta**.

   - Runtime: `settings.py:_database_settings()` sigue con fallback a
     SQLite si `DATABASE_URL` esta vacio.
   - CI: sigue corriendo 100% SQLite (`Lint+Test` + `E2E` jobs).
   - Backup/restore scripts: mantienen las 2 ramas (Postgres + SQLite).
   - Tests `test_backup_restore.py` mantiene el round-trip SQLite.
   - Docs `OPERATIONS.md` + `FIRST_INSTALL_DJANGO.md` ya lo documentan
     como "fallback local de conveniencia" — Postgres es official.

   **Riesgo aceptado**: hay drift semantico SQLite vs Postgres que el
   test suite no detecta (`select_for_update()` no-op en SQLite,
   JSON ops distintas, etc). CI verde con SQLite ≠ correcto en
   Postgres prod. Mitigacion: el deploy real corre Postgres y las
   features sensibles a engine (throttle counters, audit chain) son
   covered por integration tests con `transactional_db`.

   **Opciones rechazadas hoy**:
   - Opcion B (CI a Postgres con service container, SQLite queda
     local) — 45 min de trabajo, posible camino futuro.
   - Opcion C (Postgres only) — rompe onboarding cero-deps y demos
     rapidas. Solo si v1.0 explicito requiere "production engine en
     tests".

2. **Vestigial cleanup**: ver §3.1 — remover Alembic (sin uso real)
   + legacy templates (dead). Refactor SQLAlchemy → Django ORM en
   `database.py`. Mantener `web.py` + `capture.py` como extension
   points documentados.

3. **`change_email_for_self`**: confirmado el design del 24-jun B3
   — la funcion no tiene callers en views pero queda como service
   unit ejercitado por 4 tests + protected por `current_password`
   gate. No es dead code, es scaffolding seguro para futuro cableado.

### 3.2. Vestigial cleanup — serie de 4 commits

| # | Commit | Cambio |
|---|---|---|
| 1 | `6522daa` | Doc SQLite decision + remove `ameli_app/templates/{dashboard,admin}.html` + docstrings extension points (`ameli_app/web.py` + `workers/capture.py`) |
| 2 | `1793564` | Remove Alembic: `migrations/env.py` + `script.py.mako` + `alembic.ini` + dep en `requirements.txt` + `pyproject.toml` + `THIRD_PARTY_LICENSES.md` |
| 3 | `a9271f3` | Refactor `database.py` SQLAlchemy → Django ORM con `_ensure_django()` lazy bootstrap (mirror del patron en `workers/notify.py`) + remove SQLAlchemy dep |
| 4 | `406b413` | Regenerar `requirements.lock` via `pip-compile --generate-hashes` (0 refs a alembic/SQLAlchemy/Mako/greenlet en runtime; greenlet sigue en dev lock por playwright transitive — legitimo) |

### 3.3. Quick wins post-reviews (commit `07a7ca2`)

| QW | Cambio | Origen |
|---|---|---|
| 1 | `ameliRandomIndex` ya no usa `Math.random` fallback — throwea cuando `crypto.getRandomValues` no esta. `ameliGeneratePassword` catchea y retorna `""`. Click handler detecta y muestra error sin tocar inputs. | SKILLS_REVIEW §4 Security MEDIUM |
| 2 | `<meta name="robots" content="noindex,nofollow">` en `base.html`. Defense-in-depth para deploys accidentalmente expuestos a internet. | SKILLS_REVIEW §7 SEO |
| 4 | 6 regression tests en `test_phase_qw_hardening.py` (3 sobre `app.js` via static-analysis, 3 sobre robots meta via Django client). | follow-up |

### 3.4. Quick win extension docs (commit `6522daa`)

- `src/ameli_app/web.py` docstring aclara que es alias de
  `ameli_app.api`, mantenido por el systemd unit `ameli-app-web.service`
  para que apps hijas reasignen la implementacion.
- `src/ameli_app/workers/capture.py` docstring aclara que es
  placeholder intencional — scaffolding para que child apps
  reemplacen `run_once()` con su ingestion logic. Los systemd
  timers `ameli-app-capture-*.timer` vienen OFF por default.

## §4. Decisiones tomadas

1. **SQLite: Opcion A — mantener como esta**.

   - Runtime: `settings.py:_database_settings()` sigue con fallback a
     SQLite si `DATABASE_URL` esta vacio.
   - CI: sigue corriendo 100% SQLite (`Lint+Test` + `E2E` jobs).
   - Backup/restore scripts: mantienen las 2 ramas (Postgres + SQLite).
   - Tests `test_backup_restore.py` mantiene el round-trip SQLite.
   - Docs `OPERATIONS.md` + `FIRST_INSTALL_DJANGO.md` ya lo documentan
     como "fallback local de conveniencia" — Postgres es official.

   **Riesgo aceptado**: hay drift semantico SQLite vs Postgres que el
   test suite no detecta (`select_for_update()` no-op en SQLite,
   JSON ops distintas, etc). CI verde con SQLite ≠ correcto en
   Postgres prod. Mitigacion: el deploy real corre Postgres y las
   features sensibles a engine (throttle counters, audit chain) son
   covered por integration tests con `transactional_db`.

   **Opciones rechazadas hoy**:
   - Opcion B (CI a Postgres con service container, SQLite queda
     local) — 45 min de trabajo, posible camino futuro.
   - Opcion C (Postgres only) — rompe onboarding cero-deps y demos
     rapidas. Solo si v1.0 explicito requiere "production engine en
     tests".

2. **Vestigial cleanup**: ver §3.1 — remover Alembic (sin uso real)
   + legacy templates (dead). Refactor SQLAlchemy → Django ORM en
   `database.py`. Mantener `web.py` + `capture.py` como extension
   points documentados.

3. **`change_email_for_self`**: confirmado el design del 24-jun B3
   — la funcion no tiene callers en views pero queda como service
   unit ejercitado por 4 tests + protected por `current_password`
   gate. No es dead code, es scaffolding seguro para futuro cableado.

4. **`Math.random` rechazado a nivel duro**: el password generator
   no acepta degradar a PRNG aunque eso signifique no generar nada
   en navegadores sin `crypto.getRandomValues`. Trade-off: usuario
   en un navegador legacy ve un error en lugar de una clave debil.
   Preferimos error visible a credencial silenciosamente predecible.

## §5. Metricas al cierre

| Indicador | Valor |
|---|---|
| Unit tests | **1033 pass** (1027 base + 6 QW) |
| E2E tests | 4/4 pass (no tocado hoy) |
| Coverage | 85% (floor pinned) |
| Ruff | clean local |
| Mypy | 0 errores en 51 archivos src |
| Bandit | Medium: 0 |
| Commits del dia | 7 (`0c7ca9b`, `6522daa`, `1793564`, `a9271f3`, `406b413`, `07a7ca2`, + este cierre) |
| Lineas runtime tocadas | `database.py` rewrite + `app.js` generator + `base.html` meta tag |
| Lineas eliminadas | 367 (Alembic + legacy templates + SQLAlchemy en runtime lock) |
| Deps runtime removidas | 2 top-level (`alembic`, `SQLAlchemy`) + transitives (`Mako`, `MarkupSafe`, `greenlet`) |
| ASVS L2 | 151 PASS + V12.4.1 + V10.3.x + V14 (sin cambio) |
| CI Lint+Test | ✓ esperado |
| CI Supply-chain | ✓ esperado (lockfile regenerada con `--generate-hashes`) |
| CI E2E | ✓ esperado |
| Server `ha-report2` | sin cambio runtime relevante hoy — sigue en `36c4329` del 22-jun |

## §6. Hallazgos / findings

### 6.1. Mapping vestigial: lo claro vs lo sutil

El barrido del dia confirmo que la frontera "vestigial" no es
binaria. Los items se separan en 3 categorias:

1. **Vestigial duro** (removido): Alembic (0 migrations
   generated since first commit), legacy templates
   `ameli_app/templates/{dashboard,admin}.html` (0 referencias).
2. **"Casi-vestigial"** (refactor pero conservar funcionalidad):
   SQLAlchemy — usado para 1 funcion de 7 lineas (`database_status`).
   Reemplazado por Django ORM via bootstrap lazy. Mas barato a
   largo plazo, menos dep weight.
3. **Apariencia vestigial pero scaffolding intencional**:
   `ameli_app/web.py` (alias de api), `workers/capture.py`
   (placeholder para child apps), `change_email_for_self`
   (service unit con tests + password gate, sin callers en
   views todavia). Conservados con docstrings explicativos.

### 6.2. Lecciones de la serie de commits

- **Lockfile regen post-remove**: cuando se remueve una dep
  top-level, el lockfile la mantiene hasta regenerar. Aunque
  no rompe el install (sigue funcionando), es ineficiente y
  confunde un audit. El commit #4 del cleanup pin esto como
  practica.
- **Lazy Django bootstrap es el patron canonico para CLI hooks
  que tocan DB**: ya existia en `workers/notify._ensure_django`.
  Replicarlo en `database.py` mantiene un punto de bootstrap
  unificado para todos los entry-points fuera-de-manage.py.
- **Static analysis de JS funciona para invariants criticos**:
  los 3 tests de QW-1 leen `app.js` y verifican propiedades
  estructurales (no usa Math.random en password path, throwea
  en lugar de degradar, handler checkea el "" return). Cubre
  lo basico sin requerir Jest/Vitest setup. Si en una iteracion
  futura se quiere validar runtime, el path es a JS test
  framework (item D-4 del §2 abierto).

### 6.3. Riesgos abiertos NO mitigados hoy

- **SQLite vs Postgres drift en CI** — Opcion A explicitamente
  aceptada en §4. La trampa: `select_for_update()` no-op en
  SQLite significa que un test de race condition puede pasar
  en CI y fallar en prod. Mitigacion futura: Opcion B.
- **`ameli_app/web.py` y `api.py` son funcionalmente
  identicos**. Si en una iteracion futura se quiere collapsar a
  uno solo, hay que coordinar con el systemd template
  (`ameli-app-web.service` vs `ameli-app-api.service`) y con
  apps hijas que puedan estar overriding una de las dos.

## §7. Roadmap actualizado

- **Phase B Bloque A** (4 HIGHs) + **Bloque B** (7 MEDs) — closed
  el 24-jun. Pinned por `test_cookie_thief_hardening.py` y
  `test_phase_b_hardening.py`.
- **Phase B item #3 doc-drift** — closed el 24-jun (`0b0eb3b`).
- **Phase QW** (vestigial cleanup + quick wins) — closed hoy
  (7 commits del 25-jun). Pinned por `test_phase_qw_hardening.py`.

### Pendientes ordenados

| # | Item | Origen | Costo |
|---|---|---|---|
| PB-2 | Phase B item #2: threat model gap analysis post-22-jun (MFA stacked, OTel, silk, breakers no estan en `THREAT_MODEL.md` §3 T2) | Plan 24-jun §7.1 | ~20 min |
| PC-1 | Phase C — split `services.py` por dominio. **3880 lineas + 121 def/class** (subio de 3793 ayer por sudo throttle B1). | SKILLS_REVIEW §3 HIGH + plan 24-jun | 3-4h |
| PC-2 | Phase C — split `views.py` por dominio. **1267 lineas + 36 def/class**. | SKILLS_REVIEW §3 HIGH | 2-3h |
| PC-3 | Phase C — split `admin_views.py` por dominio. 745 lineas. | SKILLS_REVIEW §3 MEDIUM | 1-2h |
| PC-4 | Phase C — split `settings.py` en package. 746 lineas. | SKILLS_REVIEW §3 LOW | 1h |
| PD-1 | Phase D — `BUILDING_NEW_APP.md`. Onboarding doc para apps hijas. | Plan 24-jun §7.1 + reviews | 30 min |
| D-1 | Identidad visual del template (paleta navy+teal, type pairing, signature element). | FRONTEND_DESIGN_REVIEW §9 P0/P1 | 6-8h |
| D-2 | UX MFA prompts: `window.prompt()` → input inline tipo `mfa_disable`. | Frontend agravado por A1/A2 del 24-jun | ~45 min |
| D-4 | JS test framework (Jest o Vitest) para validar `ameliGeneratePassword` runtime. | SKILLS §5 Testing MEDIUM | ~2h |
| Promote | Promover `dev → main` como milestone "v1.0 production-ready" cuando Phase C cierre. | Plan 24-jun + reviews | Instruccion explicita del operador |

## §8. Continuidad — para el proximo agente

### 8.1. Estado snapshot al cierre

- Rama: `dev @ <commit-cierre>` (este push). `main @ 4b36607`
  intacto, 29 commits atras.
- Unit suite: **1033 pass local** (1027 base + 6 QW).
- E2E suite: 4/4 pass (sin tocar hoy).
- Server `ha-report2`: `36c4329` del 22-jun, 29 commits atras de
  `dev`. Cambios runtime hoy: `database.py` (refactor SQLAlchemy),
  `app.js` (password generator hardening), `base.html` (robots meta).
  Cambios deploy hoy: `requirements.lock` regenerada (sin alembic
  / SQLAlchemy). El proximo deploy DEBE incluir estos cambios para
  alinear el ASVS argument.
- ruff/mypy/bandit: clean local.

### 8.2. Pendientes ordenados por prioridad

**Bloque proximo — Phase B-D restantes** (foco del 26-jun en
adelante):

1. **PB-2 threat model gap analysis** (~20 min). Confirmar
   `THREAT_MODEL.md` §3 T2 cubre MFA stacked (TOTP+email),
   OTel exporter trust, django-silk activation accidental,
   circuit-breaker forced-open DoS. Si no estan, anadir
   S-11..S-14.
2. **PC-1 split `services.py`** (~3-4h). 3880 lineas, 121
   def/class. Foco: dividir por dominio (`services/user.py`,
   `services/mfa.py`, `services/email.py`, `services/audit.py`,
   `services/throttle.py`, `services/breaker.py`). Mantener
   API publica via `services/__init__.py` re-exports.
3. **PC-2 split `views.py`** (~2-3h). 1267 lineas. Mismo
   patron de dominio.
4. **PD-1 `BUILDING_NEW_APP.md`** (~30 min). Onboarding doc
   para apps hijas. Que renombrar / que mantener / que extender.
5. **D-2 UX MFA prompts** (~45 min) — opcional pero valioso si
   el operador planea demo del template proximamente.

### 8.3. Que NO hacer

- No promover `dev → main` sin instruccion explicita del operador.
- No revertir el `Math.random` removal — la decision fue explicita
  (preferir error visible a credencial debil silente, §4.4).
- No revertir el `noindex` meta — defense-in-depth bajo costo.
- No reintroducir alembic / SQLAlchemy sin justificacion clara
  (el cleanup pasa por 4 commits revertibles si surge la necesidad).
- No tocar `ameli_app/web.py` ni `workers/capture.py` sin
  considerar el contrato implicito que esperan las apps hijas —
  los docstrings nuevos pinean el porque.
- No splittear `services.py` "por capas" (utils / models / orm).
  El split debe ser por DOMINIO (auth / mfa / email / audit) para
  que las imports cross-domain sean explicitas.

### 8.4. Lectura sugerida antes de tocar la rama dev

**Para Phase B-D restantes**:
- `docs/PHASE_A_PREPROD_AUDIT_2026-06-24.md` (que esta revisado).
- `docs/PHASE_B_SECURITY_REVIEW_2026-06-24.md` (Bloques A+B cerrados).
- `docs/SKILLS_REVIEW.md` §3 Django Patterns (god objects).
- `docs/FRONTEND_DESIGN_REVIEW.md` §9 (visual identity propuesta).
- `docs/THREAT_MODEL.md` (input para PB-2).

**Para tocar auth / MFA / sessions**:
- `tests/test_cookie_thief_hardening.py` (invariantes A1-A4).
- `tests/test_phase_b_hardening.py` (invariantes B1-B7).
- `tests/test_phase_qw_hardening.py` (invariantes QW-1).

**Para tocar el sistema de deps**:
- `tests/test_lockfile_hashes.py` (contract pin).
- `docs/THIRD_PARTY_LICENSES.md` (manual file, regenerar
  con `pip-licenses` segun el comando documentado).
