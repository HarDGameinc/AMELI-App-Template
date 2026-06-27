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

(Pendiente al cierre del dia.)

## §4. Decisiones tomadas

(Pendiente al cierre del dia.)

## §5. Metricas al cierre

(Pendiente al cierre del dia.)

## §6. Hallazgos / findings

(Pendiente al cierre del dia.)

## §7. Roadmap actualizado

(Pendiente al cierre del dia.)

## §8. Continuidad — para el proximo agente

(Pendiente al cierre del dia.)
