## AMELI App Template handoff (sesion Claude, 2026-07-10)

Fecha: `2026-07-10`
Agente: `claude-opus-4-8`
Rama de trabajo: `dev` (version `v0.5.1-django`, HEAD `cbd00cf` al momento de abrir este handoff)
Rama estable: `main` (en `v0.5.0-django`; **v0.5.1 aun NO promovido**)
Sesion previa: [`CLAUDE_HANDOFF_2026-07-09_TEMPLATE_DEV.md`](CLAUDE_HANDOFF_2026-07-09_TEMPLATE_DEV.md)

> **Sesion en curso** — este handoff se va completando durante la sesion.

## §1. Snapshot al inicio

- Se retoma en una workstation Windows nueva (`hardgame1`); local estaba **43
  commits atras** de `origin/dev`. Fast-forward a `origin/dev`
  (`v0.5.1-django`). Desde el cierre del 03-jul (v0.4.9) el remoto avanzo
  mucho: doc-set integrado, Postgres en CI, D-1 (identidad visual) completo,
  a11y (axe-core), **security review → v0.5.1** y hardening de systemd.
- `main` promovido a **v0.5.0** el 07-07 (ya **no** esta congelado); v0.5.1
  aun sin promover. Memoria `promote-to-main-milestone` actualizada.

## §2. Objetivo de la sesion

Retomar: revisar local vs remoto + documentacion, y avanzar. Derivo en (1)
crear tooling de acceso SSH/SFTP a la workstation, y (2) **revision completa
de `SERVER_HARDENING.md`** (repo + auditoria live del host).

## §3. Trabajo realizado

### 3.1. Sync + cierre retroactivo del handoff 07-09 (`dc4b082`)

La sesion 07-09 (remediacion de host P1/P2/P3 con el operador) nunca se
cerro formalmente: los resultados estaban en el Appendix de
`SERVER_HARDENING.md` (`e4e2c18`) pero sin handoff, y el 07-08 aun listaba
P1/P2/P3 como pendientes. Se creo `CLAUDE_HANDOFF_2026-07-09` formalizando
el cierre y se reconcilio el pendiente stale del 07-08.

### 3.2. Tooling SSH/SFTP de workstation (`bf38014`, `cbd00cf`)

Para no repetir el setup manual de llaves. En esta maquina **no habia
llave** (solo `known_hosts`) → se genero una `ed25519` con passphrase
(`hardg@workstation-hardgame1`), pendiente de autorizar + probar en el
server (ver §4.2).

- **`tools/Setup-SshKey.ps1`** — helper PowerShell **idempotente** (nunca
  pisa una llave; `-Force` para regenerar) y generico (`-KeyName`,
  `-Comment`, `-ServerHost`, `-ServerUser`, `-Port`, `-MakePpk`). Genera la
  llave, imprime la publica + el comando exacto de `authorized_keys`, opcional
  `.ppk` (PuTTYgen), e instrucciones para OpenSSH/PuTTY-Pageant/FileZilla. No
  maneja la passphrase (la pide `ssh-keygen`). Verificado (idempotencia +
  `Get-Help`).
- **`tools/Setup-SshKey.md`** — manual completo (walkthrough end-to-end,
  parametros, ejemplos, notas de seguridad, troubleshooting). Enlazado desde
  el `.LINK` del script y desde `SERVER_HARDENING.md` §4.

### 3.3. Revision completa de `SERVER_HARDENING.md`

**Lado repo (verificado por el agente):** las afirmaciones ✅ in-repo son
ciertas. Los 9 units de `deploy/systemd/*.service` tienen el sandbox moderno;
`api` = full (caps vacio, `ProtectSystem=full`, `ReadWritePaths` acotado,
`User=__RUN_USER__`); `backup` = deliberadamente mas liviano (root,
`CapabilityBoundingSet=CAP_DAC_OVERRIDE/READ_SEARCH/CHOWN/FOWNER`, sin
`SystemCallFilter`). Matriz de ownership en `_common.sh` correcta (ETC 0750,
`app.env` 0640, DATA/LOG/BACKUP 0750/0640 a `RUN_USER`, codigo root:root).
`AMELI_APP_HOST` y `AMELI_APP_SECURE_PROXY_SSL_HEADER` existen. **Nada que
arreglar del lado del codigo.**

