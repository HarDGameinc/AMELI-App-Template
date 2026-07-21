## AMELI App Template handoff (sesion Claude, 2026-07-21)

Fecha: `2026-07-21`
Agente: `claude-opus-4-7`
Rama de trabajo: `dev` (version `v0.5.9-django`, HEAD `dfac623` al abrir)
Rama estable: `main` (en `v0.5.9-django`, `98f32a5`; al dia con `dev`
menos 2 commits docs-only pendientes de promocion)
Sesion previa: [`CLAUDE_HANDOFF_2026-07-17_TEMPLATE_DEV.md`](CLAUDE_HANDOFF_2026-07-17_TEMPLATE_DEV.md)

> **Sesion en curso** — este handoff se completa durante el dia.

## §1. Snapshot al inicio

- `dev` == `origin/dev` (0/0), **arbol limpio**. `main` promovido a
  **v0.5.9-django** el 2026-07-17 (`98f32a5`); `dev` en `dfac623`, 2
  commits docs-only adelante (`932db99` fix duplicado CHANGELOG + `dfac623`
  cierre honesto §3.3 del handoff previo).
- **Entorno canonico operativo = WSL2 Ubuntu 24.04** (per DECISIONS #9) en
  `/home/hardg/ameli-app-template`, suite **1156/28**. Clone Windows en
  `C:\Users\hardg\AMELI APPS\AMELI_APP_TEMPLATE` esta en sync pero
  **tratado como archivado** — no editar ahi.
- **PR #13 abierto** (Dependabot, 2026-07-20): `chore(ci): Bump actions/
  setup-python from 6 to 7`. `MERGEABLE`/`CLEAN`, esperando review.
- **Server** (`ha-report2`): en **v0.5.6-django**, active. v0.5.7/8/9 son
  docs/Docker-path y **no requieren redeploy**; `/health` sube en el
  proximo `git pull` sin urgencia.
- **CI verde** en el ultimo release (`98f32a5`).

## §2. Objetivo de la sesion

Por definir.

## §3. Trabajo realizado

(a completar durante la sesion)
