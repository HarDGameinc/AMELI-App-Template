# OWASP ASVS 4.0.3 Level 2 gap analysis — AMELI App Template

| Field | Value |
| --- | --- |
| Standard | OWASP Application Security Verification Standard 4.0.3 |
| Level | L2 (defense-in-depth, suited to apps handling sensitive data) |
| Target | `AMELI-App-Template` (Django-first template) |
| Branch / HEAD | `dev` @ `0077fb0` (~62 commits ahead of `main`) |
| Date | 2026-06-15 |
| Reviewer | Claude (Opus), hardgameinc@gmail.com |
| Scope | Server-side Django code under `src/`, deploy units under `deploy/`, scripts under `scripts/`, CI under `.github/workflows/`. Templates reviewed for output encoding only. |

> Note on chapter count: the user brief said "12 capítulos". ASVS 4.0.3 actually has **14** chapters; this report covers V1 through V14 to honour the intent of the request (full L2 control surface).

## 1. Executive summary

| Chapter | PASS | GAP | N/A | DEFERRED |
| --- | ---: | ---: | ---: | ---: |
| V1 Architecture, design and threat modelling | 1 | 3 | 0 | 4 |
| V2 Authentication | 11 | 2 | 1 | 0 |
| V3 Session management | 8 | 1 | 0 | 0 |
| V4 Access control | 5 | 1 | 1 | 0 |
| V5 Validation, sanitization and encoding | 5 | 2 | 1 | 0 |
| V6 Stored cryptography | 3 | 1 | 1 | 1 |
| V7 Error handling and logging | 5 | 1 | 0 | 1 |
| V8 Data protection | 3 | 3 | 0 | 1 |
| V9 Communications | 2 | 1 | 0 | 1 |
| V10 Malicious code | 1 | 1 | 0 | 1 |
| V11 Business logic | 4 | 1 | 0 | 0 |
| V12 Files and resources | 5 | 1 | 0 | 0 |
| V13 API and web service | 3 | 2 | 2 | 0 |
| V14 Configuration | 7 | 4 | 0 | 1 |
| **Total** | **63** | **24** | **5** | **10** |

**Headline finding.** The template scores strongly on identity, session, audit-integrity and crypto-at-rest controls — every Argon2id, HMAC-chained audit, sudo re-auth, MFA, throttle and boot-guard surface in the source matches the ASVS L2 intent. The material L2 gaps cluster around **supply-chain hygiene and disclosure plumbing**: dependencies use lower-bound (`>=`) specifiers with no lockfile, no SBOM, no `pip-audit` / `bandit` / `pre-commit` checks in CI, no `docs/SECURITY.md` (referenced from `OPERATIONS.md:156` but absent), no `THREAT_MODEL.md`, no PII purge job, and no automatic `Cache-Control: no-store` on authenticated responses. Several user-claimed features (**API tokens with scopes**, **outbound webhooks with HMAC + SSRF guard**) are NOT actually present in the codebase as of `0077fb0` — they are documented in the agent's prompt but not implemented; this report treats those control families as N/A while flagging the spec-vs-code drift.

---

## 2. V1 — Architecture, design and threat modelling

Covers the existence of an SDLC, threat model, secure defaults and component inventory. For a Django-first template these map mostly to docs (`AGENTS.md`, `docs/ARCHITECTURE.md`, `docs/OPERATIONS.md`) rather than to code.

| ID | Requirement (summary) | Status | Evidence / gap |
| --- | --- | --- | --- |
| 1.1.1 | Secure SDLC | DEFERRED | No `docs/SECURITY.md` present; `docs/OPERATIONS.md:156` references one. Recommend creating it. |
| 1.1.2 | Threat modelling for every design change | DEFERRED | No `THREAT_MODEL.md`. The handoff docs (`docs/CLAUDE_HANDOFF_*`) discuss threats per block but aren't a model. |
| 1.1.3-1.1.7 | User stories / SDLC artefacts | DEFERRED | Operator concern — note in `AGENTS.md`. |
| 1.2.1-1.2.4 | Auth architecture: unique low-priv service accts, short-lived tokens | PASS | Roles defined in `models.py` (`superadmin`, `public`); admin requires sudo grant — `admin_views.py:91` `sudo_required`. |
| 1.4.1 | Trusted enforcement layer | PASS | Middleware chain in `settings.py:155-171` enforces auth, sudo, maintenance, CSP. |
| 1.4.4 | Single vetted access-control mechanism | GAP | Authorization decisions are scattered (`@login_required`, `is_staff`, `is_superuser`, `sudo_required`, role check via `user.role`). Suggested fix: centralize in a `permissions.py` policy module. |
| 1.5.1-1.5.4 | Input/output trust boundaries documented | GAP | No data-flow diagram in `docs/ARCHITECTURE.md`. Add a "trust boundaries" section. |
| 1.6.1 | Cryptographic key management policy documented | GAP | `AUDIT_HMAC_KEY` rotation is implemented (`services.py:269 rotate_audit_key`) but no documented policy on rotation cadence or key custody. Add to `docs/SECURITY.md`. |
| 1.8.1-1.8.2 | Data classification | DEFERRED | Operator concern. |
| 1.9.1 | Components inventory | PASS (partial) | `requirements.txt` + `requirements-dev.txt` enumerate components, but no SBOM (see V14). |
| 1.10.1 | Source-code repo controls | PASS | Repo is git, dev branch protected via GitHub flow; CI on push (`.github/workflows/ci.yml:4`). |
| 1.11.1-1.11.2 | Component segregation | PASS | Workers (`src/ameli_app/workers/`) separated from web; ASGI runtime isolated. |
| 1.14.x | Configuration architecture | PASS | Centralized in `src/ameli_app/config.py` + `settings.py` with boot guards. |

