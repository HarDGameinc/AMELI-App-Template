## AMELI App Template handoff (sesion Claude, 2026-07-08)

Fecha: `2026-07-08`
Agente: `claude-opus-4-8` (parte final en `claude-fable-5`)
Rama de trabajo: `dev` (version final `v0.5.1-django`, HEAD `2477166`)
Rama estable: `main` (en `v0.5.0-django`; **v0.5.1 aun NO promovido**)
Sesion previa: [`CLAUDE_HANDOFF_2026-07-07_TEMPLATE_DEV.md`](CLAUDE_HANDOFF_2026-07-07_TEMPLATE_DEV.md)

> **Nota**: sesion de tres bloques — (1) revision de documentacion +
> verificacion del roadmap, (2) **revision de seguridad multi-agente** que
> cerro 7 hallazgos (`v0.5.1`), (3) **hardening a nivel servidor** (systemd
> + doc) y auditoria del host `ha-report2`. Todo validado en server y CI.

## §1. Snapshot al inicio

- `dev` en `v0.5.0-django`, tree limpio. `main` recien promovido a `v0.5.0`
  (sesion 2026-07-07). Server `ha-report2` OPERATIVO.
- Entorno dev = Windows nativo; venv `.venv`. Tests corren con
  `APP_ENV=dev` (M1 de esta sesion lo hace obligatorio, ver §3.2).

## §2. Objetivo de la sesion

Instruccion del operador: "revisa toda la documentacion, verifiquemos
roadmap" → derivo en "profundicemos en agujeros de seguridad" → y luego
"a nivel de servidor que revisar". La sesion cubrio las tres.

## §3. Trabajo realizado

### 3.1. Revision de docs + roadmap (`fe200fd`)

Verificado que el roadmap refleja la realidad: `TECH_EVOLUTION.md` al dia
(High/Medium cerrados, solo Low/opt), D-1 completo, **nada obligatorio
pendiente**. Corregidas referencias **stale a "main congelado"** (ya
promovido) en `CONTRIBUTING.md`, `RELEASE.md`, `DOCUMENTATION_PLAN.md`; el
relato de estado de `AGENTS.md` (faltaba la promocion v0.5.0); wording de
"alembic" → "Django migrations" en los testing gaps (no se usa Alembic);
marca de "RESUELTO" en `FRONTEND_DESIGN_REVIEW.md`; nota de correccion en
`SKILLS_REVIEW.md` (describia un setup Alembic inexistente).

### 3.2. Revision de seguridad multi-agente → 7 fixes (`v0.5.1`)

3 agentes en paralelo por clase de vulnerabilidad (authz/IDOR ·
injection/SSRF/traversal · crypto/session/CSRF/throttle) + verificacion
manual de cada hallazgo antes de arreglar. **Cero** inyeccion/SSRF/
traversal/XSS/CSRF/open-redirect (base muy fuerte). Los 7 son de
**logica/config**:

| # | Sev | Fix | Commit |
|---|---|---|---|
| M1 | med | **Entorno fail-closed**: env no declarado rehusa arrancar (antes → "dev" desactivaba TODOS los guards de prod) | `9975677` |
| M2 | med | **`mfa_required` se aplica**: `MfaRequiredMiddleware` fuerza enrolamiento; no se limpia al enrolar; self-disable bloqueado | `4478c52` |
| M3 | med→bajo | Docstring del throttle corregido (era check-then-act, no atomico); acotado por lockout permanente. Rediseño atomico diferido | `4e652fb` |
| L1 | bajo | **IDOR de avatar**: ownership por `avatar.name` exacto, no slug lossy (`john.doe`/`john_doe` colisionaban) | `284de8a` |
| L2 | bajo | `decrypt_secret`: `except` estrechado a `InvalidToken` | `f966bf5` |
| L3 | bajo | Cancel de email **two-step GET→POST** (mail-scanner no auto-cancela) | `a3ba537` |
| L4 | bajo | Invariante **≥1 superadmin activo** transaccional (`select_for_update`) | `b558908` |

Bump `v0.5.1` (`9ce8c24`), smokeado en server (`v0.5.1-django` OPERATIVO).
Suite **1086 verde**, ruff limpio. Varios tests viejos que codificaban el
comportamiento **inseguro** fueron actualizados al correcto.

### 3.3. Hardening a nivel servidor — repo (`b4ac16b`, `2442719`, `2477166`)

- **systemd**: los 9 units de `deploy/systemd/*.service` tenian baseline
  (`NoNewPrivileges`, `PrivateTmp`, `ProtectSystem=full`, `ProtectHome`).
  Se agregaron ~15 directivas modernas: `PrivateDevices`,
  `ProtectKernel*`, `ProtectControlGroups`, `ProtectClock/Hostname`,
  `RestrictAddressFamilies`, `RestrictNamespaces/Realtime/SUIDSGID`,
  `LockPersonality`, `SystemCallFilter=@system-service` (+ `~@privileged`),
  `CapabilityBoundingSet=` (vacio), `UMask=0077`. Se mantuvo
  `ProtectSystem=full` (no `strict`, para no bloquear `.pyc`). `backup`
  (root+pg_dump) quedo mas liviano a proposito.
