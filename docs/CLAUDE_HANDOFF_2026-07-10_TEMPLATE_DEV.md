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

### 3.4. Aplicacion de #1 + #3 en el host (10-jul) + fix de repo #3 (`48d0bd3`)

- **#1 — units endurecidos aplicados**: render quirurgico en el box
  (`APP_ENV=dev bash -c 'source scripts/_common.sh; render_systemd_units'`)
  + restart api/notifier. `systemd-analyze security` del api: **8.4 EXPOSED
  → 1.5 OK**; app sana (`/health` ok, journal sin EPERM/syscall). Backup de
  los units previos en `/root/systemd-backup-20260710/`. **CERRADO.**
- **#3 — verify-audit**: fix de repo (`48d0bd3`) — `resolve_systemd_profile`
  ahora habilita el `verify-audit.timer` en **todo** profile (era renderizado
  pero nunca habilitado) + agregado a `ALL_UNIT_SUFFIXES` (uninstall) + test
  parametrizado. Habilitado live en el box (`systemctl enable --now
  …-verify-audit.timer`, programado). **CERRADO.**
- El appendix de `SERVER_HARDENING.md` quedo actualizado (sección "Closed
  2026-07-10").

### 3.5. #2 TLS — cierre real + fix de repo del proxy header (`32eb65f`)

Al revisar el Caddyfile se vio que el TLS **ya estaba montado** (07-09):
`dev03.ameli.cl:18480` con cert wildcard real → `127.0.0.1:18080`. (Mi
"sin TLS" del audit fue un artefacto de grep — filtre `:80/:443` y me
perdi el `:18480`.) **Pero** el `app.env` tenia un bug silencioso:
`AMELI_APP_SECURE_PROXY_SSL_HEADER=X-Forwarded-Proto=https` nunca
matcheaba la clave WSGI de Django (`HTTP_X_FORWARDED_PROTO`), asi que
`request.is_secure()` quedaba **False** detras del TLS (secure-cookies/
HSTS/CSRF-seguro sin activarse, sin error).

- **Repo (`32eb65f`)**: `security_headers.py` ahora **normaliza** el nombre
  del header (acepta `X-Forwarded-Proto` y lo mapea a
  `HTTP_X_FORWARDED_PROTO`) + `TLS_WITH_CADDY.md` documenta los 4 env vars
  (antes solo `SESSION_COOKIE_SECURE`) + test.
- **Host**: `app.env` corregido — header canonico, `SESSION_COOKIE_SECURE=
  true`, `CSRF_TRUSTED_ORIGINS=https://dev03.ameli.cl:18480`, borrada la
  linea stale `AMELI_APP_HOST=0.0.0.0`.
- **Verificado**: login por HTTPS OK; cookies `__Host-ameli_csrf` +
  `ameli_app_session` con `Secure=true` (prueba de que `is_secure()` es
  True). **#2 CERRADO.**

### 3.6. #4 SSH 22 restringido + limpieza ufw (host)

Se reemplazo el `OpenSSH ALLOW Anywhere` (v4+v6) por allows por-CIDR de
las redes admin/VPN (192.168.100/110/111.0/24, 10.100.100.0/24,
10.11.2.1). Secuencia self-protecting: allow del origen actual primero
(el operador entra por VPN `10.11.2.1`), luego drop del Anywhere.
**Gotcha vivido**: `ufw` re-numera tras cada delete → borrar dos seguidas
por numero pego en una regla ajena (`8106/tcp` de OMEGA), que se
restauro. Regla de oro documentada en `SERVER_HARDENING.md`: borrar una y
re-listar. Las reglas vestigiales del 18080 se dejaron (inofensivas,
loopback-only). **#4 CERRADO.**

## §4. Continuidad

### 4.1. Pendientes del HOST (operador) — accionables

1. ~~🔴 Aplicar units endurecidos (#1)~~ **CERRADO 10-jul** (8.4→1.5 OK, §3.4).
2. ~~🟠 Enable `verify-audit.timer` (#3)~~ **CERRADO 10-jul** (§3.4).
3. ~~🟠 TLS (#2)~~ **CERRADO 10-jul** (§3.5) — front ya existia (07-09); se
   arreglo el proxy header (repo + app.env), login HTTPS validado.
4. ~~🟡 Restringir SSH 22 (#4)~~ **CERRADO 10-jul** (§3.6) — 22 solo desde CIDR
   admin/VPN. **Revision de SERVER_HARDENING completa: los 4 hallazgos cerrados.**

Unico remanente opcional: limpiar las reglas ufw vestigiales del 18080
(inofensivas). Nada mas pendiente del host.

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

### 3.7. Release de seguridad v0.5.2 — Django 5.2.16 (post-cierre, `31bb921`)

El CI `pip-audit` (post-push del dia) marco **3 CVEs** en django 5.2.15
(PYSEC-2026-2090/2091/2092). Bump del lock a **django==5.2.16** (patch
5.2 LTS, no el 6.0.7 non-LTS) con hashes de PyPI, en `requirements.lock`
+ `requirements-dev.lock`; el rango `Django>=5.2,<7` ya lo permitia (sin
cambios de codigo). Bump ritual a **v0.5.2-django**. CI verde
(pip-audit ok en Linux). Pendiente: deploy al server (`git pull` + `pip
install --require-hashes -r requirements.lock` + restart).

## §5. Cierre

**Revision de `SERVER_HARDENING.md` completa (2026-07-10).** Los 4
hallazgos del audit cerrados: #1 units endurecidos (8.4→1.5 OK), #2 TLS
(proxy header + login HTTPS validado), #3 verify-audit timer, #4 SSH 22
restringido. Lado repo verificado + 3 fixes que benefician toda app hija
(verify-audit en profiles `48d0bd3`; proxy-header normalizado + doc TLS
`32eb65f`). El host `ha-report2` quedo sustancialmente endurecido:
sandbox systemd, TLS end-to-end con cookies seguras, audit-verify activo,
SSH key-only + restringido por CIDR, Postgres loopback. Unico remanente
opcional: limpiar reglas ufw vestigiales del 18080. Ademas se corto el
release de seguridad **v0.5.2-django** (Django 5.2.16, 3 CVEs — §3.7).
`dev` en `v0.5.2-django`; ni v0.5.1 ni v0.5.2 promovidos a `main` aun
(main sigue en v0.5.0). **Deploy pendiente al server**: 5.2.16 aun no
esta live (git pull + reinstall deps + restart).
