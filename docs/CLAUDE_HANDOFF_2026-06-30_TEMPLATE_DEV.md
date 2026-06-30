## AMELI App Template handoff (sesion Claude, 2026-06-30)

Fecha: `2026-06-30`
Agente: `claude-opus-4-6`
Rama de trabajo: `dev` (HEAD `1a0c33d` al abrir)
Rama estable: `main` (`4b36607`, sin tocar — 40 commits atras)
Sesion previa: [`CLAUDE_HANDOFF_2026-06-27_TEMPLATE_DEV.md`](CLAUDE_HANDOFF_2026-06-27_TEMPLATE_DEV.md)

> Nota: 28-29 jun no hubo sesion. Reanudamos desde el cierre del 27-jun.

## §1. Snapshot al inicio

### Estado del repo

- `dev @ 1a0c33d` (sync local == origin). Cierre del 27-jun:
  PC-1 steps 1-4 (services.py split — audit, throttle, sudo extraidos).
- `main @ 4b36607` (sync local == origin), **40 commits atras** de
  `dev`.
- Tests: **1033 unit pass** + 4 e2e collected (skip por default).
- Coverage: 85% (floor pinned).
- mypy: 0 errores en src.
- **ruff: 49 errores** — el handoff 27-jun declaraba "clean local"
  pero el PC-1 refactor dejo imports huerfanos y re-exports sin
  marcar como tales.
- Version: `v0.4.0-django`.
- ASVS L2: **151 PASS / 0 strict GAP**.

## §2. Objetivo de la sesion

1. Validar el handoff 27-jun contra el estado real del repo.
2. Corregir los 49 errores de ruff encontrados durante la validacion.

## §3. Trabajo realizado

### 3.1. Validacion del handoff 27-jun

Lectura del handoff + verificacion de claims contra el repo:

| Claim | Real | Veredicto |
|---|---|---|
| `services/__init__.py` = 2907 lineas | 2906 | OK (off-by-1) |
| `audit.py` = 462 lineas | 462 | OK |
| `throttle.py` = 495 lineas | 495 | OK |
| `sudo.py` = 214 lineas | 214 | OK |
| Total `services/` = 4078 | 4077 | OK |
| Unit tests 1033 pass | 1033 pass | OK |
| `main` 39 commits atras | 40 commits atras | MENOR |
| ruff / bandit: clean local | **49 errores ruff** | **INCORRECTO** |

### 3.2. Fix ruff lint — services/__init__.py

**Problema**: el PC-1 refactor (steps 2-4) movio funciones a
audit.py, throttle.py y sudo.py pero dejo en `__init__.py`:
- 3 imports huerfanos (`os`, `tempfile`, `gettext as _`) que ya
  solo se usaban en el codigo extraido.
- 39 re-exports sin marcar como re-exports explicitos — ruff los
  trata como F401 (imported but unused).
- 3 bloques de import mid-file (E402) y desordenados (I001) por
  estar junto a los comments de dominio.

**Solucion aplicada**:

1. Eliminados `import os`, `import tempfile`,
   `from django.utils.translation import gettext as _`.
2. Re-exports convertidos a alias redundante (`X as X`) — el patron
   que ruff reconoce como re-export intencional.
3. Bloques mid-file anotados con `# noqa: E402, I001` (ubicacion
   deliberada junto a sus domain comments).
4. Import block top-level reordenado con `ruff --fix --select I001`.

**Commit**: `64227b6` en branch `claude/compassionate-meitner-ds2fs4`.

**Verificacion post-fix**:
- ruff: **0 errores** (49 → 0)
- mypy: 0 errores
- pytest: **1033 pass** (sin cambio)

## §4. Decisiones tomadas

1. **Alias redundante (`X as X`) sobre `__all__`**. Ruff sugiere
   ambos; elegimos el alias porque es local a cada import statement
   y no requiere mantener una lista `__all__` separada que se
   desincronice cuando PC-1 steps 5+ extraigan mas modulos.

2. **`noqa: E402, I001` en re-export blocks**. Los 3 bloques de
   re-export estan intencionalmente mid-file (junto al domain comment
   que explica que se movio y cuando). Moverlos al top del archivo
   los alejaria de su contexto narrativo. Esto es deuda aceptada
   que desaparece cuando PC-1 complete la extraccion y __init__.py
   sea solo re-exports.

## §5. Metricas al cierre

| Indicador | Valor |
|---|---|
| Unit tests | **1033 pass** (sin cambio) |
| E2E tests | 4/4 (no tocado) |
| Coverage | 85% (floor pinned) |
| Ruff | **0 errores** (corregido hoy) |
| Mypy | 0 errores |
| Commits del dia | 1 (fix ruff lint) |
| Archivos tocados | 1 (`services/__init__.py`) |
| Delta | 42 insertions, 45 deletions |
| Branch | `claude/compassionate-meitner-ds2fs4` (pendiente merge a `dev`) |

## §6. Hallazgos / findings

### 6.1. El handoff 27-jun tenia un claim falso

"ruff / mypy / bandit: clean local" no era cierto para ruff. Los
49 errores existian desde PC-1 step 2 (`58d0061`). Probable causa:
la sesion del 27-jun no corrio `ruff check src/` despues de los
commits sino solo `pytest`. Leccion: correr el lint completo
despues de CADA commit de refactor, no solo los tests.

## §7. Roadmap actualizado

Sin cambios respecto al handoff 27-jun §7. El fix de hoy no
avanza ningun item del roadmap — solo corrige deuda del PC-1.

### Pendientes ordenados

| # | Item | Costo | Notas |
|---|---|---|---|
| Merge | `claude/compassionate-meitner-ds2fs4` → `dev` | 5 min | Fix ruff lint, 1 archivo |
| PC-1.5+ | Continuar split `services.py` — email_queue, mfa, user, session, password_reset, maintenance | 2-3h | Misma estrategia incremental |
| PC-2 | Split `views.py` (1267 lineas) | 2-3h | Despues de PC-1 cerrado |
| PC-3 | Split `admin_views.py` (745 lineas) | 1-2h | |
| PC-4 | Split `settings.py` en package | 1h | Mecanico |
| D-2 | UX MFA prompts (`window.prompt` → input inline) | 45 min | Polish |
| D-1 | Identidad visual del template | 6-8h | Solo si operador decide |
| D-4 | JS test framework (Jest/Vitest) | 2h | |
| Promote | `dev → main` v1.0 | — | Requiere PC-1 cerrado + instruccion explicita |

## §8. Continuidad — para el proximo agente

### 8.1. Estado snapshot al cierre

- Rama: `dev @ 1a0c33d`. Branch
  `claude/compassionate-meitner-ds2fs4 @ 64227b6` pendiente de
  merge (1 commit adelante de dev, fix ruff lint).
- `main @ 4b36607`, **40 commits atras**.
- Unit suite: **1033 pass**.
- ruff / mypy: **0 errores**.
- `services/` package: 4 modulos (`__init__`, `audit`, `throttle`,
  `sudo`).

### 8.2. Primer paso

Merge `claude/compassionate-meitner-ds2fs4` a `dev`, luego
continuar PC-1 desde step 5 (ver handoff 27-jun §8.2 para el
plan detallado de email_queue → mfa → user → session).

### 8.3. Que NO hacer

Mismas restricciones que handoff 27-jun §8.3 — siguen vigentes.
