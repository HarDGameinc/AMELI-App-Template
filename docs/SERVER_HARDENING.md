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

> **Confirm the service `User=`.** On `ha-report2` the *operator* logs in
> and runs deploys as `root` (SSH session) — that is an access-hygiene
> item (§4), separate from the service account. What matters here is that
> the **systemd service** runs as the dedicated non-root user, not root. If
> `systemctl show -p User` returns `root`, migrate: root negates the
> code-isolation the sandbox relies on (a compromised app process = root),
> and the two aggressive sandbox directives assume non-root.

Check:
```bash
systemctl show -p User ameli-app-template-dev-api.service    # expect the dedicated user, NOT root
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

The template **ships a loopback bind by default** — `api.host: "127.0.0.1"`
in `config/app.yaml.example`, and the same `127.0.0.1` fallback in
`ameli_app/config.py` — so out of the box the app is reachable only through a
reverse proxy, never directly from the network. The hardening requirement is
to **keep it that way**: an operator who overrides the bind to `0.0.0.0`
exposes the app over plain HTTP. (The reference deployment did exactly that
early on; **closed 2026-07-09**, see the appendix P2 — it is loopback-only
behind Caddy TLS today.)

For any non-dev deploy:

1. **Keep the loopback bind**: leave `api.host` / `AMELI_APP_HOST` at
   `127.0.0.1` so the app is only reachable through the reverse proxy, never
   directly.
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

> **Workstation key setup**: on a Windows workstation, generate + wire an
> SSH/SFTP key (OpenSSH + PuTTY + FileZilla) with
> [`tools/Setup-SshKey.ps1`](../tools/Setup-SshKey.ps1) — idempotent, prints
> the exact `authorized_keys` command. E.g.
> `.\tools\Setup-SshKey.ps1 -ServerHost <ip> -MakePpk`. Full manual (walkthrough,
> examples, troubleshooting): [`tools/Setup-SshKey.md`](../tools/Setup-SshKey.md).

- **SSH**: **key-only**. In `/etc/ssh/sshd_config`:
  `PasswordAuthentication no`, `KbdInteractiveAuthentication no`. For root
  login: the operator currently logs in as root, so at minimum use
  `PermitRootLogin prohibit-password` (key-only root, **no** password);
  ideally create a sudo user and set `PermitRootLogin no`. Then `sudo
  systemctl restart ssh`. (Verify you can open a **second** session before
  closing the first, so a misconfig can't lock you out.)
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
- **Rotation**: full runbook for all four secrets (Django key, MFA
  encryption key, audit HMAC key, DB password) — cost, procedure and
  gotchas per secret — in `OPERATIONS.md` → **Secret rotation**. Headlines:
  rotating `MFA_ENCRYPTION_KEY` silently breaks every enrolled TOTP (verify
  TOTP after), and `AUDIT_HMAC_KEY` must go through `ameli-app
  rotate-audit-key` (never a bare env edit) so the chain stays verifiable.

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

---

## 9. Hardening a publicly-exposed dev/staging instance ⚙️

A dev/staging box reachable from the public internet over TLS (not just a
LAN/VPN sandbox) needs the production security posture even though it runs
`APP_ENV=dev`. The `_IS_DEV_ENV` gate makes several settings *default* to a
laxer value in dev — but each one has an env override that wins regardless of
`APP_ENV`. Set these on the instance (in `app.env`) so a public dev host is
not one config typo away from plaintext cookies or `DEBUG` tracebacks:

| Concern | Env var | Value for a public dev host |
| --- | --- | --- |
| Debug tracebacks off | `AMELI_APP_DJANGO_DEBUG` | `false` |
| Secure (HTTPS-only) cookies | `AMELI_APP_SESSION_COOKIE_SECURE` | `true` |
| Behind a TLS proxy | `AMELI_APP_SECURE_PROXY_SSL_HEADER` | `X-Forwarded-Proto=https` |
| Audit-log HMAC | `AMELI_APP_AUDIT_HMAC_KEY` | a real 32-byte key |
| MFA secret encryption | `AMELI_APP_MFA_ENCRYPTION_KEY` | a real Fernet key |
| HSTS | `AMELI_APP_HSTS_SECONDS` | `31536000` (see caveat below) — **but if a reverse proxy already sets HSTS, that is the source of truth; see below** |

> `ha-report2` already sets `DEBUG=false`, Secure cookies, the proxy SSL
> header, and real audit + MFA keys (verified 2026-07-13). HSTS on this host
> is **managed by Caddy** (per-site), not the app — see the next section.

### Where HSTS lives: app vs. reverse proxy ⚠️

If a TLS-terminating reverse proxy (Caddy, nginx) sits in front and already
emits `Strict-Transport-Security`, **the proxy is the source of truth** — its
`header` directive *replaces* whatever the app sends, so the app-side
`AMELI_APP_HSTS_*` env vars are shadowed and silently do nothing. Check the
actual served header before assuming the app controls it:

```bash
curl -sI https://<host>/ | grep -i strict-transport-security
```

- **App-managed** (no proxy HSTS): use the `AMELI_APP_HSTS_*` env vars above.
- **Proxy-managed** (e.g. `ha-report2` / Caddy): edit the HSTS line in the
  proxy's per-site config; leave the app HSTS vars unset.

### The `includeSubDomains` caveat 🔴

`includeSubDomains` extends the HSTS policy to every subdomain **of the host
that sends it** — for `app.example.com` that is `*.app.example.com`, **not**
siblings like `other.example.com` and **not** the parent `example.com`. The
footgun is turning it on for a host that has (or will have) HTTP-only hosts
beneath it, or submitting to the HSTS **preload** list, which hardcodes the
whole subtree into browsers. On a leaf host with no subdomains of its own it
adds scope for no benefit. Enable `includeSubDomains` **only** when the host
owns and HTTPS-serves every subdomain beneath it.

> Note: a sibling emitting `includeSubDomains` does **not** affect you — e.g.
> `other.example.com`'s flag covers `*.other.example.com`, never `app.example.com`.
> The cross-host risk only exists when the header is set on a *parent* domain.

- **App-managed**: `includeSubDomains` defaults **OFF** (opt-in, matching
  Django). Turn HSTS on, and opt into subdomains only if you own the subtree:
  ```bash
  AMELI_APP_HSTS_SECONDS=31536000
  # AMELI_APP_HSTS_INCLUDE_SUBDOMAINS=true   # ONLY if this host owns *.its-subtree
  ```
  The flag is never emitted when HSTS is off, and a non-boolean value fails
  closed (the app refuses to boot).
- **Proxy-managed** (Caddy per-site block): omit the flag from the value.
  ```caddyfile
  # in the site's block — ONLY this header, so the app's own
  # Referrer-Policy / X-Frame-Options / CSP still pass through untouched
  header Strict-Transport-Security "max-age=31536000"
  ```
  > **`ha-report2` (2026-07-13):** `app.example.com` (a leaf, no subdomains of
  > its own) had no HSTS; added the line above to its Caddy site block without
  > `includeSubDomains`. `other.example.com` keeps its pre-existing `includeSubDomains`
  > (which only ever scoped `*.other.example.com`, so it never touched app.example.com).

---

## Appendix — `ha-report2` host status (dev box)

Audit + remediation performed with the operator (Debian 13 "trixie",
service runs as the dedicated user `ameli-app-template-dev`).

### Closed 2026-07-08 → 2026-07-09

- 🔴 **P1 — SSH (CLOSED 2026-07-09)**: was `PermitRootLogin yes` +
  `PasswordAuthentication yes` (default) with port 22 open to Anywhere.
  Set up an **ed25519 key** (workstation → `/root/.ssh/authorized_keys`,
  validated from PowerShell + PuTTY), then set `PasswordAuthentication no`
  + `PermitRootLogin prohibit-password` and reloaded. Verified:
  `sshd -T` → `passwordauthentication no` / `permitrootlogin
  without-password`; a forced-password login returns `Permission denied
  (publickey)`. **Root is now key-only.**
- 🔴 **P2 — App exposure (CLOSED 2026-07-09, quick win)**: `18080` was
  `0.0.0.0` + `ufw ALLOW Anywhere`. Derived the real client subnets from the
  app's access logs (192.168.110.0/24, 192.168.111.0/24, 10.100.100.0/24,
  10.11.2.1 VPN), added `ufw allow from <cidr> ... 18080`, then deleted the
  `Anywhere` rule. Public exposure closed; LAN/VPN access preserved.
- 🟠 **P3 — Auto-patching (CLOSED 2026-07-09)**: installed + enabled
  `unattended-upgrades` (`20auto-upgrades` = `Update-Package-Lists "1"` /
  `Unattended-Upgrade "1"`; service active).

### Already good (verified in the audit)

Postgres bound to `127.0.0.1:5432` only; ufw active default-deny incoming;
service runs as the dedicated non-root user; `app.env` is `0640
root:<run_group>`.

### Closed 2026-07-10

- ✅ **Hardened systemd units applied (§1)**: re-rendered the instance units
  (`APP_ENV=dev bash -c 'source scripts/_common.sh; render_systemd_units'`)
  + restarted api/notifier. `systemd-analyze security` for the api dropped
  from **8.4 EXPOSED → 1.5 OK**; the app came back healthy (`/health` ok, no
  syscall/EPERM in the journal). Pre-change units backed up to
  `/root/systemd-backup-20260710/`.
- ✅ **`verify-audit.timer` enabled (§7)**: it was rendered but no profile
  enabled it — fixed in-repo (now enabled by every profile) and enabled live
  on the box (`systemctl enable --now …-verify-audit.timer`).
- ✅ **TLS front (§2) — P2 fully closed**: the app is loopback-only
  (`127.0.0.1:18080`) and fronted by Caddy at `app.example.com:8443` with a
  real wildcard cert (`/etc/ssl/ameli/wildcard-*`, not the internal CA),
  proxying with `X-Forwarded-Proto https`. The app-side config had a silent
  bug — `AMELI_APP_SECURE_PROXY_SSL_HEADER=X-Forwarded-Proto=https` never
  matched Django's WSGI META key, so `request.is_secure()` stayed False
  behind the TLS. Fixed in-repo (the parser now normalizes the wire name)
  and in `app.env` (canonical value + `SESSION_COOKIE_SECURE=true` +
  `CSRF_TRUSTED_ORIGINS=https://app.example.com:8443`, stale `0.0.0.0` bind
  removed). Verified: HTTPS login works and the browser shows
  `__Host-ameli_csrf` + `Secure` on both cookies (proof `is_secure()` is now
  True).

- ✅ **SSH port 22 restricted (§4)**: replaced the `OpenSSH ALLOW Anywhere`
  (v4 + v6) with per-source allows for the admin/VPN ranges
  (`192.168.100/110/111.0/24`, `10.100.100.0/24`, `10.11.2.1`). Applied
  self-protectingly: allow the current SSH source first, verify a fresh
  session, then drop `Anywhere`.
  > **ufw gotcha**: rules **renumber after every delete**. Delete ONE rule,
  > then re-list — deleting a second by its old number hit an unrelated rule
  > (belonging to another service on the host), which was restored. Prefer
  > `ufw status numbered` immediately before each single `ufw delete <n>`.

### Closed 2026-07-13

- **Vestigial ufw (CLOSED)**: the three `18080` LAN/VPN allow rules were moot
  (the app is loopback-only; clients reach it through the TLS proxy) and have
  been removed. Verified loopback-only first (`ss -tlnp | grep 18080` →
  `127.0.0.1:18080`), then deleted **by rule specification** rather than by
  number — `ufw delete allow from <cidr> to any port 18080 proto tcp` — which
  sidesteps the renumbering gotcha above entirely. `ufw status` now shows no
  `18080` rules.

### Still pending

Nothing open on this host.