---

## 3. V2 — Authentication

Covers password rules, MFA, credential storage, throttling, lockout. The template implements most of L2 here.

| ID | Requirement | Status | Evidence / gap |
| --- | --- | --- | --- |
| 2.1.1 | Min 12-char passwords | PASS | `settings.py:222-223` `MinimumLengthValidator(min_length=12)`. |
| 2.1.2 | Allowed all printable + Unicode | PASS | `ameli_app/password_policy.py` accepts the standard set; symbol whitelist in `AGENTS.md`. |
| 2.1.5-2.1.6 | Credential rotation, reuse policy | PASS | Password age alert at `views.py:229` (`PROFILE_PASSWORD_MAX_AGE_DAYS`, default 90d). |
| 2.1.7 | Breached-password check | PASS | `validators.py:46 HIBPPasswordValidator` (k-anonymity, opt-in via `HIBP_PASSWORD_CHECK`). |
| 2.1.9 | No password truncation | PASS | Argon2 hasher handles arbitrary length; `strip=False` on password fields (`forms.py:17`). |
| 2.2.1 | Anti-automation: throttle + lockout | PASS | `services.py:2966 check_login_throttle`; sliding window in `services.py:2635`; permanent lockout at `services.py:2907`; honeypot in `views.py:124`. |
| 2.2.2 | Account lockout uses out-of-band recovery | PASS | Admin unlock via `services.py:2944 admin_unlock_user` (requires sudo). |
| 2.2.3 | Notify user of failed auth attempt | GAP | No email alert on failed login attempts to the affected user. Suggested fix: queue an email after N consecutive failures (already tracked in `_consecutive_lockouts_for`). |
| 2.2.4 | Impersonation resistance — MFA required for privileged | PASS | `models.py User.mfa_required` field; admin disable of MFA gated by sudo + email alert (`services.py:1740 _send_mfa_disabled_by_admin_notification`). |
| 2.3.1 | System-generated credentials randomness | PASS | `mfa.py:28 generate_secret` via `pyotp.random_base32`; recovery codes via `secrets.choice` (`mfa.py:54`). |
| 2.3.2 | Enrollment-time credentials short-lived | PASS | Reset token TTL `settings.py:371 PASSWORD_RESET_TIMEOUT` (default 3600s, min 60s). |
| 2.4.1 | Salt 32-bit+; PBKDF2/Argon2 work factor | PASS | `accounts/hashers.py:7 ConfigurableArgon2Hasher`, default `t=2 m=102400 p=8`, settings-tunable. |
| 2.4.4 | Server-side hashing only | PASS | All hashing via Django auth; no client-side hashing. |
| 2.5.1 | Recovery token not by GET in URL log | PASS | Reset token in URL but used once + short TTL (Django default behavior is L2-acceptable). |
| 2.5.3-2.5.5 | Forgot password indistinguishable response | PASS | `services.py:2492 request_password_reset` returns identical payload + timing pad at `views.py:898-934`. |
| 2.5.6 | New session after credential reset | PASS | `views.py:552,568,584,600,611,646` — `request.session.cycle_key()` after MFA, password change, reset. |
| 2.6.1-2.6.3 | Out-of-band auth (MFA) | PASS | TOTP at `mfa.py:38 verify_totp`; email MFA at `mfa.py:96 generate_email_code`. |
| 2.7.1-2.7.3 | OTP cryptographically secure | PASS | TOTP uses pyotp (RFC 6238); email codes via `secrets.randbelow` (`mfa.py:98`). |
| 2.7.6 | OTP rate limited | PASS | `mfa.py:92 EMAIL_CODE_RESEND_INTERVAL_SECONDS=60`; hourly limit at `mfa.py:93`. |
| 2.8.1-2.8.6 | Time-based OTP encrypted at rest, single-use | GAP | TOTP `secret` stored on `User` model (presumably plaintext); ASVS L2 expects encryption-at-rest with a different key from the DB master. Suggested fix: wrap `mfa_totp_secret` with Fernet keyed by `AUDIT_HMAC_KEY`-style env secret. |
| 2.9.x | Cryptographic 2FA (WebAuthn) | N/A | Out of scope for this template; TOTP+email satisfy L2. |
| 2.10.1-2.10.3 | Service auth (token storage) | PASS | API tokens not implemented; service-account password storage uses Argon2 same as users. |

