## AMELI App Template handoff (sesion Claude, 2026-07-15)

Fecha: `2026-07-15`
Agente: `claude-opus-4-8`
Rama de trabajo: `dev` (version `v0.5.5-django`)
Rama estable: `main` (en `v0.5.5-django`)
Sesion previa: [`CLAUDE_HANDOFF_2026-07-14_TEMPLATE_DEV.md`](CLAUDE_HANDOFF_2026-07-14_TEMPLATE_DEV.md)

## §1. Snapshot al inicio

- `dev` == `origin/dev` (ahead 0, behind 0), **arbol limpio**. VERSION
  `v0.5.5-django`; `main` tambien en `v0.5.5-django` (`b7d0172`).
- **3 commits en `dev` sin promover**, todos **docs/CLI/CI** (sin cambio de
  runtime de la app): `cd7c0f4` bump de actions + Dependabot→dev, `2bfe6ad`
  fixes del dry-run (encoding de `template-check`, hint de rate-limit,
  correccion de `BUILDING_NEW_APP §2`), `766d167` handoff.
- **CI verde** en el ultimo commit con codigo (`2bfe6ad`). **Sin PRs abiertos.**
- **Server** (`ha-report2`): corriendo `v0.5.5-django`. Los fixes del dry-run
  (`2bfe6ad`, docs/CLI) aun no sincronizados — sin efecto runtime.
- **Toggles del repo aun DISABLED** (verificado via API): `secret_scanning`,
  `push_protection`, `dependabot_security_updates`. Accion del operador.
- Sin apps hijas; camino de fork validado y corregido la sesion pasada.

## §2. Objetivo de la sesion

**Promover `v0.5.6` de mantenimiento** — llevar a `main`/release los 3 commits
docs/CLI/CI que quedaron sobre el tag v0.5.5, para que las correcciones del
camino de fork esten en un release (una app hija forkea desde `main`/un tag).

## §3. Trabajo realizado

### 3.1. Validacion en server (regla "bump solo tras validar")

v0.5.6 **no tiene cambio de runtime de la app** (codigo del servicio identico a
v0.5.5); lo unico runtime-adjacent es el CLI `template-check`. Validado en
`ha-report2`: `git pull` a `766d167`, y `template-check` corrio **limpio en la
caja imprimiendo el 🔴 de las notas de v0.5.5 sin crashear** — o sea, valida en
vivo el fix de encoding (`2bfe6ad`). `/health` `v0.5.5-django` OPERATIVO,
servicio intacto (sin restart, codigo identico).

### 3.2. Bump v0.5.6 + promocion (`b98a868`, PR #9)

Ritual de bump (VERSION+pyproject+CHANGELOG+AGENTS). CHANGELOG framea v0.5.6
como **mantenimiento sin cambio de runtime**: correccion de `BUILDING_NEW_APP
§2` (keep-names = default; el "must rename" dejaba ~740 refs rotas), fixes del
CLI `template-check` (encoding UTF-8 + mensaje de rate-limit), y bumps de
actions + Dependabot→dev. Suite **1120 passed**, ruff limpio. PR #9 **CI 8/8
verde**, merge commit (`0657ef7`) + tag/release **v0.5.6-django**. `main` =
`v0.5.6-django`, 0 commits de contenido sin promover.

## §4. Pendiente / proximos pasos

- **Sync del server a v0.5.6** (opcional, tidy): la caja quedo en `766d167`
  (v0.5.5). v0.5.6 es docs/CLI sin cambio de runtime, asi que sincronizar solo
  hace que `/health` reporte v0.5.6 y trae los docs/CLI. `git pull` (sin
  restart necesario).
- **🔴 Toggles del repo (tuyos):** al inicio seguian **DISABLED** —
  `secret_scanning`, `push_protection`, `dependabot_security_updates`. Activar
  en Settings → Code security (+ Private Vulnerability Reporting). Es el hueco
  de seguridad abierto de mayor valor en un repo publico. Recordatorio:
  Dependabot **alerts** si, *security updates* automaticas no (chocan con el
  lockfile hash-pinneado).
- **Backlog** (bajo valor): jsdom DOM-wiring, visual regression, Model C
  (`ameli-core` paquete), Django LTS 6.2 (~dic-2026).
- **Historial git**: ground-truth viejo; decision previa = aceptar (no purgar).
- Sin apps hijas todavia; camino de fork probado y corregido (release v0.5.6).
