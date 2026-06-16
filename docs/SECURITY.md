# Security policy

This document is the canonical place for security-relevant operational
information about the AMELI App Template: how to report a vulnerability,
how secrets are rotated, what residual risks the template carries by
design, and what the operator is responsible for. The threat-model side
of the picture lives in [`THREAT_MODEL.md`](THREAT_MODEL.md).

## Reporting a vulnerability

| Contact | Where |
| --- | --- |
| Email | `hardgameinc@gmail.com` |
| Subject prefix | `[AMELI-SEC]` |
| Response SLA | 72 h acknowledgment, 30 d remediation target |

Please include:

- The branch, commit hash and environment (`dev` / `staging` / `prod`).
- A minimal reproduction or proof-of-concept (curl command, screenshot,
  test that fails). Do NOT include production secrets.
- Your suggested severity (CVSS or descriptive).

Do **not** open a public GitHub issue for a vulnerability that has not
been patched yet. If you need to coordinate disclosure with another
party, mention it in the report.

## Supported versions

| Version line | Status |
| --- | --- |
| `dev` branch | Active development; fixes land here first. |
| `main` branch | Latest promoted release. Fixes back-ported from `dev`. |
| Tags prior to current `VERSION` | Best-effort only; no guaranteed back-port. |

The `VERSION` file at the repo root is the source of truth.

## Cryptographic key custody

The template holds three categories of long-lived secrets. Each has a
distinct rotation playbook.

### 1. `AMELI_APP_DJANGO_SECRET_KEY`

- **Purpose**: Django's session signer, password reset signer, CSRF
  token signer.
- **Rotation cadence**: 12 months OR on suspected compromise.
- **Procedure**:
  1. Generate a new key: `python -c "import secrets; print(secrets.token_urlsafe(64))"`
  2. Set the new value in `app.env` on every node.
  3. Restart the systemd unit. Existing sessions will be invalidated —
     this is intentional. Users re-authenticate.
- **Caveat**: Pending password-reset links signed under the old key
  stop working immediately. Time the rotation outside a support window
  if you can.

### 2. `AMELI_APP_AUDIT_HMAC_KEY`

- **Purpose**: HMAC seed for the forward-chained audit log.
- **Rotation cadence**: 12 months OR on suspected compromise.
- **Procedure**:
  ```bash
  ameli-app rotate-audit-key --from-key-env=OLD_KEY --to-key-env=NEW_KEY --apply-env=/etc/ameli/app.env
  ```
  The CLI re-stamps every chained row under the new key inside one
  transaction. The pre-rotation chain is re-validated under the old
  key first; a broken chain refuses to rotate.
- **Caveat**: The retention sweep `--audit-max-age-days` re-stamps
  surviving rows under the live key too (see `_prune_audit_with_anchor`
  in `accounts/services.py`); keep an external archive before pruning
  if you need to retain the original HMACs.

### 3. `AMELI_APP_MFA_ENCRYPTION_KEY`

- **Purpose**: Fernet (AES-128-CBC + HMAC-SHA256) symmetric key that
  wraps the TOTP shared secret on the `User` row at rest. Closes ASVS
  V2.8.1-2.8.6.
- **Rotation cadence**: 12 months OR on suspected compromise.
- **Procedure**:
  1. Generate a new key:
     ```bash
     python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
     ```
  2. Set the new value in `app.env` on every node.
  3. Run a one-shot re-encrypt sweep against the DB using the data
     migration `accounts.0012_mfa_secret_encrypt` (the forward path
     detects rows under the previous key as "not Fernet under live
     key" and treats them as plaintext, so a rotation without an
     intermediate "decrypt under old, re-encrypt under new" step
     LOSES the existing secrets and forces every user to re-enroll
     TOTP). For a controlled rotation: load the OLD key first, run
     `migrate accounts 0011` to decrypt to plaintext, swap to NEW
     key, run `migrate accounts 0012` to re-encrypt. Operators should
     drain auth traffic during this window.
  4. Restart the systemd unit. Active TOTP authenticators on user
     phones continue to work — the shared secret is unchanged, only
     the wrap is.
- **Caveat**: This key is distinct from `SECRET_KEY` and
  `AUDIT_HMAC_KEY` by design (ASVS expects key separation). Losing
  one must not compromise the others.
- **Caveat 2**: Without this key configured outside `dev`, the boot
  guard in `settings.py` refuses to start. In `dev` the wrap
  pass-throughs to plaintext so the test suite + CI keep working
  without operator setup.

### 4. `AMELI_APP_BACKUP_GPG_RECIPIENT`

- **Purpose**: GPG identity that encrypts every backup archive that
  leaves the host.
- **Rotation cadence**: per the key holder's policy.
- **Procedure**: import the new public key on the backup host, update
  the env var. Old archives remain decryptable by anyone holding the
  old private key — archive that key separately if you need to read
  historical backups.

### Storage rules

- Keys are environment variables read at process boot; they are never
  written to the repo, the audit log, or shell history.