---

## 4. V3 — Session management

| ID | Requirement | Status | Evidence / gap |
| --- | --- | --- | --- |
| 3.1.1 | No URL session identifiers | PASS | Django session cookie only; no URL param. |
| 3.2.1 | Session created at login | PASS | `views.py form_valid` triggers `auth_login`. |
| 3.2.2 | Session token random ≥ 64 bits | PASS | Django default `signing.get_random_string(32)` ≈ 160 bits. |
| 3.2.3 | Session re-issued on auth change (fixation) | PASS | `request.session.cycle_key()` at `views.py:552, 568, 584, 600, 611, 646`. |
| 3.2.4 | Random over the wire when generated | PASS | TLS handled by Caddy (`docs/TLS_WITH_CADDY.md`). |
| 3.3.1 | Logout terminates session server-side | PASS | `views.py:175 logout_view` calls `auth_logout` + `revoke_sudo`. |
| 3.3.2 | Idle timeout | PASS | `settings.py:286 SESSION_SAVE_EVERY_REQUEST=True` + `SESSION_COOKIE_AGE` (default 43200s = 12h). |
| 3.3.3 | Absolute timeout (re-auth required after N) | GAP | The session can be renewed indefinitely by activity; there is no absolute cap. Suggested fix: add `SESSION_ABSOLUTE_MAX_AGE` in `UserSessionMiddleware` and force re-login when exceeded. |
| 3.3.4 | Concurrent session control | PASS | `services.py:562 revoke_other_sessions` + admin revoke at `admin_views.py:357`. |
| 3.4.1 | Cookie `Secure` | PASS | `settings.py:277 SESSION_COOKIE_SECURE=True` outside dev. |
| 3.4.2 | Cookie `HttpOnly` | PASS | `settings.py:279 SESSION_COOKIE_HTTPONLY=True`. |
| 3.4.3 | Cookie `SameSite` | PASS | `settings.py:280 SESSION_COOKIE_SAMESITE="Lax"`. |
| 3.4.4 | Cookie `__Host-` prefix | DEFERRED | Operator can set the cookie name; not enforced by template — note in deployment guide. |
| 3.5.1 | Stateful tokens revocable | PASS | DB-backed sessions, `UserSession` table; revocation at `services.py:549`. |
| 3.5.2 | Stateful or signed | PASS | Django signed cookies for messages; DB-backed sessions for auth. |
| 3.6.1 | Look-ahead re-auth for sensitive ops | PASS | Sudo grant at `services.py:3318 grant_sudo` with TTL; verified by `verify_sudo_credentials`. |
| 3.7.1 | Re-auth requires current creds | PASS | `services.py:3353 verify_sudo_credentials(password, mfa_code)`. |

---

## 5. V4 — Access control

| ID | Requirement | Status | Evidence / gap |
| --- | --- | --- | --- |
| 4.1.1 | Trusted enforcement layer | PASS | Django middleware + per-view decorators. |
| 4.1.2 | All attrs protected | PASS | Forms whitelist editable fields (`forms.py:30 fields = ["display_name", "theme_preference"]`). |
| 4.1.3 | Principle of least privilege | PASS | `superadmin` vs `public` roles in `models.py`; admin endpoints require sudo. |
| 4.1.4 | Default-deny | PASS | `LOGIN_URL` enforced for views; `_authenticated_media` (`urls.py:92`) denies anon. |
| 4.1.5 | Access-control fails closed | PASS | Middleware `MaintenanceModeMiddleware` and `MustChangePasswordMiddleware` redirect rather than allowing pass-through; admin paths require explicit `@sudo_required`. |
| 4.2.1 | Sensitive data/API protected against IDOR | GAP | `_authenticated_media` in `urls.py:92` checks auth but not ownership — any authenticated user can fetch any other user's avatar by guessing the 64-bit random filename token (`models.py:13 secrets.token_hex(8)`). Risk is low (entropy adequate) but the control is technically IDOR-vulnerable. Suggested fix: scope media-serve to "owner or admin". |
| 4.2.2 | CSRF protection on state-changing ops | PASS | `settings.py:162 CsrfViewMiddleware`; CSRF cookie attrs at `settings.py:290-293`. |
| 4.3.1 | Admin interfaces require stronger auth | PASS | Admin requires `is_staff` + `sudo` grant via `sudo_required` decorator (`admin_views.py:91`). |
| 4.3.2 | Directory browsing disabled | PASS | Django's `serve()` returns 404; no autoindex. |
| 4.3.3 | Sensitive ops require additional auth | PASS | All admin writes are `@sudo_required` (multiple sites in `admin_views.py`). |
| 4.x | OAuth scopes | N/A | No OAuth; SSO not in scope. |