- **`docs/SERVER_HARDENING.md`** (nuevo, en el indice de AGENTS): checklist
  del host — red/firewall, TLS/Caddy, Postgres, SSH, secretos, backups,
  observabilidad, con comandos de auditoria.
- El sandbox esta calibrado para el **usuario dedicado** (no root); el
  servicio efectivamente corre como `ameli-app-template-dev` (confirmado).

## §4. Auditoria del host `ha-report2` (2026-07-08)

Corrida con el operador (root, sin `sudo` — no instalado). **Hallazgos
priorizados, PENDIENTES de accion del operador en la caja** (no son del
repo):

- 🔴 **P1 — SSH**: `PermitRootLogin yes` + `PasswordAuthentication yes` +
  puerto 22 `ALLOW Anywhere` → root brute-forceable. **En progreso**: se
  genero una clave ed25519 en la workstation Windows
  (`C:\Users\hardg\.ssh\id_ed25519`), la publica ya esta en
  `/root/.ssh/authorized_keys`, **login por clave funciona en PowerShell**;
  falta configurar PuTTY (importar a `.ppk`) y **recien despues** desactivar
  el password (`PasswordAuthentication no` + `PermitRootLogin
  prohibit-password`). **NO se ha desactivado el password aun.**
- 🔴 **P2 — App expuesta**: bind `0.0.0.0:18080` en **HTTP plano** + ufw
  `18080 ALLOW Anywhere`. Quick win: restringir el 18080 a las CIDR LAN/VPN
  (patron que ya usan otros servicios). Fix completo: Caddy (ya corre en
  `:80`) proxeando con TLS a `127.0.0.1:18080` + `AMELI_APP_HOST=127.0.0.1`.
- 🟠 **P3 — `unattended-upgrades` NO instalado** → sin parches automaticos.
- ✅ Bien: Postgres solo en `127.0.0.1:5432`; ufw activo default-deny;
  servicio como usuario dedicado; `app.env` en `0640 root:grupo`.

> Nota: los units endurecidos (§3.3) **no se aplican con `git reset`** — son
> plantillas con `__PLACEHOLDER__` que el install renderiza a
> `/etc/systemd/system/`. Para activarlos hay que re-correr install/update
> (o re-renderizar) + `daemon-reload`. Aun no aplicado en el server.

## §5. Continuidad — proximo agente / operador

### 5.1. Pendientes del OPERADOR en el host (no-repo, prioridad alta)

> **Actualizado 2026-07-09**: P1, P2 (quick win) y P3 quedaron **CERRADOS**
> — ver [`CLAUDE_HANDOFF_2026-07-09_TEMPLATE_DEV.md`](CLAUDE_HANDOFF_2026-07-09_TEMPLATE_DEV.md)
> y el Appendix de `SERVER_HARDENING.md`. Solo siguen abiertos el #2 (fix
> completo TLS/Caddy) y el #4 (aplicar units endurecidos).

1. ~~**Terminar P1**: PuTTY con la clave → validar → desactivar password SSH.~~ **CERRADO 07-09.**
2. **P2 fix completo**: TLS con Caddy + bind loopback (el quick win ufw ya se aplico 07-09).
3. ~~**P3**: instalar `unattended-upgrades`.~~ **CERRADO 07-09.**
4. Aplicar los units endurecidos (re-render + daemon-reload) — opcional, aun pendiente.

### 5.2. Pendientes del REPO (opcionales)
- **Promover `v0.5.1` → `main`** (mismo flujo que v0.5.0: PR + CI verde +
  merge commit + tag). `main` sigue en `v0.5.0`.
- M3 rediseño atomico del throttle (diferido; riesgo bajo acotado).
- Refactor inline-styles → utility-classes (cosmetico).

### 5.3. Restricciones criticas (siguen vigentes)
- Server pull SIEMPRE de `dev`. `main` avanza solo por PR con CI verde.
- Deploy: `git fetch && git reset --hard origin/dev` → `check` → `migrate`
  (no hubo migraciones nuevas esta sesion) → restart. Esperar readiness
  antes de leer `/health` (puerto **18080**).
- Tests requieren `APP_ENV=dev` (M1). `gh` CLI en `C:\Program Files\GitHub
  CLI\` (no en PATH). En el server no hay `sudo` (se opera como root).
- Al tocar seguridad: verificar el hallazgo antes de arreglar; correr la
  suite completa (`APP_ENV=dev pytest`) + ruff.
