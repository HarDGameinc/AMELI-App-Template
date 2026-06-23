## AMELI App Template handoff (sesion Claude, 2026-06-23)

Fecha: `2026-06-23`
Agente: `claude-opus-4-7`
Rama de trabajo: `dev` (HEAD `0c9b4c8` al abrir)
Rama estable: `main` (`1355060`, sin tocar — 21 commits atras de dev)
Sesion previa: [`CLAUDE_HANDOFF_2026-06-22_TEMPLATE_DEV.md`](CLAUDE_HANDOFF_2026-06-22_TEMPLATE_DEV.md)

## §1. Snapshot al inicio

- Estado del repo:
  - `dev @ 0c9b4c8` (sync local == origin).
  - `main @ 1355060` (sync local == origin), **21 commits atras** de
    `dev` (la sesion 22-jun cerro Fases 3 + 4 + 5 del mini-roadmap y
    sumo el follow-up del `unix://` AV scheme).
  - Convencion ratificada el 21-jun: server pullea SIEMPRE `dev`;
    `main` solo avanza por instruccion explicita "milestone" del
    operador.
- Tests: **1004 passed** sin deselect.
- Coverage: 85% (floor pinned).
- mypy: 0 errores en 51 archivos src (+1 `telemetry`, +1 `sri` tag,
  +1 `circuit_breaker` desde el inicio de la semana).
- Version: `v0.4.0-django` (deployed en `ha-report2 @ 36c4329` post
  wire test del bundle #11 + #10).
- ASVS L2: 151 PASS + V12.4.1 strict-shipped (clamav unix://) +
  V10.3.x SRI propios + V14 Trusted Types.
- Mini-roadmap: **11/12 closed**.
  - Fases 1 (DX), 2 (deploy), 3 (types+OTel), 4 (hardening),
    5 (performance) — todas closed.
  - Solo queda **#12 Playwright e2e** (Fase 6).

### Commits pendientes en `dev` desde el ultimo match con `main`

| Bloque | Commits | Tema |
|---|---|---|
| Avatar polish (21+22 jun) | `d70bff6`..`d279c24` | Convencion branches + dashboard/admin hero `has_avatar` + ring polish + size bump |
| Cierre 21-jun + open 22-jun | `c643af8`, `08e2583` | docs |
| Fase 4 — #8 SRI + TT | `2db09cb`, `afa083d` | Trusted Types CSP + SRI sobre propios |
| Fase 4 — #9 breakers | `39d3243` | Circuit breakers AV/HIBP/SMTP |
| Doc + 22-jun primer cierre | `1a2ea7f`, `3885252` | docs |
| Fase 4 — AV `unix://` | `a51d2b8`, `9c16b2d` | unix:// scheme + wire test |
| Fase 3 — #7 OTel | `8de62d1`, `cb8e67b`, `0bf9bca`, `1fe35d8`, `68bca6a` | OTel bootstrap + ASGI wrap + boot logging + wire test parte B |
| Fase 5 — #11 pool | `ca2a81f` | CONN_MAX_AGE + health checks + opt-in pool |
| Fase 5 — #10 silk | `36c4329` | Opt-in profiler con prod boot guard |
| Cierre 22-jun | `cc9636f`, `0c9b4c8` | docs |

### Estado del servidor `ha-report2`

- Corriendo `36c4329`.
- `AMELI_APP_OTEL_EXPORTER_OTLP_ENDPOINT`: **NO seteada** (OTel dormant, rollback post wire test parte B).
- `AMELI_APP_AV_ENDPOINT=unix:///var/run/clamav/clamd.ctl` (clamav activo).
- `AMELI_APP_SILK_ENABLED`: **NO seteada** (silk dormant post wire test). Tablas `silk_*` quedan vacias en DB (no graban porque silk salio de INSTALLED_APPS).
- `AMELI_APP_DB_CONN_MAX_AGE_SECONDS=0` ← residuo del test del rollback path. **Vale la pena confirmar con operador si lo mantiene o lo quita** para volver al default 60s. Mientras este seteado, pool tuning #11 esta efectivamente OFF (per-request connections, comportamiento Django original).

## §2. Objetivo de la sesion

(Pendiente — esperando direccion del operador.)

Items abiertos como candidatos:

1. **Limpieza residual del wire test 22-jun**:
   - Quitar `AMELI_APP_DB_CONN_MAX_AGE_SECONDS=0` del app.env para
     restaurar el default 60s del #11.
   - (Opcional) Drop de tablas `silk_*` si no se va a re-activar:
     re-enable temporal + `migrate silk zero` + disable.
2. **#12 Playwright e2e** (Fase 6, ultimo item del mini-roadmap).
   Cerraria el roadmap entero. Toca CI + agrega Node deps + un
   driver headless. Mas pesado que #10/#11.
3. **Promote `dev → main`** si el operador declara "milestone" para
   el bloque grande del 21-22 jun (Fases 3+4+5 closed). 21 commits
   ahead de main. Trigger explicito requerido.
4. **Cosmetic follow-ups** registrados en 22-jun §7:
   - Format del log line del breaker (`%.0f` → `%.1f` para cooldowns
     visibles en testing).

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