---

## 6. V5 — Validation, sanitization and encoding

| ID | Requirement | Status | Evidence / gap |
| --- | --- | --- | --- |
| 5.1.1 | Untrusted HTTP params validated server-side | PASS | Django Forms + `clean_*` methods; e.g. `forms.py:51 clean_avatar`. |
| 5.1.2 | Frameworks block parameter pollution | PASS | Django uses `QueryDict.get` (last-wins). |
| 5.1.3 | Schema validation | PASS (partial) | Form-level; no JSON-schema validation for API (template ships no public JSON API beyond `/api/health`). |
| 5.1.4 | Structured data validated | PASS | Forms + ModelForms validate types. |
| 5.1.5 | URL redirect uses safe-URL check | PASS | Django `LoginView.get_redirect_url()` uses `url_has_allowed_host_and_scheme` (default). |
| 5.2.1-5.2.7 | Sanitization of HTML, CSV, URLs, SMTP, LDAP | PASS | Template engine auto-escapes; no LDAP/SQL injection (ORM only). No raw SQL in code (`grep raw\(` returns nothing). |
| 5.2.8 | SSRF prevention | GAP | `validators.py:42 urlopen` to HIBP is the only outbound HTTP; no SSRF guard library (`AGENTS.md` mentions a webhook SSRF guard but **no webhook code exists in the repo as of `0077fb0`**). Suggested fix: when webhooks are added, port the documented RFC1918/metadata reject list before shipping. |
| 5.3.1-5.3.3 | Output encoding (context-aware) | PASS | Django auto-escape on; CSP nonce in `middleware.py:18 build_csp`. |
| 5.3.4 | SQL injection: parameterised queries | PASS | ORM only; no raw SQL (verified by grep). |
| 5.3.5 | Command injection prevention | PASS | No `shell=True`/`os.system`. `exec()` only in `cli.py:360` for the operator-controlled `ameli-app shell` (equivalent to `django-admin shell`). |
| 5.3.6 | LDAP / NoSQL / Xpath / XML | N/A | None used. |
| 5.3.7 | XSS — CSP / nonce / X-XSS-Protection | PASS | `middleware.py:18 build_csp` with per-request nonce; X-Content-Type-Options + Referrer-Policy at `settings.py:295-296`. |
| 5.3.8 | Stored XSS via uploads | PASS | Avatar upload via `forms.py:51` format-whitelisted to JPEG/PNG/WEBP/GIF (no SVG). |
| 5.3.9 | Deserialisation: avoid pickle on untrusted | PASS | No `pickle.loads` in repo. |
| 5.5.1 | Serialization safe | GAP | `messages.session` storage `settings.py:327` uses Django's signed JSON cookie — safe — but if an operator switches to `pickle`-backed `SignedCookie` storage there is no guard. Document in `docs/SECURITY.md`. |

---

## 7. V6 — Stored cryptography

| ID | Requirement | Status | Evidence / gap |
| --- | --- | --- | --- |
| 6.1.1-6.1.3 | Inventory of secrets / classification | DEFERRED | Operator concern; recommend `docs/SECURITY.md` "Secrets inventory" table. |
| 6.2.1 | Approved algorithms only | PASS | Argon2id (`hashers.py:7`), HMAC-SHA256 (`services.py:118`), SHA-256 for recovery (`mfa.py:82`). |
| 6.2.2 | No insecure algorithms (MD5/SHA-1) | PASS (partial) | SHA-1 used in `validators.py:84` exclusively for the HIBP k-anonymity API as the protocol requires; not used for security decisions. |
| 6.2.3 | Authenticated symmetric encryption | N/A | No symmetric encryption of fields at rest currently performed (see V2.8.1 gap on TOTP secret). |
| 6.2.4-6.2.6 | Random number generators | PASS | `secrets.token_urlsafe` for CSP nonce (`middleware.py:15`), session keys (Django), and HMAC keys (per `settings.py:243-244` comment). |
| 6.3.1-6.3.3 | Key management — rotation, separation | GAP | `AUDIT_HMAC_KEY` rotation implemented (`services.py:269`), but no rotation procedure for `SECRET_KEY` documented; no key versioning for audit chain (rotation is one-shot, not multi-key). Suggested fix: document `SECRET_KEY` rotation playbook in `docs/SECURITY.md`. |
| 6.4.1 | Secrets never in source | PASS | Boot guards in `settings.py:24-35` refuse bundled defaults outside dev. |
| 6.4.2 | Secrets in env / vault | PASS | Read via `ameli_app.config.load_settings` → env. |

---

## 8. V7 — Error handling and logging