**Auditoria live del host `ha-report2` (10-jul), con el operador (root):**

| § | Check | Estado |
|---|---|---|
| §3 | Postgres `127.0.0.1:5432`, rol app NO superuser | ✅ |
| §4 | SSH `permitrootlogin without-password` + `passwordauthentication no` + `kbdinteractive no` | ✅ (P1) |
| §5 | `app.env` `0640 root:ameli-app-template-dev`, no en git | ✅ |
| §6 | `backup.timer` activo + 3 archivos reales (08/09/10-jul, rotando) | ✅ |
| — | `unattended-upgrades active` | ✅ (P3) |
| §2 | App en **`127.0.0.1:18080`** (loopback) + ufw default-deny + 18080 a LAN/VPN + Caddy en `:80` | ✅ parcial |

El **bind a loopback** del 18080 (parte del P2-full) ya esta hecho — mejor de
lo que el appendix daba por pendiente.

#### Hallazgos abiertos (priorizados)

1. 🔴 **Units endurecidos NO aplicados (§1)** — `systemd-analyze security` da
   **8.4 EXPOSED** con `✗ UMask=` vacio → corre el unit pre-hardening. El repo
   los tiene, nunca se renderizaron en la caja. Fix: `APP_ENV=dev bash
   scripts/update.sh` (re-render + restart, instance-scoped) o re-render manual
   → `/etc/systemd/system/` + `daemon-reload`. Esperado: score baja a ~2-4.
2. 🟠 **Sin TLS en la LAN (§2)** — Caddy escucha solo en `:80` (HTTP), sin
   `:443`. App loopback + proxeado, pero trafico LAN en texto plano
   (passwords + MFA). Fix: Caddy TLS en 443 (`docs/TLS_WITH_CADDY.md`) +
   `AMELI_APP_SECURE_PROXY_SSL_HEADER`. (El `8443` visible es de otra app,
   Bandwidth.)
3. 🟠 **Timer `verify-audit` NO programado (§7)** — la cadena de auditoria no
   se verifica periodicamente. El repo trae el `.service`/`.timer` pero no esta
   enabled para esta instancia. Fix: incluirlo en `APP_SYSTEMD_PROFILE` +
   re-render, o `systemctl enable --now ameli-app-template-dev-verify-audit.timer`.
4. 🟡 **SSH puerto 22 `ALLOW IN Anywhere` (§2/§4)** — menor; el daemon es
   key-only (mitiga brute-force). Opcional: restringir origen a CIDR admin/VPN
   o `fail2ban`.

> Fuera de scope (host compartido, otras apps): `ameli-notifier` en
> `0.0.0.0:8099` y un `ALLOW Anywhere` redundante en `8443` (Bandwidth).

## §4. Continuidad

### 4.1. Pendientes del HOST (operador) — accionables

1. 🔴 **Aplicar los units endurecidos** (#1 arriba) — mayor impacto, mas directo.
2. 🟠 **TLS con Caddy en 443** (#2) — cierra el cleartext en la LAN.
3. 🟠 **Enable `verify-audit.timer`** (#3).
4. 🟡 Restringir SSH 22 a CIDR admin/VPN o `fail2ban` (#4).

### 4.2. Pendiente de la WORKSTATION (operador)

- **Autorizar + probar la llave** generada en §3.2: pegar la publica en
  `/root/.ssh/authorized_keys` (desde una sesion ya autorizada) y validar
  `ssh root@10.100.100.16`; luego PuTTY (`.ppk` + Pageant) y FileZilla.

### 4.3. Pendientes del REPO (opcionales)

- Actualizar el Appendix de `SERVER_HARDENING.md` con los resultados de hoy
  (bind loopback hecho; 3 hallazgos nuevos).
- Promover `v0.5.1` → `main`. M3 throttle atomico. Runbook de rotacion de
  secretos. Inline-styles → utility-classes.

### 4.4. Restricciones criticas (vigentes)

- Server pull SIEMPRE de `dev`. `main` avanza solo por PR con CI verde.
- Tests requieren `APP_ENV=dev`. En el server no hay `sudo` (root).
- Al tocar seguridad: verificar el hallazgo antes de arreglar; suite completa
  (`APP_ENV=dev pytest`) + ruff antes de push.
