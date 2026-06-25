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
