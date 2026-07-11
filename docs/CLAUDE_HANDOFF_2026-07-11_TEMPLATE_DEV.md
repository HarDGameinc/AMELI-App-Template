## AMELI App Template handoff (sesion Claude, 2026-07-11)

Fecha: `2026-07-11`
Agente: `claude-opus-4-8`
Rama de trabajo: `dev` (version `v0.5.2-django`, HEAD `9c99b17` al abrir)
Rama estable: `main` (en `v0.5.2-django` — promovido 2026-07-10)
Sesion previa: [`CLAUDE_HANDOFF_2026-07-10_TEMPLATE_DEV.md`](CLAUDE_HANDOFF_2026-07-10_TEMPLATE_DEV.md)

> **Sesion en curso** — este handoff se completa durante la sesion.

## §1. Snapshot al inicio

- `dev` == `origin/dev` (sync 0/0), tree limpio. **`main` y `dev` ambos en
  `v0.5.2-django`** (promocion + release + tag hechos el 10-jul).
- Server `ha-report2`: **v0.5.2 live** (Django 5.2.16, 3 CVEs parcheados),
  host endurecido (sandbox systemd 8.4→1.5, TLS end-to-end con cookies
  seguras, verify-audit activo, SSH key-only + restringido por CIDR,
  Postgres loopback).
- CI recortado (~75% menos minutos): docs-only skip, push a dev = 1 Python
  (3.13) + pip-audit + js; matriz completa + e2e + postgres en PR + weekly.
- Entorno dev = Windows nativo (`hardgame1`); ver `windows-local-dev-env`
  en memoria + `CONTRIBUTING.md` antes de correr checks.

## §2. Objetivo de la sesion

(pendiente de definir con el operador — se abrio el handoff tras revisar
documentacion.)

## §3. Trabajo realizado

(por completar)

## §4. Continuidad / backlog (todo opcional — nada obligatorio pendiente)

### Host (operador) — trivial

- Limpiar las reglas ufw **vestigiales del 18080** (loopback-only ahora,
  inofensivas). Una a la vez + re-listar (gotcha de re-numeracion de ufw,
  ver `SERVER_HARDENING.md`).

### Repo (opcionales, ninguno urgente)

- **`ameli-app template-check`** — CLI que consulta la GitHub Release mas
  reciente y compara contra el lineage de la app (canal "consultar" del
  update-channel; ver `DECISIONS.md` #7 + `BUILDING_NEW_APP.md` §6).
  Propuesto 10-jul, no implementado.
- **M3** — rediseño atomico del throttle (diferido; riesgo bajo acotado
  por el lockout permanente).
- **Runbook de rotacion de secretos** — el §5 de `SERVER_HARDENING.md` lo
  pide; hoy solo la rotacion de `AUDIT_HMAC_KEY` esta documentada del todo.
- Refactor inline-styles → utility-classes (cosmetico).
- **Modelo C del update-channel** (`ameli-core` package + Dependabot) —
  el canal mas fuerte, refactor grande; adoptar si la flota crece
  (`DECISIONS.md` #7).

### Restricciones criticas (vigentes)

- Server pull SIEMPRE de `dev`. `main` avanza solo por PR con CI verde +
  merge commit + tag/release (flujo en `RELEASE.md`).
- Tests requieren `APP_ENV=dev`. En el server no hay `sudo` (root).
- Al tocar seguridad: verificar el hallazgo antes de arreglar; suite
  completa (`APP_ENV=dev pytest`) + ruff antes de push.
