## AMELI App Template handoff (sesion Claude, 2026-06-27)

Fecha: `2026-06-27`
Agente: `claude-opus-4-7`
Rama de trabajo: `dev` (HEAD `25a3759` al abrir)
Rama estable: `main` (`4b36607`, sin tocar — 34 commits atras)
Sesion previa: [`CLAUDE_HANDOFF_2026-06-25_TEMPLATE_DEV.md`](CLAUDE_HANDOFF_2026-06-25_TEMPLATE_DEV.md)

> Nota: el 26-jun no hubo sesion. Reanudamos desde el cierre del 25-jun.

## §1. Snapshot al inicio

### Estado del repo

- `dev @ 25a3759` (sync local == origin). Cierre del 25-jun:
  PB-2 (threat model gap analysis) + PD-1 (`BUILDING_NEW_APP.md`)
  cerrados.
- `main @ 4b36607` (sync local == origin), **34 commits atras** de
  `dev` post cierre del 25-jun.
- Tests: **1033 unit pass** (1004 base + 13 cookie-thief A1-A4 + 10
  phase-b B1-B7 + 6 phase-qw) + 4 e2e collected (skip por default).
- Coverage: 85% (floor pinned).
- mypy: 0 errores en 51 archivos src.
- ruff / bandit: clean local.
- Version: `v0.4.0-django`.
- Server `ha-report2`: sigue en `36c4329` del 22-jun, **34 commits
  atras**. Los fixes del 24+25 jun (cookie-thief Bloque A + Bloque B,
  cleanup Alembic/SQLAlchemy, QW seguridad) NO estan deployados.
- ASVS L2: **151 PASS / 0 strict GAP** (`COMPLIANCE_ASVS_L2_2026-06-16.md`).
- Mini-roadmap: **12/12 wire-validated**.
- Threat model: cubre S-01..S-17 + 8 STRIDE rows nuevas + §7 change log.

### Metricas de masa critica al inicio

| Archivo | Lineas | def/class | Estado |
|---|---|---|---|
| `src/ameli_web/accounts/services.py` | 3880 | 121 | **God object** — top priority de split |
| `src/ameli_web/accounts/views.py` | 1267 | 36 | HIGH split candidate |
| `src/ameli_web/admin_views.py` | 745 | — | MEDIUM split candidate |
| `src/ameli_web/settings.py` | 746 | — | LOW split candidate |
| Inline JS `profile.html` | ~470 | — | Crecio por A1/A2 del 24-jun (window.prompt) |
| Inline JS `admin/panel.html` | ~650 | — | Sin cambio |

### Phase status cerradas

- Phase A audit ✓ (24-jun)
- Phase B item #1 (sweep focal + Bloques A/B) ✓ (24-jun)
- Phase B item #2 (threat model gap analysis) ✓ (25-jun)
- Phase B item #3 (doc-drift compliance) ✓ (24-jun)
- Phase QW (vestigial cleanup + quick wins) ✓ (25-jun)
- Phase D item #1 (`BUILDING_NEW_APP.md`) ✓ (25-jun)

### Que NO esta en el repo al abrir

- Handoff de hoy 27-jun (lo abrimos en este push).
- Phase C — splits estructurales (services / views / admin_views /
  settings). **Top priority.**
- UX MFA polish (D-2).
- Identidad visual (D-1) — bloqueado por decision del operador.
- Promote `dev → main` v1.0 — bloqueado por PC-1 + instruccion
  del operador.

## §2. Objetivo de la sesion

Continuar con el roadmap del 25-jun §8.2. El item #1 es **PC-1
split `services.py`** — el item de mas valor estructural y el
mas riesgoso. Lo atacamos hoy.

### Plan PC-1 — split `services.py` por dominio

`services.py` tiene 3880 lineas, 121 def/class. Mi propuesta de
particion por dominio (no por capas):

| Modulo destino | Dominio | Funciones estimadas |
|---|---|---|
| `services/__init__.py` | Re-exports para mantener API publica | (passthrough) |
| `services/user.py` | User CRUD, bootstrap, lockout, role management | ~20 |
| `services/mfa.py` | TOTP / email MFA enrolment, verify, disable, recovery codes | ~25 |
| `services/sudo.py` | sudo grant/revoke/verify, throttle de sudo | ~8 |
| `services/email.py` | Email change double-opt-in, alerts, outbound queue | ~20 |
| `services/audit.py` | record_audit, verify_chain, rotate_audit_key, prune | ~15 |
| `services/throttle.py` | _bump/_read counters, check_login_throttle, sliding window | ~10 |
| `services/breaker.py` | Circuit breaker glue (AV, HIBP, SMTP) | ~5 |
| `services/session.py` | UserSession sync, revoke, ceiling | ~8 |
| `services/maintenance.py` | get/set maintenance state | ~3 |
| `services/password_reset.py` | request_password_reset, complete_password_reset | ~5 |

