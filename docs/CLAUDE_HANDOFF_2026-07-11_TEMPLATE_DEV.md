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

Elegido por el operador: **`ameli-app template-check` CLI** — la pieza
"consultar" del canal de updates documentado el 10-jul.

## §3. Trabajo realizado

### 3.1. `template-check` CLI (commits `95d3926`, `c89cf2f`)

Nuevo subcomando `ameli-app template-check` (`cli.py`): consulta el ultimo
GitHub Release del template y lo compara contra el **lineage** de la app
(env `AMELI_APP_TEMPLATE_LINEAGE` → archivo root `TEMPLATE_LINEAGE` → el
`VERSION` de la app). Emite JSON `{current, latest, status, release_url,
notes_excerpt}` y sale **1 si esta behind** (cron-friendly), 0 si
up-to-date/ahead, 2 en error.

- **Sin dep runtime nueva** — stdlib `urllib`; repo validado por regex +
  host https fijo (`api.github.com`).
- **Token**: el repo del template es **privado** → la API da 404 sin auth;
  soporta `GITHUB_TOKEN` / `AMELI_APP_GITHUB_TOKEN`.
- **+11 tests** (`test_cli_template_check.py`) con `urlopen` mockeado.
- Docs: `BUILDING_NEW_APP.md` §6 "Consultar" lidera con el comando;
  tabla de CLI en `AGENTS.md`.
- **Lección**: CI corre **bandit** aparte de ruff-S. El `# noqa: S310`
  silencia ruff pero NO el `B310` de bandit → hace falta el patron dual
  `# noqa: S310  # nosec B310` (`c89cf2f`). Suite local 1098 pass; CI verde.

### 3.2. M3 — throttle atómico del gate por-usuario (commit `a711a02`)

`check_login_throttle` era **check-then-act**: leía el contador por-user
(sin lock) antes de que el fallo lo incrementara después, así que una
ráfaga concurrente leía un valor stale sub-cap y se colaba (techo blando).

**Fix — reserve-then-verify** sobre un gate dedicado `login_gate_user`:
cada `check` cuenta el intento atómicamente (`_bump_throttle_counter` bajo
`select_for_update`) y luego lee el sliding total; el incremento commitea
antes de la decisión → requests concurrentes ven counts distintos y el cap
es **techo duro**. `>` (no `>=`) mantiene el cap efectivo idéntico. Un
login exitoso limpia el gate vía `reset_login_throttle()`, cableado al
único hook de éxito `user_logged_in` (cubre login-form + MFA).

**Scope**: solo el gate por-usuario. El gate por-**IP** queda failure-based
soft **a propósito** — gatea un keyspace grande/mixto (usernames
rotativos), contar todos los intentos penalizaría ráfagas legítimas de una
IP compartida (NAT/oficina). `record_login_failure` + la alerta de
auth-failures **sin cambios**. Suite completa **1101 pass**; CI verde.

## §4. Continuidad / backlog (todo opcional — nada obligatorio pendiente)

### Host (operador) — trivial

- Limpiar las reglas ufw **vestigiales del 18080** (loopback-only ahora,
  inofensivas). Una a la vez + re-listar (gotcha de re-numeracion de ufw,
  ver `SERVER_HARDENING.md`).

### Repo (opcionales, ninguno urgente)

- ~~**`ameli-app template-check`**~~ **HECHO 11-jul** (§3.1).
- ~~**M3** — rediseño atomico del throttle~~ **HECHO 11-jul** (§3.2) — gate
  por-usuario reserve-then-verify (techo duro) + reset-on-success.
- ~~**Runbook de rotacion de secretos**~~ **HECHO 11-jul** (`ff1a074`) —
  `OPERATIONS.md` → "Secret rotation" cubre las 4 claves; SERVER_HARDENING
  §5 apunta ahi.
- ~~**SBOM (CycloneDX)**~~ **HECHO 12-jul** — `OPERATIONS.md` → "Lockfile /
  supply chain" → subseccion "SBOM (CycloneDX)": `pip-audit -f
  cyclonedx-json` (sin dep nueva), refresh por release, artefacto adjunto
  al release (no commiteado; `*.cdx.json` gitignored).
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
