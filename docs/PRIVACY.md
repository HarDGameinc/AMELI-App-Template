# Privacy

Data inventory, retention, and user rights **as implemented by the
template**. The operator running a deploy is the legal *data controller*
and must complete the deploy-specific parts (legal basis, DPO, cross-border
transfer disclosures) — see [§10](#10-what-the-operator-must-decide-per-deploy).

Companion docs:
- [`SECURITY.md`](SECURITY.md) — threat model, controls, ASVS L2.
- [`OPERATIONS.md`](OPERATIONS.md) — retention sweep worker, secret
  rotation, backup handling.
- [`THREAT_MODEL.md`](THREAT_MODEL.md) — STRIDE trust boundaries.

## 1. Scope

This document covers the **Core template layer**. A child app inherits
these controls; anything the app adds (its own domain data — telemetry,
billing, tickets, whatever) is out of scope here and must be covered in
the child's own privacy doc.

## 2. Personal data inventory

Every DB row that can carry personal data, with the model file for
grepping. All timestamps are UTC.

| Store | Fields | Purpose | Notes |
|---|---|---|---|
| `accounts.User` ([`models.py:16`](../src/ameli_web/accounts/models.py)) | `username`, `email`, `display_name`, `avatar`, `role`, `theme_preference`, `color_theme`, `mfa_secret`, `mfa_*_enabled`, `mfa_required`, `must_change_password`, `locked_at`, `locked_reason`, `password` (argon2 hash), `last_login`, `created_at`, `updated_at`, `last_auth_alert_sent_at` | Auth, personalization, MFA | `password` argon2 ([`auth.py`](../src/ameli_web/settings/auth.py)); `mfa_secret` Fernet-encrypted at rest ([`accounts/mfa.py`](../src/ameli_web/accounts/mfa.py)) |
| `accounts.UserSession` ([`models.py:133`](../src/ameli_web/accounts/models.py)) | `session_key`, `user_agent`, `ip_address`, `created_at`, `last_seen_at`, `revoked_at` | Session listing + revoke (Phase 2) | User-visible under `/profile#sessions` |
| `accounts.MFARecoveryCode` ([`models.py:150`](../src/ameli_web/accounts/models.py)) | `code_hash`, `created_at`, `used_at` | One-time recovery | Stored HASHED — the raw code exists only during enrollment display |
| `accounts.MFAEmailChallenge` ([`models.py:163`](../src/ameli_web/accounts/models.py)) | `code_hash`, timestamps | Email 2FA | `code_hash` = keyed HMAC (`salted_hmac` over `SECRET_KEY`) since v0.5.5; NEVER the raw 6-digit code |
| `accounts.EmailChangeRequest` | `user`, `old_email`, `new_email`, `token_hash`, timestamps | Double-opt-in email change | Old address kept for post-change alert |
| `accounts.OutboundEmail` | `to_emails`, `subject`, `body`, retry/status metadata | Retry queue (SMTP outbox) | Contains full message text |
| `accounts.ThrottleCounter` | `scope`, `key`, `window_start`, `count` | Login/IP throttling | `key` is username or IP — pseudonymous |
| `audit.AuditEvent` | `action`, `payload` (JSON), `actor`, `target`, `prev_hmac`, `hmac`, timestamps | Hash-chained audit log | See §4 for the "no raw PII in audit payloads" rule |

**Not stored:** raw MFA codes (TOTP secret is stored *encrypted*, email/
recovery codes are only ever hashed), plaintext passwords (argon2 hashes
only), payment data (the template doesn't handle payments), device
fingerprints beyond `user_agent`.

## 3. Retention

Automated retention sweeps run on the maintenance worker
([`services/retention.py`](../src/ameli_web/accounts/services/retention.py)),
scheduled by `ameli-app-template-*-maintenance.timer`. The
sweep is itself audited (`retention_sweep` event); see
[`OPERATIONS.md` → "Data retention sweep"](OPERATIONS.md#data-retention-sweep-maintenance-worker).

| Store | Default window | Tunable |
|---|---|---|
| `UserSession` (revoked) | **30 days** | `sessions_revoked_max_age_days` |
| `OutboundEmail` (sent) | **30 days** | `outbound_email_sent_max_age_days` |
| `EmailChangeRequest` (resolved) | **30 days** | `email_change_resolved_max_age_days` |
| `MFAEmailChallenge` (consumed) | **7 days** | `mfa_email_challenge_consumed_max_age_days` |
| `ThrottleCounter` | **1 day** | `throttle_counter_max_age_days` |
| `AuditEvent` | **∞ by default** (audit chain protects itself; disable by omitting `audit_max_age_days`) | `audit_max_age_days` |
| `User` (deleted via `delete_my_account`) | Immediate (see §6) | — |

Live sessions and unresolved email changes are never swept.

## 4. Confidentiality controls

### At rest
- **Passwords** — argon2 via Django's password hashers; PBKDF2/BCrypt/
  Scrypt supported as legacy fallback ([`auth.py`](../src/ameli_web/settings/auth.py)).
- **MFA TOTP secret** — Fernet (AES-128-CBC + HMAC-SHA256) with
  `AMELI_APP_MFA_ENCRYPTION_KEY`; unset in dev falls back to plaintext.
  Rotation runbook: [`OPERATIONS.md` → "Secret rotation"](OPERATIONS.md#secret-rotation).
- **MFA email code** — keyed HMAC via `salted_hmac(secret_key, code)`
  since v0.5.5 (previously bare SHA-256, which was DB-brute-forceable in
  ~10⁶ ops).
- **MFA recovery codes** — hashed at insertion; raw code only shown once
  during enrollment.
- **Audit log** — hash chain with HMAC (`AUDIT_HMAC_KEY`) for tamper
  detection ([`services/audit.py`](../src/ameli_web/accounts/services/audit.py));
  verified nightly by `ameli-app-*-verify-audit.timer`.
- **Avatars** — pipeline strips **EXIF + GPS** on upload (WebP re-encode
  drops the entire metadata block, [`services/images.py:12`](../src/ameli_web/accounts/services/images.py)),
  then AV-scanned before storage.

### In transit
- **TLS** — production reverse proxy (Caddy on `ha-report2`) terminates
  TLS with HSTS `max-age=31536000`. `SESSION_COOKIE_SECURE = CSRF_COOKIE_SECURE = True` when `SECURE_SSL_REDIRECT`.
- **Cookies** — `__Host-` prefix, `HttpOnly`, `SameSite=Lax`
  ([`cookies.py`](../src/ameli_web/settings/cookies.py)).

### Audit payloads
Audit events must record **what happened** without duplicating raw PII.
Actor is the user id/username; target is a stable identifier. Do NOT put
raw email bodies, passwords, tokens, or MFA codes into `payload`. The
existing services follow this — a new service adding a new event type
should keep the pattern.

## 5. Logs discipline (no PII)

Application logs go to `journalctl` (systemd) or stdout (compose). ASVS
V8.3.1 forbids PII in logs. Enforcement:

- Exception messages from third-party libs are wrapped before logging
  where they routinely contain recipients or endpoints:
  [`services/email_queue.py:147`](../src/ameli_web/accounts/services/email_queue.py),
  [`accounts/av.py:_redact`](../src/ameli_web/accounts/av.py).
- Request/response middleware does **not** log request bodies.
- CSP `report-uri` is not configured to a third party by default; if the
  operator points it somewhere, the payloads (URI, blocked source) do
  not carry request bodies.

## 6. User rights (as implemented)

| Right | Endpoint | Notes |
|---|---|---|
| **Access** | `GET /profile` | The profile page renders every field the app stores about the user, plus session list and MFA status. |
| **Rectification** | `POST /profile` (form fields) | Users edit `display_name`, `email` (double-opt-in), theme, avatar, MFA. |
| **Erasure** | `POST /profile/delete-account/` ([`services/user.py:552`](../src/ameli_web/accounts/services/user.py); route [`urls.py:34`](../src/ameli_web/accounts/urls.py)) | Self-service, requires current-password confirmation. Cascades via `on_delete=CASCADE` to `UserSession`, `MFARecoveryCode`, `MFAEmailChallenge`, `EmailChangeRequest`. `AuditEvent` rows referencing the user are kept (see §8). |
| **Restriction** | Admin: `enabled=False` sets the account to "disabled". Users cannot self-restrict; contact the operator. |
| **Session management** | `POST /profile/sessions/<key>/revoke` | Revoke individual sessions; retention sweep prunes them after 30 d. |
| **MFA management** | `/profile#security` | Enable/disable TOTP, enable/disable email 2FA, regenerate recovery codes. |
| **Object to processing** | — | Not applicable at the template level (no analytics/marketing processing shipped). |
| **Data portability** | **Not implemented at the template level.** | The operator can grant it via admin export or add an app-level `/profile/export/` endpoint. Documented gap. |

## 7. Third-party processors

The template calls out to these external services when the operator
configures them. Each is optional except SMTP:

| Processor | What leaves the host | Configured via | Default |
|---|---|---|---|
| **SMTP relay** | `to_emails`, subject, body of transactional mail (auth alerts, MFA email codes, password reset, email-change confirm) | `AMELI_APP_EMAIL_*` env / `app.yaml` | `console` backend in dev; operator picks the relay for prod |
| **HIBP (Have I Been Pwned)** | k-anonymity prefix (5-char SHA-1) of the candidate password on *set*/*change* — never the password itself, never the account | `AMELI_APP_HIBP_PASSWORD_CHECK` | **OFF** by default ([`integrations.py:59`](../src/ameli_web/settings/integrations.py)) |
| **AV scanner** | Uploaded avatar bytes | `AMELI_APP_AV_ICAP_ENDPOINT` | Off by default; deploy-configurable |
| **OpenTelemetry collector** | Traces/metrics — no request bodies, but URL paths + status codes | `AMELI_APP_OTEL_*` | Off by default |

Nothing else phones home. There is no analytics SDK, no ad tracker, no
error-reporting SaaS wired in.

## 8. Audit log vs erasure — the trade-off

`AuditEvent.payload` records actions (`user_created`, `login_failed`,
`mfa_disabled`, ...) and references the actor + target by identifier.
Rows are kept indefinitely by default (chain integrity) and are NOT
cascade-deleted when a user runs `delete_my_account`. The trade-off:

- **Keep audit rows**: hash-chain integrity + regulatory/security
  evidence retained. Reference to the deleted user is by numeric id and
  event action; no raw email/password. This is the default.
- **Prune audit rows**: enabling `audit_max_age_days` in the retention
  sweep re-chains survivors (services/audit.py handles the re-stamp)
  and drops rows past the cutoff. Chain integrity is preserved forward;
  the link to the pruned head is sacrificed. Use only when a
  jurisdiction demands it and the operator accepts the trade-off.

## 9. Backups

Backups (see `OPERATIONS.md` → "Backup + restore") contain a Postgres
dump of the whole DB (including personal data), the deploy's
`${DATA_DIR}` (user-uploaded avatars) and `${ETC_DIR}` (config/env
files — secrets). Tunables:

- **Encryption**: set `AMELI_APP_BACKUP_GPG_RECIPIENT` to require GPG
  encryption of archives that leave the host. Recommended for prod.
- **Retention**: `AMELI_APP_BACKUP_RETENTION_DAYS` (default 30) prunes
  old archives.
- **Off-host**: the template ships the archive; moving it off-host is
  operator responsibility.

An erasure request must remember to also purge the user from **any
backup restored later**. This is a general limitation of encrypted
snapshot backups (not template-specific); document it in the operator's
own privacy notice if backups are retained past the erasure horizon.

## 10. What the operator MUST decide per deploy

The template ships the *technical* controls above. Every real deploy
needs the operator to also:

1. **Declare the legal basis** (contract, legitimate interest, consent,
   legal obligation — jurisdiction-dependent) for each processing
   activity, and publish a user-facing privacy notice.
2. **Name a data controller** (and DPO if applicable).
3. **Disclose cross-border transfers** — the SMTP relay, AV/HIBP
   endpoints, OTel collector may live outside the user's jurisdiction;
   disclose which and under what safeguards (SCCs, etc.).
4. **Set retention windows** in `retention.py` call sites if the
   defaults do not match your jurisdiction / policy. Document what you
   picked and why.
5. **Publish an incident response process** — the template records the
   evidence (audit log + backups); the disclosure timeline and channels
   are policy, not code.
6. **Portability endpoint** — if the deploy needs GDPR-style
   portability, add a `/profile/export/` view returning the user's
   `User` row + related tables as JSON. Not shipped by default.
7. **Cookie / consent banner** — the template ships only strictly
   necessary cookies (session, CSRF); if the deploy adds analytics /
   marketing later, a consent flow is the operator's addition.

## 11. Change log

- **2026-07-17** — initial document; consolidates existing controls, marks
  data-portability as a documented gap. `docs/DOCUMENTATION_PLAN.md`
  bucket "productive/critical" closed alongside the SBOM procedure.