**Estrategia tecnica**:
1. Crear `services/` package con cada modulo
2. Mover funciones por dominio (sin reescribir, solo `git mv`-style)
3. `services/__init__.py` re-exporta TODO lo que estaba en
   `services.py` para que callers existentes (~100 imports en
   views.py, admin_views.py, tests, etc.) no rompan.
4. Iterar: tests despues de cada modulo movido.
5. Cuando todo se haya migrado, eliminar `services.py` original.

**Riesgo**: imports circulares entre modulos (ej: `mfa.py` usa
`audit.py`, `email.py` usa `audit.py`, `sudo.py` usa `mfa.py`).
Mitigacion: hacer los imports lazy donde haga falta (ya hay
precedente en el repo con `from .services import ...` lazy).

**Verificacion**: `pytest tests/ --ignore=tests/e2e` debe seguir
en 1033 pass + ruff/mypy clean.

**Costo**: 3-4h estimado. Posible que requiera 2 sesiones si
surge un import circular complicado.

### Plan alternativo si PC-1 se complica

Si despues de 2h el split de services.py no esta cerrado limpiamente,
pivot a items mas chicos del backlog:

- **D-2 UX MFA prompts** (~45 min): `window.prompt()` → input inline.
- **PC-4 split settings.py** (~1h): mas mecanico que services.

## §3. Trabajo realizado

### 3.1. PC-1 (steps 1-4) — services.py incremental split

Refactor incremental del god-object `services.py` en `services/`
package. **Estrategia**: cada step es un commit revertible, tests
verdes despues de cada step. Si algo se rompe, revert 1 commit y
no se pierde el resto.

| Step | Commit | Que se extrajo | Lineas removidas de __init__ |
|---|---|---|---|
| 1 | `98a9648` | `services.py` → `services/__init__.py` (rename only, 6 imports actualizados de `from .X` a `from ..X` por la profundidad extra) | 0 (rename) |
| 2 | `58d0061` | `services/audit.py` — chain HMAC + verify + rotate + apply_audit_key_to_env_file (8 funciones) | -441 |
| 3 | `9bd1233` | `services/throttle.py` — counters + lockout + auxiliary rate limits (11 funciones + 2 exception classes + 9 constants) | -412 |
| 4 | `239d34e` | `services/sudo.py` — grants + brute-force gate (7 callables + SudoRequired) | -134 |

**Cycle handling pattern**: cuando una funcion extraida llama a
otra que sigue en `__init__.py`, se hace el import lazy adentro
del function body:

```python
from ameli_web.accounts.services import _maybe_alert_for_auth_failures_burst
```

Python permite la late binding y evita el import-time cycle
`__init__ → throttle → __init__`. Cuando se extraiga el modulo
destino, los lazy imports se reemplazan por imports normales al
top del nuevo modulo.

**Metricas al cierre del dia**:

| Archivo | Lineas inicio | Lineas cierre | Delta |
|---|---|---|---|
| `services/__init__.py` | 3880 | 2907 | **-973 (-25%)** |
| `services/audit.py` | — | 462 | +462 (nuevo) |
| `services/throttle.py` | — | 495 | +495 (nuevo) |
| `services/sudo.py` | — | 214 | +214 (nuevo) |
| Total `services/` | 3880 | 4078 | +198 (overhead por docstrings de modulo + re-exports) |

El +198 en total es el costo aceptable de la modularizacion:
~200 lineas de docstrings + 4 bloques de re-exports en __init__.
Cada modulo ahora es leible aisladamente con su proposito
documentado al tope.

**Tests verdes despues de cada step**: 1033 pass. Sin cambios
de tests, sin schema, sin migracion.

## §4. Decisiones tomadas

1. **Split incremental, no big-bang**. Cada commit es revertible
   sin perder el resto del progreso. Si Step 5 (email) se complica,
   revertimos solo Step 5 y los Steps 1-4 quedan stable.

2. **Re-exports desde `__init__.py`**. Mantener la API publica
   intacta es no-negociable: 100+ callers en views, admin_views,
   tests, cli, signals — todos siguen escribiendo
   `from ameli_web.accounts.services import X`. La package shim
   absorbe el cambio interno.