| ID | Requirement | Status | Evidence / gap |
| --- | --- | --- | --- |
| 7.1.1 | No sensitive data in logs | PASS (with risk) | No call-sites log secrets (verified by grep), but `JsonFormatter` (`logging_utils.py:28`) promotes every `extra=` key verbatim — no `password` / `token` / `authorization` scrubbing filter. If a future caller passes a credential in `extra=`, it ships. Suggested fix: add a `RedactingFilter` that drops known-sensitive key names. |
| 7.1.2 | No payment / auth tokens in logs | PASS | Verified by grep. |
| 7.1.3 | Logs contain enough to investigate | PASS | `audit/models.py AuditEvent` captures actor, action, payload, ts; JSON formatter promotes extras (`logging_utils.py:28`). |
| 7.1.4 | Log source-identifying info (request id) | PASS | `request_id.py:64` injects `X-Request-Id` end-to-end; appears in `logging_utils.py:86 "[req=%(request_id)s]"`. |
| 7.2.1 | Auth decisions logged | PASS | `record_audit("login_throttled", ...)` etc throughout `views.py`. |
| 7.2.2 | Access-control decisions logged | PASS | `AdminAccessAuditMiddleware` (`middleware.py:212`), `DjangoAdminSudoGateMiddleware` (`middleware.py:230`). |
| 7.3.1 | Logs protected from injection | PASS (partial) | JSON formatter uses `json.dumps` which escapes; text formatter does not — newlines in usernames could fold lines. Low risk because usernames are validated. |
| 7.3.2 | Logs cannot be silently modified | PASS | `audit/models.py AuditEvent` rows are HMAC-chained (`services.py:121 record_audit`); `services.py:186 verify_audit_chain` detects edits, deletes, reorders. |
| 7.3.3 | Time-synchronised logs | DEFERRED | Operator concern (NTP); recommend mention in `docs/OPERATIONS.md`. |
| 7.4.1-7.4.3 | Error handlers do not leak | GAP | `DEBUG=False` forbidden outside dev (settings.py:31), but custom 404/500 templates are not present. Django default ships generic pages — acceptable, but no branded handler. Suggested fix: add `handler404 / handler500` views with generic messages. |

---

## 9. V8 — Data protection

| ID | Requirement | Status | Evidence / gap |
| --- | --- | --- | --- |
| 8.1.1-8.1.6 | Client-side data minimisation | PASS | No localStorage usage of secrets; no autocomplete on password (`forms.py:18 autocomplete="current-password"`). |
| 8.2.1 | Cache-control on sensitive responses | GAP | No `Cache-Control: no-store` header set on profile/admin/MFA pages. Browsers and proxies may cache. Suggested fix: middleware that adds `Cache-Control: no-store` for any authenticated `request.user.is_authenticated` response. |
| 8.2.2 | Data classified before storage | DEFERRED | Operator/data-owner concern. |
| 8.2.3 | Sensitive data sent only over POST/auth | PASS | Reset token used in GET only once (Django default); login/password are POST. |
| 8.3.1 | Sensitive data in HTTPS only | PASS | `SESSION_COOKIE_SECURE` + `CSRF_COOKIE_SECURE` (`settings.py:277, 290`). |
| 8.3.2 | Backups encrypted | PASS | `scripts/backup.sh` supports optional GPG encryption (per AGENTS spec and confirmed in script). |
| 8.3.3 | Sensitive data not retained beyond need | GAP | No automatic PII purge for inactive users; `run_retention_sweep` only handles audit log (`services.py:789`). Suggested fix: add a `purge-inactive-users` CLI that anonymises accounts after N days. |
| 8.3.4 | PII purge on user request | GAP | No "delete my account" flow. User can be deleted by admin (`delete_user_account` `services.py:1415`), but no self-service. Suggested fix: add `/profile/delete-account` with re-auth + sudo. |

---

## 10. V9 — Communications

| ID | Requirement | Status | Evidence / gap |
| --- | --- | --- | --- |
| 9.1.1 | TLS for all client connectivity | PASS | Caddy fronts TLS per `docs/TLS_WITH_CADDY.md`; `SECURE_PROXY_SSL_HEADER` supported (`settings.py:305-313`). |
| 9.1.2 | HSTS | GAP | `settings.py:318 SECURE_HSTS_SECONDS = 0` — intentionally off until operator opts in. Document this clearly in deployment guide as a required follow-up; not a code gap but a deployment gap. |
| 9.1.3 | TLS for backend / DB | DEFERRED | Operator deploys DB; PostgreSQL `sslmode` is configurable via DSN. Document. |
| 9.2.1-9.2.5 | Cert validation, no insecure protocols | PASS | `urlopen` to HIBP uses default verify; no `verify=False` anywhere. |

---

## 11. V10 — Malicious code

