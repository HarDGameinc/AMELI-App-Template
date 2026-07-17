## AMELI App Template handoff (sesion Claude, 2026-07-17)

Fecha: `2026-07-17`
Agente: `claude-opus-4-7`
Rama de trabajo: `dev` (version `v0.5.7-django`, HEAD `88700d3` al abrir)
Rama estable: `main` (en `v0.5.7-django`, `216a6e7`; al dia con `dev` menos 3
commits docs-only pendientes de promocion)
Sesion previa: [`CLAUDE_HANDOFF_2026-07-16_TEMPLATE_DEV.md`](CLAUDE_HANDOFF_2026-07-16_TEMPLATE_DEV.md)

> **Sesion en curso** — este handoff se completa durante el dia.

## §1. Snapshot al inicio

- `dev` == `origin/dev` (ahead 0, behind 0), **arbol limpio**. VERSION
  `v0.5.7-django`; `main` en `v0.5.7-django` (`216a6e7`, promovido ayer via
  PR #10).
- **3 commits en `dev` docs-only sin promover** desde v0.5.7: `9ab1202`
  (handoff 2026-07-16), `a5ccf3d` (DECISIONS #8), `88700d3` (correccion
  two-locks). Ninguno urge — la proxima promocion los recoge sola.
- **Entornos activos**: Windows nativo (loop diario, venv desde rangos → Django
  6.x local; suite 1126/58) **y WSL2 Ubuntu 24.04** (paridad Linux completa,
  venv desde ambos locks hash-pinneados → uvloop + django 5.2.16; suite
  **1156/28**, 30 tests mas que Windows).
- **CI verde** en el ultimo commit con codigo (v0.5.7, `216a6e7`).
- **Sin PRs abiertos.**
- **Server** (`ha-report2`): en `v0.5.6-django`, active. v0.5.7 no requiere
  redeploy (cero runtime prod); `/health` sube en el proximo `git pull` sin
  urgencia.

## §2. Objetivo de la sesion

Por definir con el operador — ver §7 del handoff de ayer.
