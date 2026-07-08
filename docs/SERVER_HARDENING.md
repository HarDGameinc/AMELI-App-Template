# Server hardening checklist

Date: `2026-07-08`
Scope: **host / deployment** security for a box running this template
(e.g. `ha-report2`). The application code is hardened separately (CSP,
MFA, audit chain, throttling, the 2026-07-08 security review); this doc
covers the layers *below* the app: systemd sandbox, network exposure,
PostgreSQL, SSH/OS, secrets, backups, observability.

Legend: ✅ done in-repo · ⚙️ operator action on the box · 🔴 highest priority.

---

## 0. What the template already does

- **Dedicated non-root run user**; the app code is installed `root:root`
  `0644`, so a compromised app process **cannot rewrite its own code**.
- **Secrets file** `/etc/<slug>/app.env` is `0640 root:<run_group>` inside
  a `0750` dir — not world-readable.
- **systemd sandbox** on every unit (✅ strengthened 2026-07-08): see §1.
- App-level: HSTS, `TRUSTED_PROXIES`, `HEALTH_METRICS_ALLOWLIST`, Secure
  cookies (prod), hash-pinned deps, env fail-closed.

---

## 1.0 Run as a dedicated non-root user 🔴 ⚙️

The install **defaults** to a dedicated system user (`RUN_USER=<slug>-<env>`,
e.g. `ameli-app-template-dev`) — that isolation is why the app code is
`root:root` (a compromised app process can't rewrite it) and why the
sandbox below can safely drop all capabilities.

> **Known deviation (dev box `ha-report2`, 2026-07-08): the service is
> running as `root`.** That negates the isolation — a compromise of the
> app process is a root compromise, and the read-only-code protection is
> moot (root can rewrite anything). This is the **highest-priority host
> fix**, above the sandbox tuning.

Check + migrate:
```bash
systemctl show -p User ameli-app-template-dev-api.service    # currently User=root?
# migrate to the dedicated user (re-run install with the default RUN_USER,
# or manually): create the system user, chown data/log/backup + the venv to
# it, keep the app code root:root, then re-render the units (User=<slug>-<env>)
# and daemon-reload. See scripts/install.sh / _common.sh for the exact
# ownership matrix (ETC 0750 root:grp, app.env 0640 root:grp, DATA/LOG 0750
# run_user:grp).
```

## 1. systemd sandbox ✅ (in-repo)

> **If you must keep `User=root` temporarily**, the two aggressive
> directives are calibrated for the non-root user and can break a root
> service: relax `CapabilityBoundingSet=` (empty → drop the line, or list
> only what's needed) and drop `SystemCallFilter=~@privileged @resources`.
> Better: fix §1.0 and keep the full sandbox. `systemd-analyze security`
> will flag the difference.


`deploy/systemd/*.service` now ship a modern sandbox: `NoNewPrivileges`,
`PrivateTmp`, `PrivateDevices`, `ProtectSystem=full`, `ProtectHome`,
`ProtectKernelTunables/Modules/Logs`, `ProtectControlGroups`,
`ProtectClock`, `ProtectHostname`, `RestrictAddressFamilies=AF_INET
AF_INET6 AF_UNIX`, `RestrictNamespaces/Realtime/SUIDSGID`,
`LockPersonality`, `SystemCallArchitectures=native`,
`SystemCallFilter=@system-service` (+ `~@privileged @resources`),
`CapabilityBoundingSet=` (empty — the services bind >1024, need no caps),
`UMask=0077`.

- `ameli-app-backup.service` (root + `pg_dump` + shell) is **deliberately
  lighter**: it keeps file-op capabilities and omits `SystemCallFilter` /
  `RestrictAddressFamilies` so the dump does not break.
- `ProtectSystem=strict` was **not** used (it would make the app dir
  read-only and block `.pyc` writes). To adopt it later, set
  `Environment=PYTHONDONTWRITEBYTECODE=1` and confirm every writable path
  is in `ReadWritePaths`.

⚙️ **Apply on the box** (re-run install/update deploys the new units; to
apply without reinstalling):
```bash
sudo cp deploy/systemd/*.service /etc/systemd/system/   # if edited in place, re-render placeholders
sudo systemctl daemon-reload
sudo systemctl restart ameli-app-template-dev-api.service
# verify the sandbox is active + no failures:
systemd-analyze security ameli-app-template-dev-api.service   # aim for a lower "exposure" score
journalctl -u ameli-app-template-dev-api.service -n 30 --no-pager
```
> If a service fails to start after this, the usual culprit is
> `SystemCallFilter` or a missing `ReadWritePaths` — check
> `journalctl` for `code=exited` + a syscall/EPERM and widen minimally.

---

## 2. Network exposure 🔴 ⚙️

The app currently binds **`0.0.0.0:18080` over plain HTTP** (verified: the
browser reaches `http://<host>:18080` directly, "Not secure"). For any
non-dev deploy:

1. **Bind to loopback**: set `api.host` / `AMELI_APP_HOST=127.0.0.1` so the
   app is only reachable through the reverse proxy, never directly.
2. **TLS reverse proxy**: put Caddy in front (see
   [`docs/TLS_WITH_CADDY.md`](TLS_WITH_CADDY.md)). Caddy terminates TLS on
   443 and proxies to `127.0.0.1:18080`. Set the app's
   `AMELI_APP_SECURE_PROXY_SSL_HEADER` to match what Caddy sends (e.g.
   `X-Forwarded-Proto=https`) **only** because the app is now unreachable
   except through Caddy — otherwise the header is spoofable.
3. **Firewall** (default-deny inbound):
   ```bash
   sudo ufw default deny incoming
   sudo ufw default allow outgoing
   sudo ufw allow 443/tcp
   sudo ufw allow from <admin-cidr> to any port 22 proto tcp   # restrict SSH source
   sudo ufw enable
   sudo ufw status verbose
   # 18080 must NOT be open to the network:
   sudo ss -tlnp | grep 18080     # expect 127.0.0.1:18080, not 0.0.0.0
   ```

---

## 3. PostgreSQL ⚙️

- **Bind local only**: `listen_addresses = 'localhost'` in
  `postgresql.conf` (unless the DB is on a separate host over a private
  network + TLS).
- **Auth**: `pg_hba.conf` uses `scram-sha-256` (not `trust`/`md5`) for the
  app's local connection.
- **Least privilege**: the app's DB role is **not** a superuser and owns
  only its own database; a strong, unique password (in `app.env`, never in
  git).
- Verify:
  ```bash
  sudo -u postgres psql -c "\du"                       # roles: app role not Superuser
  sudo ss -tlnp | grep 5432                              # expect 127.0.0.1:5432
  sudo grep -E '^(local|host)' /etc/postgresql/*/main/pg_hba.conf
  ```

---

## 4. SSH / OS ⚙️

- **SSH**: key-only + no root login. In `/etc/ssh/sshd_config`:
  `PasswordAuthentication no`, `PermitRootLogin no`, `KbdInteractive­Authentication no`,
  optionally `AllowUsers <op>`. Then `sudo systemctl restart ssh`.
- **fail2ban** for sshd (and optionally the web) to throttle brute force.
- **Unattended security upgrades**: `sudo apt install unattended-upgrades`
  + enable, so kernel/openssl/etc. patches land automatically.
- **Time sync** (`systemd-timesyncd`/chrony) — the audit chain, MFA TOTP
  and cookie expiries all depend on a correct clock.

---

## 5. Secrets ⚙️

Three critical keys live in `app.env`: `AMELI_APP_DJANGO_SECRET_KEY`,
`AMELI_APP_MFA_ENCRYPTION_KEY`, `AMELI_APP_AUDIT_HMAC_KEY` (+ the DB
password). Confirm:
```bash
sudo ls -l /etc/ameli-app-template-*/app.env     # 0640 root:<run_group>
sudo git -C /opt/ameli-app-template-* status --porcelain | grep -i env   # env must NOT be tracked
grep -RiE 'SECRET|HMAC|ENCRYPTION' /var/log/ 2>/dev/null | head   # keys must not leak to logs
```
- **Rotation**: document a rotation runbook. For `MFA_ENCRYPTION_KEY`,
  rotating invalidates existing ciphertext (Fernet cannot tell a wrong key
  from legacy plaintext — see the `decrypt_secret` L2 note); verify TOTP
  after any rotation. For `AUDIT_HMAC_KEY`, use the existing key-rotation
  tooling so the chain stays verifiable.

---

## 6. Backups ⚙️

`ameli-app-backup.timer` exists. Confirm the backup is **usable**, not just
present:
- **Encrypted at rest** (age/gpg) if the box or its storage isn't trusted.
- **Off-box copy** (a backup on the same disk as the DB is not a backup).
- **Restore tested**: periodically run `scripts/restore.sh` into a scratch
  DB and confirm the app boots + the audit chain verifies against it.
  ```bash
  systemctl list-timers | grep ameli
  ls -l /var/backups/ameli-app-* 2>/dev/null
  ```

---

## 7. Observability & integrity ⚙️

- `ameli-app-verify-audit.timer` verifies the hash-chained audit log —
  keep it enabled and alert on failure (a failed verify = tampering or
  corruption).
- **journald retention + off-box shipping**: so a host compromise can't
  erase the trail. `SystemMaxUse=` in `journald.conf`, and forward to a
  central/immutable log store if available.
  ```bash
  systemctl list-timers | grep verify-audit
  journalctl -u ameli-app-template-dev-verify-audit.service -n 20 --no-pager
  ```

---

## 8. Quick audit (run on the box, review the output)

```bash
# service sandbox score + status
systemd-analyze security ameli-app-template-dev-api.service | tail -5
systemctl is-active ameli-app-template-dev-api.service
# what's listening / exposed
sudo ss -tlnp
# firewall
sudo ufw status verbose 2>/dev/null || sudo nft list ruleset
# secret file perms
sudo ls -l /etc/ameli-app-template-*/app.env
# SSH policy
sudo sshd -T | grep -Ei 'passwordauthentication|permitrootlogin'
# postgres exposure
sudo ss -tlnp | grep 5432
# updates
systemctl status unattended-upgrades 2>/dev/null | head -3
```