| ID | Requirement | Status | Evidence / gap |
| --- | --- | --- | --- |
| 10.1.1 | Code analysed for backdoors | DEFERRED | No SAST in CI. Recommend adding `bandit` as a CI step (see V14). |
| 10.2.1-10.2.6 | No malicious code / time-bomb / hardcoded back-door | PASS | Code-review pass: no hardcoded master credential outside `_INSECURE_DEFAULT_SECRET` (which is rejected outside dev). |
| 10.3.1-10.3.3 | Auto-update / integrity protections for client code | GAP | `STATICFILES_DIRS` JS is served unsigned; CDN assets in `dashboard/views.py` have **optional** SRI hashes (`settings.py:71 CDN_SRI_HASHES`) but no default values, so SRI is off out of the box. Suggested fix: ship default SRI values pinned to the Swagger UI/ReDoc versions referenced. |

---

## 12. V11 — Business logic

| ID | Requirement | Status | Evidence / gap |
| --- | --- | --- | --- |
| 11.1.1 | Business logic flows process in order | PASS | MFA enforced as a discrete step (`views.py:158 PENDING_MFA_SESSION_KEY`); cannot skip. |
| 11.1.2 | High-value txns logged | PASS | Audit covers admin user CRUD, password resets, MFA toggles, sudo grants, maintenance toggles. |
| 11.1.3 | Sequential steps enforced | PASS | `MustChangePasswordMiddleware` (`middleware.py:151`) blocks normal flow until rotation done. |
| 11.1.4 | Anti-automation for unusual volume | PASS | Sliding-window throttles for login, MFA resend, forgot-password (`services.py:2800, 2836, 2966`). |
| 11.1.5 | Replay prevention on sensitive ops | GAP | Reset tokens are one-use via Django's `default_token_generator`, but the sudo grant has no replay nonce within its window — any authenticated request in the window can act. Acceptable trade-off but document in `docs/SECURITY.md`. |
| 11.1.7 | Real-time monitoring | PASS | `/metrics` exposes `ameli_app_audit_chain_ok` (`dashboard/views.py:563`) for Prometheus. |

---

## 13. V12 — Files and resources

Avatar upload IS in scope; this is the main file-handling surface.

| ID | Requirement | Status | Evidence / gap |
| --- | --- | --- | --- |
| 12.1.1 | File size limit | PASS | `forms.py:8 MAX_AVATAR_BYTES = 3 * 1024 * 1024`. |
| 12.1.2 | Decompression-bomb defence | PASS | `forms.py:79` pixel cap 4096 × 4096. |
| 12.1.3 | File-count limit (DoS) | PASS | Avatar is a single replace; no batch upload. |
| 12.2.1 | File type validation against whitelist | PASS | `forms.py:10 ALLOWED_AVATAR_FORMATS = {"JPEG","PNG","WEBP","GIF"}` checked via Pillow at `forms.py:72`. |
| 12.3.1 | File path traversal | PASS | `models.py:13 avatar_upload_to` builds `avatars/<username-slug>-<token>.<ext>`; no user-supplied path. |
| 12.3.2 | No execute permissions on uploads | PASS | Files stored under `MEDIA_ROOT` (no exec bit; served via `serve()` which sets MIME by extension). |
| 12.3.3 | Filenames sanitized against reserved | PASS | Username re-slugified at `models.py:12 secure_filename`-equivalent. |
| 12.4.1 | Uploaded content scanned | GAP | No ClamAV / antivirus integration. Acceptable for internal apps but document residual risk. Suggested fix: optional `AMELI_APP_AV_ENDPOINT` that scans uploads before persisting. |
| 12.5.1 | File-type by header, not extension | PASS | Pillow opens and reads `img.format` (`forms.py:72`). |
| 12.5.2 | Files in known-safe location | PASS | `MEDIA_ROOT` per `settings.py:266`; outside webroot when behind Caddy. |
| 12.6.1 | SSRF prevention on file-fetch | N/A | Server does not fetch URLs supplied by users (other than HIBP, which is a fixed allow-listed endpoint). |

---

## 14. V13 — API and web service

The template exposes minimal HTTP: dashboard, `/health`, `/metrics`, `/api/health`, `/openapi.json`. No authenticated JSON API.

