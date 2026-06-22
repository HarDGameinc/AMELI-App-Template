## AMELI App Template handoff (sesion Claude, 2026-06-22)

Fecha: `2026-06-22`
Agente: `claude-opus-4-7`
Rama de trabajo: `dev` (HEAD `c643af8` al abrir)
Rama estable: `main` (`1355060`, sin tocar — 8 commits atras de dev)
Sesion previa: [`CLAUDE_HANDOFF_2026-06-21_TEMPLATE_DEV.md`](CLAUDE_HANDOFF_2026-06-21_TEMPLATE_DEV.md)

## §1. Snapshot al inicio

- Estado del repo:
  - `dev @ c643af8` (sync local == origin).
  - `main @ 1355060` (sync local == origin), 8 commits atras de `dev`.
  - Sin promote pendiente: convencion ratificada el 21-jun es
    server pullea `dev`, `main` avanza solo por instruccion
    explicita "milestone" del operador.
- Tests: **948 passed** sin deselect.
- Coverage: 85% (floor pinned).
- mypy: 0 errores en 47 archivos src.
- Version: `v0.4.0-django` (deployed en `ha-report2 @ f76af65`,
  ultimo commit con cambio de codigo; los siguientes son doc-only).
- ASVS L2: 151 PASS / 0 strict GAP.
- Mini-roadmap mejoras: 7/12 items shipped (Fase 1+2 closed,
  Fase 3 partial: #6 mypy done, #7 OpenTelemetry pendiente;
  Fases 4-6 abiertas).
- Frente abierto del 21-jun §8:
  - Promote `dev → main` cuando operador diga "milestone".
  - Continuar mini-roadmap (5/12 items) si hay direccion.
  - Patrones operacionales ratificados (server pulls dev only,
    auto-prompts ≠ instruccion, etc.) — incorporados al playbook.

### Commits pendientes en `dev` desde el ultimo match con `main`

| Commit | Tema |
|---|---|
| `d70bff6` | Convencion de branches documentada en §2 del 21-jun |
| `32dc83f` | Cierre wire test 21-jun + journal review |
| `af6b185` | Hero dashboard + admin panel honran `has_avatar` |
| `9c800a9` | Drop ring + gradient backdrop del hero cuando hay imagen |
| `6ac13fc` | Sibling: drop ring del chip top-right |
| `f76af65` | Hero avatar 72→96px + radius 24→28 |
| `d279c24` | §3 del 21-jun amplificado con polish del 22-jun |
| `c643af8` | Cierre §4-§8 del handoff 21-jun |

## §2. Objetivo de la sesion

(Pendiente — esperando direccion del operador.)

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