- The boot guards in `src/ameli_web/settings.py` refuse to start when
  the bundled dev `SECRET_KEY` is present outside the `dev` environment.
- The `apply_audit_key_to_env_file` helper uses `O_NOFOLLOW` + same-dir
  tempfile + `os.replace` + parent-dir fsync, so the env-file rewrite
  is atomic and cannot follow an attacker-planted symlink.

## Residual risk register

The template ships with a small number of accepted, documented risks.
Each is something the operator can choose to remediate or accept.

| ID | Risk | Status | Mitigation |
| --- | --- | --- | --- |
| R-01 | TOTP shared secret stored unencrypted in the `User` row | **Closed 2026-06-16** | Fernet wrap keyed off `AMELI_APP_MFA_ENCRYPTION_KEY`. Boot guard refuses to start outside `dev` without the key. Migration `accounts.0012_mfa_secret_encrypt` re-encrypts legacy rows. |
| R-02 | Audit retention prune re-stamps surviving rows under the live key (original HMACs are lost) | Accepted by design | The prune is opt-in (`audit_max_age_days=None` by default). Archive externally before pruning. |
| R-03 | Static asset SRI hashes default to empty for Swagger/ReDoc | Accepted | Pin a vendored copy under `static/` or supply hashes via `OPENAPI_SWAGGER_SRI` / `OPENAPI_REDOC_SRI`. |
| R-04 | Dependency pins use `>=` rather than `==` with hashes | Mitigation pending | Tracked separately; see `docs/COMPLIANCE_ASVS_L2_2026-06-15.md` roadmap item #1. |
| R-05 | No automatic AV scan on avatar upload | Accepted | Format whitelist + pixel cap + byte cap close the common decompression-bomb / SVG-JS vectors. Operator can wire clamd via a custom signal handler. |
| R-06 | Maintenance-mode singleton bypasses `/profile/password/` so a `must_change_password=True` user can always rotate | Accepted by design | Without the bypass the user is permanently bounced — confirmed by `tests/test_code_review_fixes_20260615.py`. |
| R-07 | HSTS is enabled by default outside `dev` (`SECURE_HSTS_SECONDS=31536000`); an HTTPS rollback is hard to undo | Operator opt-out | Set `AMELI_APP_HSTS_SECONDS=0` until TLS is stable. |
| R-08 | `/health` and `/metrics` are publicly reachable unless `HEALTH_METRICS_ALLOWLIST` is set | Accepted | Allowlist is opt-in. Setting it matches both REMOTE_ADDR and the upstream proxy hop, so `127.0.0.1` works behind Caddy. |

## Operator security checklist

Before promoting a deploy from `dev` to `staging` / `prod`:

- [ ] `AMELI_APP_DJANGO_SECRET_KEY` set to a 64-byte URL-safe value.
- [ ] `AMELI_APP_ALLOWED_HOSTS` set to the actual hostnames, NOT `*`.
- [ ] `AMELI_APP_TRUSTED_PROXIES` set to the reverse-proxy IPs.
- [ ] `AMELI_APP_AUDIT_HMAC_KEY` set and `ameli-app verify-audit` clean.
- [ ] `AMELI_APP_PUBLIC_URL_BASE` set to the canonical public URL
      (required outside `dev` for the password-reset flow).
- [ ] `AMELI_APP_EMAIL_BACKEND` is `smtp` (or `file` for a sealed
      staging) — never `console` outside `dev`.
- [ ] `HEALTH_METRICS_ALLOWLIST` set to the LB / Prometheus IP if you
      do not want `/health` and `/metrics` public.
- [ ] Caddy / reverse proxy terminates TLS; HSTS rolled out gradually
      (15m -> 1d -> 7d -> 12mo) the first time.
- [ ] `ameli-app bootstrap-admin` ran once, the bootstrap password was
      rotated through the must-change flow, and the admin enabled MFA.
- [ ] systemd timer for `ameli-app verify-audit` is active.
- [ ] `scripts/backup.sh` runs as a cron / timer; the first archive
      passes `scripts/restore.sh verify`.

## Compliance posture

| Standard | Status | Reference |
| --- | --- | --- |
| OWASP ASVS 4.0.3 Level 2 | 63 PASS / 24 GAP / 5 N\A / 10 DEFERRED | [`COMPLIANCE_ASVS_L2_2026-06-15.md`](COMPLIANCE_ASVS_L2_2026-06-15.md) |

The template targets ASVS L2 as the working bar. The gap analysis above
maps each unmet control to a roadmap item.

## Out of scope

The template does not ship:

- Webhook delivery (removed in `641ece1`; document if you re-introduce).
- API tokens with scopes (removed in `641ece1`; document if you
  re-introduce).
- A web application firewall (WAF) layer — operator's reverse proxy.
- TLS termination — operator's reverse proxy (typically Caddy).
- A SIEM / log shipper — operator wires `journalctl` to their stack.
- An anti-virus scanner — operator can add via a signal handler on
  `User.avatar`.