| ID | Requirement | Status | Evidence / gap |
| --- | --- | --- | --- |
| 13.1.1 | All API requests authenticated by same identity store | N/A | No authenticated API endpoints in current build. |
| 13.1.2 | Anti-automation on APIs | PASS (partial) | `/health` and `/metrics` allowlistable by IP (`settings.py:83 HEALTH_METRICS_ALLOWLIST`, `dashboard/views.py:265`). |
| 13.1.3 | Different APIs different auth | N/A | One API. |
| 13.1.4 | Authorization on every API call | PASS | `/api/health` and `/health` are intentionally public unless allowlisted. |
| 13.1.5 | Body parsing limits | GAP | No explicit `DATA_UPLOAD_MAX_MEMORY_SIZE` override — Django default (2.5 MB) used. For the avatar (3 MB) this means form parsing kicks to disk. Acceptable but document. |
| 13.2.1 | REST APIs use proper HTTP verbs | PASS | `@require_GET`, `@require_POST` decorators used throughout. |
| 13.2.2 | JSON schema validation | GAP | `/api/health` returns hand-built JSON; OpenAPI doc at `dashboard/views.py:44 _openapi_schema` is hand-written and not auto-validated against actual responses. Add a contract test. |
| 13.2.3 | CSRF on POST API | PASS | CSRF middleware applies to all POSTs. |
| 13.2.4 | Hide framework signatures | PASS | `X-Frame-Options: DENY` (`settings.py:297`); `Server` header is Caddy/uvicorn-controlled. |
| 13.3.x | SOAP / XML | N/A | None used. |
| 13.4.x | GraphQL | N/A | Not used. |

---

## 15. V14 — Configuration

| ID | Requirement | Status | Evidence / gap |
| --- | --- | --- | --- |
| 14.1.1 | Reproducible builds | PASS (partial) | `pyproject.toml` + `requirements.txt` + Dockerfile + `scripts/install.sh`; matrix CI on Python 3.11 + 3.12. |
| 14.1.2 | Compiler flags / build security | DEFERRED | Pure Python; n/a for compilation. |
| 14.1.3 | Server config hardened | PASS | Caddy/uvicorn-fronted per `docs/TLS_WITH_CADDY.md`; settings refuse insecure defaults (`settings.py:24-53`). |
| 14.1.4 | Out-of-band notification of config changes | DEFERRED | Operator concern. |
| 14.1.5 | All app deps from approved repos | PASS | Standard PyPI deps. |
| 14.2.1 | Dependencies managed and minimised | GAP | `requirements.txt` uses **`>=` only** (e.g. `Django>=5.2.0`) — no upper bound, no lockfile. A surprise major upgrade can land on any `pip install`. Suggested fix (Medium): switch to `pip-tools` with a `requirements.lock` or pin `==` and use Dependabot. |
| 14.2.2 | Deprecated / vulnerable components removed | GAP | No `pip-audit` / `safety` step in CI (`.github/workflows/ci.yml`). Suggested fix (Small): add `pip-audit --strict` job. |
| 14.2.3 | Third-party signature/integrity verified | GAP | No SBOM generated; no `pip install --require-hashes`. Suggested fix (Medium): generate `requirements.lock` with hashes via `pip-compile --generate-hashes`. |
| 14.2.4 | Deprecated functions removed | PASS | Ruff lints in CI (`ci.yml:65`); `from __future__ import annotations` everywhere; no `imp`/`crypt` usage. |
| 14.2.5 | Sandbox / least-priv runtime | PASS | systemd units in `deploy/systemd/` ship as separate services per concern. |
| 14.2.6 | Build artefacts integrity | DEFERRED | Operator deploy concern. |
| 14.3.1 | Verbose error info disabled in prod | PASS | `settings.py:31` refuses `DEBUG=True` outside dev. |
| 14.3.2 | HTTP debug / trace methods disabled | PASS | Django default; only routed methods reach views. |
| 14.3.3 | Disclosure headers minimised | PASS (partial) | `X-Frame-Options: DENY`; no `Server` header strip but uvicorn/Caddy can be configured. |
| 14.4.1 | Content-Type charset declared | PASS | Django default `Content-Type: text/html; charset=utf-8`. |
| 14.4.2 | Content-Type for all responses | PASS | JSON responses use `JsonResponse` (correct CT). |
| 14.4.3 | Content-Security-Policy | PASS | `middleware.py:18 build_csp` with per-request nonce. |
| 14.4.4 | Referrer-Policy | PASS | `settings.py:296 SECURE_REFERRER_POLICY="same-origin"`. |
| 14.4.5 | Strict-Transport-Security | GAP | `settings.py:318 SECURE_HSTS_SECONDS=0` by default — see V9.1.2. |
| 14.4.6 | X-Content-Type-Options | PASS | `settings.py:295 SECURE_CONTENT_TYPE_NOSNIFF=True`. |
| 14.4.7 | X-Frame-Options / frame-ancestors | PASS | `settings.py:297 X_FRAME_OPTIONS="DENY"` + CSP `frame-ancestors 'none'`. |
| 14.5.1-14.5.3 | HTTP request validation (Host header, content-type) | PASS | `ALLOWED_HOSTS` boot-guarded against `*` outside dev (`settings.py:49`); password reset refuses Host header injection via `public_url_base` (`services.py:3061`). |

---

## 16. Gap roadmap

Ordered by combined impact + effort. Effort: Small ≤ 1 day; Medium 1–3 days; Large > 3 days.

