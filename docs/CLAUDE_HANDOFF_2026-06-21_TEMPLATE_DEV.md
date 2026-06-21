## AMELI App Template handoff (sesion Claude, 2026-06-21)

Fecha: `2026-06-21`
Agente: `claude-opus-4-7`
Rama de trabajo: `dev` (HEAD `<this-commit>` — commit del open)
Rama estable: `main` (sync `e9d1e24`, recien promovido del cierre 20-jun)
Sesion previa: [`CLAUDE_HANDOFF_2026-06-20_TEMPLATE_DEV.md`](CLAUDE_HANDOFF_2026-06-20_TEMPLATE_DEV.md)

## §1. Snapshot al inicio

- Estado del repo: `main == dev == e9d1e24` (sync absoluto al
  abrir).
- Tests: **943 passed** sin deselect. CI #117 verde sobre
  `676d6a2` (parent del handoff close).
- Coverage: 85% (floor pinned).
- mypy: 0 errores en 47 archivos src.
- Version: `v0.4.0-django` (deployed en `ha-report2` con todos
  los checks de `/health/deep` operativos tras el wire test del
  20-jun).
- ASVS L2: 151 PASS / 0 strict GAP.
- Mini-roadmap mejoras: 7/12 items shipped (Fase 1+2 closed,
  Fase 3 partial: #6 mypy done, #7 OpenTelemetry pendiente;
  Fases 4-6 abiertas).
- Frente abierto del 20-jun §8:
  - Promote `dev → main` post-cierre ← **DONE al abrir 21-jun**.
  - Re-install + wire test del avatar UI en `ha-report2`.

## §2. Objetivo de la sesion

Wire test del nuevo bundle deployado a `ha-report2`:
1. Re-correr `install.sh` con el fix `d4ade5e` (auto-restart
   de daemons running). Validar que el operador YA NO necesita
   restart manual post-upgrade.
2. Smoke del avatar UI: login → `/profile/` → upload imagen →
   verificar render → delete → vuelve a iniciales.
3. Smoke del dark mode (#3 de Phase 1) si no se valido aun
   visualmente.

Si el wire test queda verde, sesion cierra con el bundle del
20-jun confirmado en produccion. Si surge bug nuevo, fix in
template + re-deploy (patron del 20-jun PT-4).

## §3. Trabajo realizado

| Commit | Tema | Tests |
|---|---|---|
| `<this>` | Open 2026-06-21 handoff | suite stays green |

(Pendiente segun decisiones del operador post-wire-test.)

## §4. Decisiones tomadas

(Pendiente al cierre del dia.)

## §5. Metricas al cierre

(Pendiente al cierre del dia.)

## §6. Hallazgos / findings

(Pendiente al cierre del dia.)

## §7. Roadmap actualizado

Roadmap principal: **0 items abiertos**.

Mini-roadmap de mejoras (heredado del 2026-06-20 §7):

| Fase | Items | Status |
|---|---|---|
| 1. DX foundation | #1 pre-commit, #2 coverage, #3 a11y/dark | ✓ closed |
| 2. Validar deploy | #4 backup round-trip, #5 deep health | ✓ closed |
| 3. Types + tracing | #6 mypy, #7 OpenTelemetry | partial — #6 done |
| 4. Hardening | #8 SRI propios, #9 circuit breakers | open |
| 5. Performance | #10 django-silk, #11 pool tuning | open |
| 6. E2E | #12 Playwright | open |

Follow-ups documentados (sin shippear):
- config.py boot guard para paths relativos en `data_dir`.
- Patron "endpoint POST sin UI consumer" → checklist.

## §8. Continuidad — para el proximo agente

(Pendiente al cierre del dia.)
