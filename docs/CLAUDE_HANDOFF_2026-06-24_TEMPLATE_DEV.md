## AMELI App Template handoff (sesion Claude, 2026-06-24)

Fecha: `2026-06-24`
Agente: `claude-opus-4-7`
Rama de trabajo: `dev` (HEAD `502f123` al abrir)
Rama estable: `main` (`4b36607`, sin tocar — 7 commits atras de dev)
Sesion previa: [`CLAUDE_HANDOFF_2026-06-23_TEMPLATE_DEV.md`](CLAUDE_HANDOFF_2026-06-23_TEMPLATE_DEV.md)

## §1. Snapshot al inicio

- Estado del repo:
  - `dev @ 502f123` (sync local == origin).
  - `main @ 4b36607` (sync local == origin), 7 commits atras de
    `dev` post-milestone del 23-jun.
  - Convencion ratificada el 21-jun: server pullea SIEMPRE `dev`;
    `main` solo avanza por instruccion explicita "milestone".
- Tests: **1004 unit pass** + 4 e2e collected (skip por default).
- Coverage: 85% (floor pinned).
- mypy: 0 errores en 51 archivos src.
- ruff: clean local.
- bandit: clean local (Medium: 0 con el `# nosec` shipped ayer).
- Version: `v0.4.0-django`.
- Server `ha-report2`: corriendo `36c4329` (codigo del 22-jun),
  MFA email funcional, IPv6 disabled, dev deps NO instaladas.
- ASVS L2: 151 PASS + V12.4.1 strict + V10.3.x SRI + V14 TT.
- Mini-roadmap: **12/12 closed** (Fase 6 #12 Playwright cerrado
  el 23-jun shippeando suite + CI job).
- CI status: Lint+Test ✓, supply-chain ✓, **e2e job rojo** con
  2 bugs identificados de test-code (no de workflow), documentados
  en §8 del 23-jun.

### Commits pendientes en `dev` desde el ultimo match con `main`

| Bloque | Commits | Tema |
|---|---|---|
| Cierre 23-jun | `502f123`, `e08ec7c`, `bf711a2`, `fbfe3af`, `e235ebc` | docs y handoffs |
| Fase 6 #12 + CI fixes | `8cbebbe`, `5695c64`, `568ced1`, `3ae3d50` | e2e suite + 3 layers de CI |

Total: 7 commits ahead, sin code change runtime (e2e + workflow +
docs).

## §2. Objetivo de la sesion

Continuar pendientes del cierre del 23-jun:

1. **Bug A — Cross-thread DB invisibility en e2e_admin fixture**
   (afecta 3 tests con `TimeoutError`):
   - Fixture usa `db` (savepoint mode, no committed). `live_server`
     corre en otro thread y NO ve el user creado.
   - Fix: `tests/e2e/conftest.py:e2e_admin(db, ...)` →
     `e2e_admin(transactional_db, ...)`.
2. **Bug B — Assert message mismatch en
   `test_login_with_wrong_password_*`**:
   - Django renderiza "por favor, introduzca un nombre de usuario
     y clave correctos." — mis asserts buscan "credenciales/
     incorrect/invalid/no pudimos".
   - Fix: cambiar assert a `"introduzca un nombre" in body`.
3. **Verificar CI verde post-fix** — el job e2e debe pasar los
   4 tests. Si pasa, mini-roadmap wire-validated end-to-end.

Cosmetico opcional al cierre:
- Log line format del breaker (`%.0f` → `%.1f`).

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