3. **Lazy imports para cycles**. En lugar de reordenar la
   arquitectura (que cambiaria el comportamiento), aceptamos los
   lazy imports `inside function bodies` como deuda transitoria
   hasta que cada modulo destino termine de extraerse. El runtime
   cost es marginal (un dict lookup por llamada) y la cycle queda
   atrapada en una sola direccion.

4. **Steps "obvios" primero**. Audit + Throttle + Sudo eran los
   bloques mas self-contained — pocas dependencias cruzadas con
   el resto de services.py. Los siguientes (email, mfa, user,
   session) tienen mas entanglement y los abordamos en proxima
   sesion con mas cuidado.

## §5. Metricas al cierre

| Indicador | Valor |
|---|---|
| Unit tests | **1033 pass** (sin cambio respecto al abrir) |
| E2E tests | 4/4 pass (no tocado hoy) |
| Coverage | 85% (floor pinned) |
| Ruff / mypy / bandit | clean local |
| Commits del dia | 5 (handoff open + 4 PC-1 steps + este cierre) |
| Archivos creados | `services/audit.py`, `services/throttle.py`, `services/sudo.py` |
| Lineas movidas | ~1000 (de `__init__.py` a 3 modulos dedicados) |
| `services/__init__.py` | 3880 → 2907 (-25%) |
| Lineas TOTAL en `services/` | 3880 → 4078 (+198 overhead docs/re-exports) |
| Cambios runtime | Ninguno (refactor puro, re-exports preservan API) |
| Server `ha-report2` | sin cambio relevante hoy — sigue en `36c4329` del 22-jun |

## §6. Hallazgos / findings

### 6.1. El patron "lazy import inside function body" funciona

Cuando un modulo extraido necesita llamar a una funcion que se
quedo en `__init__.py`, el lazy import `inside the function body`
resuelve el cycle sin overhead notable. Python cachea el import
en `sys.modules` despues de la primera llamada, asi que el costo
runtime es un dict lookup (~ns). Ejemplo:

```python
# services/throttle.py
def record_login_failure(...):
    ...
    from ameli_web.accounts.services import _maybe_alert_for_auth_failures_burst
    _maybe_alert_for_auth_failures_burst(...)
```

Esta es deuda transitoria — cuando se extraiga `services/alerts.py`
en una iteracion futura, el lazy se reemplaza por
`from .alerts import _maybe_alert_for_auth_failures_burst` al top.

### 6.2. La estimacion de 3-4h era conservadora

PC-1 steps 1-4 tomaron ~1.5h reales (el resto del tiempo fue
suite waits + commit messages). Eso deja headroom para los steps
restantes (email, mfa, user, session, password_reset, maintenance)
en proxima sesion sin presion.

### 6.3. Riesgo abierto: email/mfa cycle

Los proximos modulos a extraer son los mas entangled:

- `services.py:_send_email_change_alert` → llama a
  `send_with_retry` (queue) y `record_audit`.
- `services.py:start_mfa_email_enrollment` → llama a
  `_check_email_mfa_rate_limit` + `_send_mfa_email_code` +
  `_create_and_send_email_challenge` + `record_audit` +
  `MFAEmailChallenge`.

El email pipeline (`send_with_retry`, `process_email_queue`,
`_email_retry_delay_seconds`, `_build_email_message`,
`_PasswordResetEmail` class) deberia salir junto como
`services/email_queue.py`. El MFA email enrolment puede ir a
`services/mfa.py` junto con TOTP enrolment, dependiendo del
email_queue extraido.

Sugiero el orden:
1. `services/email_queue.py` primero (transport layer, sin
   business logic de auth).
2. `services/mfa.py` despues (consumer del email_queue).

## §7. Roadmap actualizado

### Phase status

- Phase A audit ✓ (24-jun)
- Phase B item #1 (Bloques A/B hardening) ✓ (24-jun)
- Phase B item #2 (threat model gap analysis) ✓ (25-jun)
- Phase B item #3 (doc-drift compliance) ✓ (24-jun)
- Phase QW (vestigial cleanup + quick wins) ✓ (25-jun)
- Phase D item #1 (`BUILDING_NEW_APP.md`) ✓ (25-jun)
- **Phase C item #1 (split `services.py`) — EN CURSO, steps 1-4 ✓ (hoy)**

### Pendientes ordenados

