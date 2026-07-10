## AMELI App Template handoff (sesion Claude, 2026-07-09)

Fecha: `2026-07-09`
Agente: `claude-opus-4-8`
Rama de trabajo: `dev` (version `v0.5.1-django`, HEAD `e4e2c18`)
Rama estable: `main` (en `v0.5.0-django`; **v0.5.1 aun NO promovido**)
Sesion previa: [`CLAUDE_HANDOFF_2026-07-08_TEMPLATE_DEV.md`](CLAUDE_HANDOFF_2026-07-08_TEMPLATE_DEV.md)

> **Nota de cierre retroactivo**: esta sesion no alcanzo a cerrarse en su
> momento (se trabajo en la caja con el operador y quedo sin handoff). Se
> redacta el 2026-07-10 a partir del registro autoritativo: el commit
> `e4e2c18` y el Appendix de [`SERVER_HARDENING.md`](SERVER_HARDENING.md),
> escritos durante la propia sesion 07-09 con el operador.

## §1. Objetivo

Cerrar la remediacion del host `ha-report2` que habia quedado **en
progreso** al terminar el 07-08 (ver §4/§5.1 del handoff 07-08): los tres
hallazgos priorizados de la auditoria del host (P1 SSH, P2 exposicion del
18080, P3 auto-patching).

## §2. Trabajo realizado (con el operador, en la caja)

Sin cambios de codigo — solo remediacion de host + su registro en doc
(`e4e2c18`, +41 lineas al Appendix de `SERVER_HARDENING.md`).

| # | Hallazgo | Antes | Remediacion | Verificacion |
|---|---|---|---|---|
| 🔴 P1 | SSH root brute-forceable | `PermitRootLogin yes` + `PasswordAuthentication yes`, puerto 22 Anywhere | Clave ed25519 (workstation → `/root/.ssh/authorized_keys`, validada PowerShell + PuTTY); luego `PasswordAuthentication no` + `PermitRootLogin prohibit-password` + reload | `sshd -T` → `passwordauthentication no` / `permitrootlogin without-password`; login forzado por password → `Permission denied (publickey)`. **Root key-only.** |
| 🔴 P2 | App expuesta | `0.0.0.0:18080` HTTP + ufw `18080 ALLOW Anywhere` | Subnets reales derivadas de los access logs (192.168.110/24, 192.168.111/24, 10.100.100/24, 10.11.2.1 VPN); `ufw allow from <cidr> ... 18080`; borrada la regla `Anywhere` | Exposicion publica cerrada; acceso LAN/VPN preservado (quick win) |
| 🟠 P3 | Sin parches automaticos | `unattended-upgrades` NO instalado | Instalado + habilitado (`20auto-upgrades` = Update-Package-Lists/Unattended-Upgrade "1") | Servicio `active` |

**Ya estaba bien** (confirmado en la auditoria): Postgres solo en
`127.0.0.1:5432`; ufw activo default-deny incoming; servicio como usuario
dedicado `ameli-app-template-dev`; `app.env` en `0640 root:<grupo>`.

Con esto quedan **cerrados los pendientes P1/P2/P3** del §5.1 del handoff
07-08.

## §3. Metricas al cierre

- Repo: `dev @ e4e2c18`, `v0.5.1-django`, tree limpio. Sin cambios de
  codigo esta sesion (solo doc). CI: sin impacto (cambio doc-only).
- Host `ha-report2`: P1/P2/P3 cerrados; base ya-buena confirmada.

## §4. Continuidad — proximo agente / operador

### 4.1. Pendientes del HOST (operador, no urgentes)

- **P2 fix completo — TLS**: el trafico intra-LAN al `18080` sigue en HTTP
  plano. Bind del app a `127.0.0.1` (`AMELI_APP_HOST=127.0.0.1`, ya
  soportado) + Caddy (ya en `:80`) terminando TLS en 443 →
  `docs/TLS_WITH_CADDY.md` + §2 de `SERVER_HARDENING.md`. La restriccion
  ufw ya quito la exposicion publica; esto cierra el cleartext en la LAN.
- **Aplicar los units endurecidos**: la caja aun corre los units
  pre-hardening; re-render + `daemon-reload` para tomar el sandbox nuevo
  (§1 de `SERVER_HARDENING.md`).

### 4.2. Pendientes del REPO (opcionales)

- **Promover `v0.5.1` → `main`** (PR + CI verde + merge + tag). `main`
  sigue en `v0.5.0`.
- **M3** — rediseño atomico del throttle (diferido, riesgo bajo acotado).
- **Runbook de rotacion de secretos** — el §5 de `SERVER_HARDENING.md`
  lo pide; hoy solo la rotacion de `AUDIT_HMAC_KEY` esta documentada del
  todo (falta `DJANGO_SECRET_KEY`, `MFA_ENCRYPTION_KEY`, password DB).
- Refactor inline-styles → utility-classes (cosmetico).

### 4.3. Restricciones criticas (siguen vigentes)

- Server pull SIEMPRE de `dev`. `main` avanza solo por PR con CI verde.
- Tests requieren `APP_ENV=dev`. En el server no hay `sudo` (root).
- Al tocar seguridad: verificar el hallazgo antes de arreglar; correr la
  suite completa (`APP_ENV=dev pytest`) + ruff.

## §5. Cierre

Sesion **cerrada** (retroactivamente, 2026-07-10). El trabajo de host
P1/P2/P3 estaba hecho y registrado (`e4e2c18` + Appendix de
`SERVER_HARDENING.md`); este handoff formaliza el cierre y reconcilia los
pendientes que el handoff 07-08 aun listaba como abiertos.