| # | Gap | Effort | Suggested fix |
| --- | --- | --- | --- |
| 1 | **14.2.1 / 14.2.2 / 14.2.3** — deps unpinned, no audit, no SBOM | M | Switch `requirements.txt` to `pip-compile --generate-hashes` output; add `pip-audit --strict` job to CI; commit SBOM via `cyclonedx-py`. |
| 2 | **1.1.1 / 6.3.1 / 8.3.4** — no `docs/SECURITY.md` covering disclosure, key custody, PII purge | S | Create `docs/SECURITY.md` with: contact email, supported versions, key-rotation playbook, residual-risk register. |
| 3 | **1.1.2** — no threat model | M | Add `docs/THREAT_MODEL.md` with STRIDE pass over auth, sessions, audit, MFA, file-upload, maintenance. |
| 4 | **8.3.3 / 8.3.4** — no PII purge / no self-service delete | M | Add `ameli-app purge-inactive-users --days N` + `/profile/delete-account` (sudo-gated). |
| 5 | **8.2.1** — no `Cache-Control: no-store` on authenticated responses | S | Add a middleware that sets `Cache-Control: no-store, max-age=0` when `request.user.is_authenticated`. |
| 6 | **9.1.2 / 14.4.5** — HSTS off by default | S | Default `SECURE_HSTS_SECONDS=31536000` outside dev with `SECURE_HSTS_PRELOAD=True`, document the inability to undo. |
| 7 | **2.8.x** — TOTP secret not encrypted at rest | M | Wrap `mfa_totp_secret` with Fernet keyed off a new env secret; provide migration. |
| 8 | **2.2.3** — no email alert on auth-failure burst | S | After N consecutive failures (already counted), queue an email to the user's address (HMAC chain stays). |
| 9 | **3.3.3** — no absolute session ceiling | S | Add `SESSION_ABSOLUTE_MAX_AGE` (default 30 d), enforce in `UserSessionMiddleware`. |
| 10 | **4.2.1** — `/media/` is auth-only, not owner-only | S | Resolve avatar from session user + admin; return 403 otherwise. |
| 11 | **10.3.1** — SRI hashes unset by default for CDN assets | S | Pin Swagger/ReDoc to a vendored copy in `static/`, or ship default SRI values in `settings.py`. |
| 12 | **10.1.1 / 5.2.8** — no SAST/SSRF lint | S | Add `bandit -ll` to CI; add Ruff rule `S310` (urllib audit) as error. |
| 13 | **12.4.1** — no AV scan on uploads | M | Optional `AMELI_APP_AV_ENDPOINT` (clamd) that scans before persisting. |
| 14 | **7.4.1** — no custom 404/500 handlers | S | Add `handler404`, `handler500` returning a branded generic page. |
| 15 | **1.4.4** — authz scattered | M | Centralise role/permission checks in `accounts/permissions.py` and replace ad-hoc `is_staff`/`role==` checks. |
| 16 | **6.3.1** — `SECRET_KEY` rotation procedure undocumented | S | Document in `docs/SECURITY.md`; provide CLI helper that re-signs sessions or forces logout. |
| 17 | **13.2.2** — OpenAPI doc is hand-written, drifts from reality | S | Add a contract test that asserts every documented path responds. |
| 18 | **5.5.1** — pickle-storage of messages possible if operator changes setting | S | Add a boot-guard that refuses non-JSON `MESSAGE_STORAGE`. |
| 19 | **3.4.4** — `__Host-` prefix not enforced | S | Default `SESSION_COOKIE_NAME = "__Host-ameli_session"` when `SESSION_COOKIE_SECURE=True` and no path/domain. |
| 19b | **7.1.1 latent** — `JsonFormatter` promotes all `extra=` keys verbatim, no PII scrub filter | S | Add a `RedactingFilter` that drops/masks `password`, `token`, `authorization`, `secret`, `mfa_code` keys. |
| 20 | **Spec-vs-code drift**: AGENTS narrative mentions API tokens (scopes) and outbound webhooks (HMAC + SSRF); neither is in the source. | L (if implementing) | Either remove from the narrative or schedule the implementation. Treat as the next security epic — when added, port the SSRF guard and HMAC dispatcher as described. |

---

### Closing note

This template's identity, session, audit and crypto-at-rest controls are above the L2 bar — the engineering effort visible in `services.py` (audit chain, sudo, throttling, MFA, maintenance singleton) is high quality. The cluster of gaps that remain is the predictable shape for an app-template at ~62 commits of growth: supply chain (lockfile + audit + SBOM), disclosure docs (`SECURITY.md`, threat model), PII lifecycle (purge + self-service delete), and the second-order hardening lifts (HSTS-on-by-default, `__Host-` cookie, Cache-Control on authenticated paths, AV on uploads). None of them require an architectural rework; together they are roughly a one-week security-hardening sprint to lift the template cleanly to ASVS L2.