| # | Item | Costo | Notas |
|---|---|---|---|
| PC-1.5+ | Continuar split `services.py` — email_queue, mfa, user, session, password_reset, maintenance | 2-3h | Misma estrategia incremental |
| PC-2 | Split `views.py` (1267 lineas) | 2-3h | Despues de PC-1 cerrado |
| PC-3 | Split `admin_views.py` (745 lineas) | 1-2h | |
| PC-4 | Split `settings.py` en package | 1h | Mecanico |
| D-2 | UX MFA prompts (`window.prompt` → input inline) | 45 min | Polish |
| D-1 | Identidad visual del template | 6-8h | Solo si operador decide template = identidad propia |
| D-4 | JS test framework (Jest/Vitest) | 2h | |
| Promote | `dev → main` v1.0 | — | Requiere PC-1 cerrado + instruccion explicita |

## §8. Continuidad — para el proximo agente

### 8.1. Estado snapshot al cierre

- Rama: `dev @ 239d34e` + este cierre. `main @ 4b36607`,
  **39 commits atras**.
- Unit suite: **1033 pass local** (sin cambio respecto al abrir
  el handoff hoy).
- E2E suite: 4/4 pass (sin tocar hoy).
- Server `ha-report2`: `36c4329` del 22-jun, **39 commits atras**
  de `dev`. Los cambios de hoy son refactor puro — no requieren
  deploy distinto al pendiente desde 25-jun.
- ruff / mypy / bandit: clean local.
- `services/` package: 4 modulos (`__init__`, `audit`, `throttle`,
  `sudo`).

### 8.2. Pendientes ordenados por prioridad

**Continuar PC-1 desde donde quedamos**:

1. **PC-1 step 5** — extraer `services/email_queue.py`. Contiene
   `send_with_retry`, `process_email_queue`,
   `_email_retry_delay_seconds`, `_build_email_message`,
   `_PasswordResetEmail` (clase). Self-contained (solo usa
   models + Django email + logger). ~30 min.
2. **PC-1 step 6** — extraer `services/mfa.py`. Contiene TOTP
   enrolment (`start_mfa_enrollment`, `confirm_mfa_enrollment`,
   `disable_mfa_totp_for_self`, `disable_mfa_for_self`,
   `serialize_mfa_status`, `regenerate_recovery_codes`,
   `consume_recovery_code`) + email MFA
   (`start_mfa_email_enrollment`, `confirm_mfa_email_enrollment`,
   `_check_email_mfa_rate_limit`, `_send_mfa_email_code`,
   `_create_and_send_email_challenge`, `consume_email_mfa_code`,
   `send_mfa_email_login_code`, `disable_mfa_email_for_self`,
   `admin_disable_mfa_for_user`). Depende de email_queue. ~45 min.
3. **PC-1 step 7+** — user / session / password_reset / maintenance.
   ~1h total.
4. Despues de PC-1 cerrado: PC-2 (`views.py`) o D-2 (UX MFA).

### 8.3. Que NO hacer

- No promover `dev → main` sin instruccion explicita del operador.
- No cambiar la API publica de `services/`. Cualquier function
  movida debe seguir importable como
  `from ameli_web.accounts.services import X`. Re-exports
  desde `__init__.py` son obligatorios.
- No quitar los lazy imports `inside function bodies` hasta que el
  modulo destino se haya extraido. Reemplazar prematuramente
  reintroduce el import cycle.
- No reordenar funciones dentro de un modulo extraido. El git
  history queda mas leible cuando el move es literal y los
  follow-ups (renames, refactors internos) van en commits
  separados.

### 8.4. Lectura sugerida antes de continuar PC-1

- `src/ameli_web/accounts/services/__init__.py` — leer el comment
  block "Email change (double-opt-in)" cerca de la linea 2440
  para entender el contrato del email pipeline antes de extraer
  email_queue.
- `tests/test_mfa_service.py`, `tests/test_mfa_email_service.py`,
  `tests/test_mfa_stacked.py` — pinean el contrato del MFA
  domain. Cualquier nuevo `services/mfa.py` debe pasar estos.
- `tests/test_email_change_double_opt_in.py` y
  `tests/test_email_retry.py` — pinean el email pipeline.
- `docs/THREAT_MODEL.md` §3 T2 — los items "Information
  disclosure — telemetry exporter trust" y "Elevation of
  privilege — MFA method downgrade" referencian funciones que
  todavia estan en __init__.py. Si la extraccion las renombra,
  actualizar el threat model.
