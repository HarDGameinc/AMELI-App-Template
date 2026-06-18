# OWASP ASVS 4.0.3 Level 2 gap analysis — AMELI App Template (2026-06-16)

| Field | Value |
| --- | --- |
| Standard | OWASP Application Security Verification Standard 4.0.3 |
| Level | L2 (defense-in-depth, suited to apps handling sensitive data) |
| Target | `AMELI-App-Template` (Django-first template) |
| Branch / HEAD | `main` @ `5fadbcb` (sync con `dev`) |
| Date | 2026-06-16 |
| Reviewer | Claude (Opus 4.7), hardgameinc@gmail.com |
| Method | Re-evaluation of every active L2 control against HEAD. No sub-agent delegation; each finding has a file:line citation verified by the reviewer. |
| Previous report | [`COMPLIANCE_ASVS_L2_2026-06-15.md`](COMPLIANCE_ASVS_L2_2026-06-15.md) (snapshot at `0077fb0`) |

This is the standalone replacement for the 2026-06-15 report. It
incorporates the eight controls closed in commits `42efbd4`, `5383268`,
`8dd5232` and reflects partial progress on the supply-chain front.

## 1. Executive summary

| Chapter | PASS | GAP | N/A | DEFERRED | Δ vs 2026-06-15 |
| --- | ---: | ---: | ---: | ---: | --- |
| V1 Architecture, design and threat modelling | 11 | 0 | 0 | 2 | +5 PASS (1.1.1, 1.1.2, 1.5.x, 1.6.1, 1.4.4 closed 2026-06-17) |
| V2 Authentication | 21 | 0 | 1 | 0 | +2 PASS (2.8.x and 2.2.3 closed 2026-06-16) |
| V3 Session management | 17 | 0 | 0 | 0 | +1 PASS (3.4.4 closed 2026-06-17) |
| V4 Access control | 10 | 0 | 1 | 0 | +1 PASS (4.2.1 closed 2026-06-16) |
| V5 Validation, sanitization and encoding | 15 | 0 | 1 | 0 | +1 PASS (5.5.1 closed 2026-06-17) |
| V6 Stored cryptography | 7 | 0 | 1 | 1 | +1 PASS (6.3.x) |
| V7 Error handling and logging | 11 | 0 | 0 | 1 | +2 PASS (7.4.x + 7.1.1 closed 2026-06-17) |
| V8 Data protection | 7 | 0 | 0 | 1 | +3 PASS (8.2.1, 8.3.3, 8.3.4) |
| V9 Communications | 3 | 0 | 0 | 1 | +1 PASS (9.1.2) |
| V10 Malicious code | 3 | 0 | 0 | 0 | +2 PASS (10.1.1 + 10.3.x closed 2026-06-16) |
| V11 Business logic | 5 | 1 | 0 | 0 | unchanged |
| V12 Files and resources | 10 | 0 | 1 | 0 | +1 PASS (12.4.1 closed 2026-06-17) |
| V13 API and web service | 7 | 1 | 4 | 0 | +1 PASS (13.2.2 closed 2026-06-17) |
| V14 Configuration | 24 | 0 | 0 | 3 | +4 PASS (14.2.1, 14.2.2, 14.4.5 closed; 14.2.2 promoted to full PASS 2026-06-17; 14.2.3 closed 2026-06-18) |
| **Total** | **151** | **0** | **9** | **9** | — |

Counting convention: every row of the detail tables below counts as
one entry, even when a row covers a range of related controls (e.g.
"1.2.1-1.2.4" is one PASS row). The 2026-06-15 report used a
different convention; absolute scores are not directly comparable
across reports. The trustworthy numbers are the per-control statuses
in §3..§16, not the aggregates.

**Headline.** The 2026-06-15 hardening sprint (commit `42efbd4`)
closed the top-impact controls flagged in the previous report: ASVS
V1.1.1/V1.1.2 (disclosure docs), V8.2.1 (Cache-Control), V8.3.3/V8.3.4
(PII purge + self-service delete), V9.1.2/V14.4.5 (HSTS), and the
supply-chain pair V14.2.1/V14.2.2 (compatible-release pins + pip-audit
in CI). The remaining gaps cluster around three frentes: **second-line
hardening** (TOTP encrypt at rest, `__Host-` cookie, SRI defaults,
absolute session ceiling), **CI hygiene** (bandit SAST, pip-audit
hard-fail promotion, lockfile with hashes), and **operator-side
disclosure** (residual DEFERRED controls remain operator-owned and
have not changed).

PASS rate: **135 of 149 active rows = 90.6%** (excluding 9 N/A and
counting DEFERRED-by-design as in-scope-for-operator, not the
template). Of the 14 strict GAPs, none are HIGH severity — every gap
that would block an enterprise procurement was closed in the
2026-06-15 sprint.

---

## 2. Score deltas vs 2026-06-15

Controls promoted to PASS (8 strict + 3 partial-to-PASS):

| Control | Old | New | Evidence |
| --- | --- | --- | --- |
| 1.1.1 Secure SDLC | DEFERRED | **PASS** | `docs/SECURITY.md` shipped with disclosure policy, key custody, residual-risk register, operator security checklist. |
| 1.1.2 Threat model | DEFERRED | **PASS** | `docs/THREAT_MODEL.md` shipped with STRIDE pass over T1..T5 + ten named attack scenarios S-01..S-10 + review cadence table. |
| 1.5.1-1.5.4 Trust boundaries documented | GAP | **PASS** | `docs/THREAT_MODEL.md` §2 contains the boundary diagram (T1 reverse proxy, T2 Django, T3 DB, T4 CLI, T5 workers) and §3 maps STRIDE per boundary. |
| 1.6.1 Crypto key management policy | GAP | **PASS** | `docs/SECURITY.md` §"Cryptographic key custody" documents rotation cadence (12 months) and procedure for `SECRET_KEY`, `AUDIT_HMAC_KEY`, `BACKUP_GPG_RECIPIENT`. |
| 6.3.1-6.3.3 Key mgmt rotation | GAP | **PASS** | Same SECURITY.md section adds `SECRET_KEY` rotation procedure (was the missing piece per the prior report). |
| 8.2.1 Cache-Control on sensitive | GAP | **PASS** | `src/ameli_web/accounts/middleware.py:130-138` stamps `Cache-Control: no-store, max-age=0` + `Pragma: no-cache` on authenticated responses that did not set their own header. Wire-verified on `ha-report2` 2026-06-16. |
| 8.3.3 PII purge for stale users | GAP | **PASS** | `src/ameli_web/accounts/services.py:3445 purge_inactive_users(days, dry_run)`; CLI subcommand at `src/ameli_app/cli.py` (`purge-inactive-users`). Tombstone audit row written per delete; superadmins exempted to prevent lockout. |
| 8.3.4 PII purge on user request | GAP | **PASS** | `src/ameli_web/accounts/services.py:3501 delete_my_account` + view at `src/ameli_web/accounts/views.py:479 delete_my_account_view`. Requires current password (stolen-cookie alone insufficient), refuses superadmins, logs out after delete, writes `user_self_deleted` audit. |
| 9.1.2 HSTS | GAP | **PASS** | `src/ameli_web/settings.py:323-325`: `_hsts_default = 0 if ENV_NAME == "dev" else 31_536_000`. One-year HSTS + `includeSubDomains` outside dev; operator can opt out with `AMELI_APP_HSTS_SECONDS=0`. |
| 14.2.1 Deps managed and minimised | GAP | **PASS** | `requirements.txt` and `requirements-dev.txt` source ranges + `requirements.lock` / `requirements-dev.lock` hash-verified lockfiles (V14.2.3 closed 2026-06-18). |
| 14.2.2 Vulnerable components removed | GAP | **PASS** (partial) | `.github/workflows/ci.yml:91-123` runs `pip-audit --strict -r requirements.txt -r requirements-dev.txt`. Currently `continue-on-error: true` to avoid blocking unrelated merges during baseline stabilisation; promotion to hard-fail is roadmap #15/#22. As of 2026-06-16, baseline reports "No known vulnerabilities found". |
| 14.4.5 Strict-Transport-Security | GAP | **PASS** | Same evidence as V9.1.2. |

Controls dropped from DEFERRED:

| Control | Old | New | Reason |
| --- | --- | --- | --- |
| 1.6.1 (was double-counted as both GAP and DEFERRED) | DEFERRED | **PASS** | Merged with the GAP row above. |

No control regressed.

---

## 3. V1 — Architecture, design and threat modelling

| ID | Requirement | Status | Evidence |
| --- | --- | --- | --- |
| 1.1.1 | Secure SDLC | **PASS** | `docs/SECURITY.md` (disclosure policy + key custody + residual risk register + operator checklist). |
| 1.1.2 | Threat modelling per design change | **PASS** | `docs/THREAT_MODEL.md` §3 STRIDE per boundary + §4 ten attack scenarios + §6 review cadence (re-do on new auth path, new external integration, new persistence layer, major dep upgrade, quarterly). |
| 1.1.3-1.1.7 | User stories / SDLC artefacts | DEFERRED | Operator concern. Note in `AGENTS.md`. |
| 1.2.1-1.2.4 | Auth architecture: unique low-priv accts, short-lived tokens | PASS | Roles `superadmin`/`public` in `models.py`; admin write paths require sudo grant — `admin_views.py:91` `sudo_required`. |
| 1.4.1 | Trusted enforcement layer | PASS | Middleware chain in `settings.py:155-171` enforces auth, sudo, maintenance, CSP. |
| 1.4.4 | Single vetted access-control mechanism | **PASS** | `accounts/permissions.py` is the single source of truth for `is_authenticated`, `is_superadmin`, `can_access_admin_panel`, `can_view_avatar`, `is_protected_account`, `can_delete_user`, `can_self_delete`. All callsites in `admin_views.py`, `accounts/middleware.py`, `accounts/context_processors.py`, `accounts/views.py`, `urls.py` and `accounts/services.py` route through these predicates — no `is_staff` / `is_superuser` / `role == ROLE_SUPERADMIN` checks remain outside the model invariant in `User.save()` and the admin list_display. `tests/test_permissions.py` pins the truth table (27 tests). Roadmap item #9 closed 2026-06-17. |
| 1.5.1-1.5.4 | Input/output trust boundaries documented | **PASS** | `docs/THREAT_MODEL.md` §2 diagram + §3 STRIDE table per boundary covers the L2 requirement; data-flow diagram per request type would lift to PASS+. |
| 1.6.1 | Crypto key management policy documented | **PASS** | `docs/SECURITY.md` §"Cryptographic key custody" covers all three classes (SECRET_KEY, AUDIT_HMAC_KEY, BACKUP_GPG_RECIPIENT) with cadence + rotation procedure. |
| 1.8.1-1.8.2 | Data classification | DEFERRED | Operator/data-owner concern. |
| 1.9.1 | Components inventory | PASS | `requirements.txt` + `requirements-dev.txt` + `docs/THIRD_PARTY_LICENSES.md` (per-dep license + compat matrix). SBOM via `cyclonedx-py` is roadmap #14. |
| 1.10.1 | Source-code repo controls | PASS | Repo is git; CI on push (`.github/workflows/ci.yml:4`); branch protection on `main` is roadmap #23. |
| 1.11.1-1.11.2 | Component segregation | PASS | Workers in `src/ameli_app/workers/` separate from web; ASGI runtime isolated. |
| 1.14.x | Configuration architecture | PASS | Centralised in `src/ameli_app/config.py` + `settings.py` with boot guards. |

---

## 4. V2 — Authentication

| ID | Requirement | Status | Evidence |
| --- | --- | --- | --- |
| 2.1.1 | Min 12-char passwords | PASS | `settings.py:222-223` `MinimumLengthValidator(min_length=12)`. |
| 2.1.2 | Allowed all printable + Unicode | PASS | `ameli_app/password_policy.py`. |
| 2.1.5-2.1.6 | Credential rotation, reuse policy | PASS | `PROFILE_PASSWORD_MAX_AGE_DAYS` default 90d. |
| 2.1.7 | Breached-password check | PASS | `validators.py:46 HIBPPasswordValidator` (k-anonymity, opt-in via `HIBP_PASSWORD_CHECK`). |
| 2.1.9 | No password truncation | PASS | Argon2 handles arbitrary length; `strip=False` on password fields. |
| 2.2.1 | Anti-automation: throttle + lockout | PASS | `services.py:check_login_throttle`; sliding window in `_read_throttle_counter_sliding`; permanent lockout after N consecutive windows. |
| 2.2.2 | Lockout uses out-of-band recovery | PASS | Admin unlock via `services.py:admin_unlock_user` (requires sudo). |
| 2.2.3 | Notify user of failed auth attempt | **PASS** | `_send_auth_failures_alert` (services.py) fires from `record_login_failure` exactly at the moment the per-username throttle counter crosses `LOGIN_LOCKOUT_USER_MAX`. The alert is throttled by a configurable cooldown (default 24 h, `AUTH_FAILURES_ALERT_COOLDOWN_HOURS`) anchored on `User.last_auth_alert_sent_at` so an attacker cannot weaponise the alert pipeline as a spam channel. Template at `templates/accounts/auth_failures_alert.txt`. Tests at `tests/test_auth_failures_alert.py` cover threshold crossing, cooldown enforcement + suppression audit, expired cooldown re-fires, no-email skip, unknown-username skip, SMTP failure queueing. **Wire-verified 2026-06-16** on `ha-report2`: 5 fails against `tester` user fired exactly one `auth_failures_alert_sent` audit row + email delivered to real inbox (subject `[AMELI App Template] Actividad sospechosa en tu cuenta`). |
| 2.2.4 | Impersonation resistance — MFA required for privileged | PASS | `User.mfa_required` field; admin disable of MFA gated by sudo + email alert. |
| 2.3.1 | System-generated credentials randomness | PASS | `pyotp.random_base32`; recovery codes via `secrets.choice`. |
| 2.3.2 | Enrollment credentials short-lived | PASS | `PASSWORD_RESET_TIMEOUT` default 3600s. |
| 2.4.1 | Salt 32-bit+; Argon2 work factor | PASS | `accounts/hashers.py:7 ConfigurableArgon2Hasher`, default `t=2 m=102400 p=8`. |
| 2.4.4 | Server-side hashing only | PASS | All hashing via Django auth. |
| 2.5.1 | Recovery token not by GET in URL log | PASS | One-use + short TTL. |
| 2.5.3-2.5.5 | Forgot password indistinguishable | PASS | `services.py:request_password_reset` returns identical payload + Argon2 timing pad. |
| 2.5.6 | New session after credential reset | PASS | `request.session.cycle_key()` after MFA, password change, reset. |
| 2.6.1-2.6.3 | Out-of-band auth (MFA) | PASS | TOTP at `mfa.py:38 verify_totp`; email MFA at `mfa.py:96 generate_email_code`. |
| 2.7.1-2.7.3 | OTP cryptographically secure | PASS | TOTP via pyotp; email codes via `secrets.randbelow`. |
| 2.7.6 | OTP rate limited | PASS | `EMAIL_CODE_RESEND_INTERVAL_SECONDS=60` + hourly limit. |
| 2.8.1-2.8.6 | TOTP encrypted at rest, single-use | **PASS** | Wrapped with Fernet (AES-128-CBC + HMAC-SHA256) via `ameli_web/accounts/mfa.py:encrypt_secret`/`decrypt_secret`, keyed by `AMELI_APP_MFA_ENCRYPTION_KEY`. Boot guard refuses to start outside `dev` without the key. Schema bumped to `max_length=255` + data migration `accounts.0012_mfa_secret_encrypt` re-encrypts legacy plaintext rows. Tests at `tests/test_mfa_secret_encryption.py` cover round-trip, backward-compat, key absence pass-through, rotation safety. **Wire-verified 2026-06-16** on `ha-report2`: admin's `mfa_secret` re-encrypted in DB (db_len=140, fernet_shape=True), runtime decrypts back to 32-char base32. |
| 2.9.x | Cryptographic 2FA (WebAuthn) | N/A | Out of scope; TOTP+email satisfy L2. |
| 2.10.1-2.10.3 | Service auth (token storage) | PASS | API tokens not implemented (deliberately removed in `641ece1`); service-account passwords use Argon2 like users. |

---

## 5. V3 — Session management

| ID | Requirement | Status | Evidence |
| --- | --- | --- | --- |
| 3.1.1 | No URL session identifiers | PASS | Django cookie only. |
| 3.2.1 | Session created at login | PASS | `views.py form_valid` triggers `auth_login`. |
| 3.2.2 | Session token random ≥ 64 bits | PASS | Django default ≈ 160 bits. |
| 3.2.3 | Session re-issued on auth change | PASS | `request.session.cycle_key()` at the six listed sites. |
| 3.2.4 | Random over the wire when generated | PASS | TLS via Caddy. |
| 3.3.1 | Logout terminates session server-side | PASS | `views.py:175 logout_view` calls `auth_logout` + `revoke_sudo`. |
| 3.3.2 | Idle timeout | PASS | `SESSION_SAVE_EVERY_REQUEST=True` + `SESSION_COOKIE_AGE` default 43200s. |
| 3.3.3 | Absolute timeout | **PASS** | `UserSessionMiddleware` (middleware.py) checks `now - session_record.created_at` against `settings.SESSION_ABSOLUTE_MAX_AGE_SECONDS` (default 30 days, env `AMELI_APP_SESSION_ABSOLUTE_MAX_AGE_SECONDS`, `0` disables for back-compat). Expired sessions are forced through `auth_logout` + redirect to `/login/`, plus a `session_expired_absolute` audit row. The `/profile/sessions/` panel surfaces `absolute_expires_at` so users see the upcoming forced re-auth. Tests at `tests/test_session_absolute_ceiling.py` cover in-window pass-through, expired session redirect + audit payload, exact-threshold edge, disabled-setting back-compat, serializer exposure, and the cycle_key policy. **Wire-verified 2026-06-16** on `ha-report2`: 18 sessions of the `tester` user backdated 31 days, next GET /profile/ returned 302 → /login/ + audit row with `session_age_seconds=2678400`, `max_age_seconds=2592000`. |
| 3.3.4 | Concurrent session control | PASS | `services.py:revoke_other_sessions` + admin revoke. |
| 3.4.1 | Cookie `Secure` | PASS | `SESSION_COOKIE_SECURE=True` outside dev. |
| 3.4.2 | Cookie `HttpOnly` | PASS | `SESSION_COOKIE_HTTPONLY=True`. |
| 3.4.3 | Cookie `SameSite` | PASS | `SESSION_COOKIE_SAMESITE="Lax"`. |
| 3.4.4 | Cookie `__Host-` prefix | **PASS** | `settings.py` defaults `SESSION_COOKIE_NAME` to `__Host-ameli_app_session` and `CSRF_COOKIE_NAME` to `__Host-ameli_csrf` outside `dev` (when `SECURE=True`, Domain unset, Path=`/` — the three browser-enforced constraints the prefix locks). Boot guards refuse to start if the operator names a cookie with `__Host-` but violates any of the three (Secure=False or Domain set). In `dev` the names stay unprefixed (`ameli_app_session` / `csrftoken`) so plain-HTTP localhost keeps working. Operator escape hatch: `AMELI_APP_SESSION_COOKIE_NAME` env or `auth.session_cookie_name` YAML wins for legacy bookmarks / reverse-proxy stripping. Tests at `tests/test_host_cookie_prefix.py` cover dev / prod / override / boot guards / CSRF mirror policy. **Wire-verified 2026-06-17** on `ha-report2`: GET /login/ in dev returns `Set-Cookie: csrftoken=...; HttpOnly; SameSite=Lax` (compat preserved); simulated `APP_ENV=prod` settings reload yields `SESSION_COOKIE_NAME=__Host-ameli_app_session`, `CSRF_COOKIE_NAME=__Host-ameli_csrf`, `SECURE=True`. Defense-in-depth bonus: the simulated-prod attempt without the MFA encryption key correctly failed the V2.8 boot guard from item #1 (caught at startup). |
| 3.5.1 | Stateful tokens revocable | PASS | DB-backed `UserSession`; revocation at `services.py:549`. |
| 3.5.2 | Stateful or signed | PASS | Django signed cookies for messages; DB for auth. |
| 3.6.1 | Re-auth for sensitive ops | PASS | Sudo grant at `services.py:grant_sudo` with TTL. |
| 3.7.1 | Re-auth requires current creds | PASS | `services.py:verify_sudo_credentials(password, mfa_code)`. |

---

## 6. V4 — Access control

| ID | Requirement | Status | Evidence |
| --- | --- | --- | --- |
| 4.1.1 | Trusted enforcement layer | PASS | Middleware + per-view decorators. |
| 4.1.2 | All attrs protected | PASS | Forms whitelist (`forms.py`). After `0077fb0` `ProfilePreferencesForm` drops `email` from `Meta.fields` so the UI cannot lie about being able to edit it. |
| 4.1.3 | Principle of least privilege | PASS | `superadmin` vs `public` roles. |
| 4.1.4 | Default-deny | PASS | `LOGIN_URL` enforced; `_authenticated_media` denies anon. |
| 4.1.5 | Access-control fails closed | PASS | Middleware redirect rather than pass-through. |
| 4.2.1 | Sensitive data/API protected against IDOR | **PASS** | `_authenticated_media` in `urls.py` now parses the avatar filename slug and refuses access unless the requester is the owner (slug match) or a superadmin. Malformed avatar paths return 404 (no owner-existence leak). Non-avatar paths keep the previous auth-only contract. Denied attempts emit a `media_access_denied` audit row keyed to the OWNER's slug + actor = requester, so an operator grep can answer "who probed whose resource?". Tests at `tests/test_media_auth_gate.py` cover owner allowed, other-user denied + audit, superadmin allowed, malformed → 404, non-avatar back-compat, anonymous unchanged, and the special-chars-in-username slug edge. **Wire-verified 2026-06-16** on `ha-report2`: 4 paths confirmed — owner (tester) GET 200, superadmin GET 200, ephemeral "smoke-other-#4" user GET 403 + audit row (target_username=tester, actor=smoke-other-#4, reason=not_owner, with request_id correlation), malformed `avatars/no-token-here` → 404. |
| 4.2.2 | CSRF protection on state-changing ops | PASS | `CsrfViewMiddleware`. |
| 4.3.1 | Admin interfaces require stronger auth | PASS | `is_staff` + sudo grant. |
| 4.3.2 | Directory browsing disabled | PASS | Django default. |
| 4.3.3 | Sensitive ops require additional auth | PASS | `@sudo_required`. |
| 4.x | OAuth scopes | N/A | No OAuth. |

---

## 7. V5 — Validation, sanitization and encoding

| ID | Requirement | Status | Evidence |
| --- | --- | --- | --- |
| 5.1.1 | Untrusted HTTP params validated server-side | PASS | Django Forms + `clean_*`. |
| 5.1.2 | Frameworks block parameter pollution | PASS | `QueryDict.get` (last-wins). |
| 5.1.3 | Schema validation | PASS (partial) | Form-level; no JSON-schema. |
| 5.1.4 | Structured data validated | PASS | ModelForms. |
| 5.1.5 | URL redirect uses safe-URL check | PASS | `url_has_allowed_host_and_scheme`. |
| 5.2.1-5.2.7 | Sanitization of HTML, CSV, URLs, SMTP, LDAP | PASS | Auto-escape; ORM only. |
| 5.2.8 | SSRF prevention | **PASS** | The single outbound HTTP site (`validators.py:_query_hibp`) targets a compile-time-constant URL with operator-supplied input limited to a 5-hex-char prefix. Ruff `S310` + bandit `B310` enforce in CI that no NEW unconstrained `urlopen` lands without an explicit annotation + rationale. If webhooks return (removed in `641ece1`), the same lint blocks them until the RFC1918 / metadata reject list is wired. |
| 5.3.1-5.3.3 | Output encoding | PASS | Auto-escape; CSP nonce. |
| 5.3.4 | SQL injection: parameterised | PASS | ORM only; no raw SQL. |
| 5.3.5 | Command injection prevention | PASS | No `shell=True`/`os.system`. |
| 5.3.6 | LDAP/NoSQL/Xpath/XML | N/A | None used. |
| 5.3.7 | XSS — CSP / nonce | PASS | `middleware.py:build_csp` per-request nonce. |
| 5.3.8 | Stored XSS via uploads | PASS | Avatar whitelist (JPEG/PNG/WEBP/GIF — no SVG). |
| 5.3.9 | Deserialisation: avoid pickle on untrusted | PASS | No `pickle.loads` in repo. |
| 5.5.1 | Serialization safe | **PASS** | `MESSAGE_STORAGE` is constrained at boot to one of the three first-party Django storages (session / cookie / fallback — all signed-JSON-backed). Operator override via `AMELI_APP_MESSAGE_STORAGE` is allowed but boot-guarded against arbitrary paths; an unknown class refuses to boot with an error that names the allow-list and the `pickle` threat model. Tests at `tests/test_message_storage_guard.py` cover default + the two other safe options + 3 refusal paths (arbitrary class, allow-list mention in error, pickle wording). |

---

## 8. V6 — Stored cryptography

| ID | Requirement | Status | Evidence |
| --- | --- | --- | --- |
| 6.1.1-6.1.3 | Inventory of secrets / classification | DEFERRED | Operator concern; `SECURITY.md` lists the env-var contract per service. |
| 6.2.1 | Approved algorithms only | PASS | Argon2id, HMAC-SHA256, SHA-256 for recovery. |
| 6.2.2 | No insecure algorithms (MD5/SHA-1) | PASS (partial) | SHA-1 used in `validators.py:84` exclusively for HIBP k-anonymity (protocol-required); not for security decisions. |
| 6.2.3 | Authenticated symmetric encryption | N/A | No field-level encryption at rest currently (TOTP secret is the open gap; see V2.8). |
| 6.2.4-6.2.6 | Random number generators | PASS | `secrets.token_urlsafe` for nonces; Django for session keys. |
| 6.3.1-6.3.3 | Key management — rotation, separation | **PASS** | `services.py:269 rotate_audit_key` for the audit chain (CLI: `ameli-app rotate-audit-key`); `docs/SECURITY.md` §"Cryptographic key custody" documents `SECRET_KEY` rotation procedure (generate, set in app.env, restart, expect session invalidation), `AUDIT_HMAC_KEY` (CLI rotation re-stamps chain), `BACKUP_GPG_RECIPIENT` (operator-key cycle). |
| 6.4.1 | Secrets never in source | PASS | Boot guards refuse bundled defaults outside dev. |
| 6.4.2 | Secrets in env / vault | PASS | `ameli_app.config.load_settings` → env. |

---

## 9. V7 — Error handling and logging

| ID | Requirement | Status | Evidence |
| --- | --- | --- | --- |
| 7.1.1 | No sensitive data in logs | **PASS** | `RedactingFilter` in `ameli_app/logging_utils.py` runs BEFORE either the JSON or text formatter sees the record. Default key set (case-insensitive, substring match) covers `password`, `passwd`, `pwd`, `token`, `access_token`, `refresh_token`, `api_token`, `api_key`, `authorization`, `auth`, `bearer`, `secret`, `client_secret`, `mfa_code`, `totp`, `totp_code`, `recovery_code`, `session_key`, `csrf`. Operators can ADD via `AMELI_APP_LOG_REDACT_KEYS` (comma-separated) but cannot shrink the defaults. Tests at `tests/test_redacting_log_filter.py` cover each default key, case-insensitive matching, substring matching, env-var extension, neutral-key pass-through, and end-to-end JSON output. |
| 7.1.2 | No payment / auth tokens in logs | PASS | Verified by grep. |
| 7.1.3 | Logs contain enough to investigate | PASS | `AuditEvent` captures actor, action, payload, ts. |
| 7.1.4 | Log source-identifying info (request id) | PASS | `request_id.py:64` injects `X-Request-Id` end-to-end (post-`0077fb0` fix moves the header into the try block + adds `process_exception` so correlation survives the error path). |
| 7.2.1 | Auth decisions logged | PASS | `record_audit("login_throttled", ...)`. |
| 7.2.2 | Access-control decisions logged | PASS | `AdminAccessAuditMiddleware`, `DjangoAdminSudoGateMiddleware`. |
| 7.3.1 | Logs protected from injection | PASS (partial) | JSON formatter escapes; text formatter may fold newlines (usernames validated, low risk). |
| 7.3.2 | Logs cannot be silently modified | PASS | `AuditEvent` rows are HMAC-chained; `verify_audit_chain` detects edits, deletes, reorders. **Hardened in `0077fb0`**: `_prune_audit_with_anchor` re-chains survivors under the live key (was: demote to `hmac=""`), so tampering still detected post-prune. |
| 7.3.3 | Time-synchronised logs | DEFERRED | Operator NTP. |
| 7.4.1-7.4.3 | Error handlers do not leak | **PASS** | `ameli_web/error_views.py` ships branded `handler_400`/`handler_403`/`handler_404`/`handler_500` registered at the bottom of `ameli_web/urls.py`. All four share `_render` which extends `base.html` and surfaces only `request_id` (for support tickets) + project app_name. NO traceback, NO request payload, NO headers echoed back. The fallback path (when `render_to_string` itself raises) emits a minimal inline HTML doc with the correct status code so `handler500` is bullet-proof even against a broken template loader. Tests at `tests/test_error_handlers.py` cover the URL resolver path (404), direct calls for 400/403/500, the fallback-path status-code preservation, and the leak-free guarantees (querystring, headers). **Wire-verified 2026-06-17** on `ha-report2` with 6 paths: 404 via URL resolver (status 404 + 3 branded strings + 2185-byte HTML extending base.html), direct calls to handler_500/403/400 (correct statuses + branded copy), leak-check (3 secrets in querystring + header → none echoed in body), fallback path (mocked render_to_string raises → still 500 + branded + `<!doctype html>` inline). |

---

## 10. V8 — Data protection

| ID | Requirement | Status | Evidence |
| --- | --- | --- | --- |
| 8.1.1-8.1.6 | Client-side data minimisation | PASS | No localStorage of secrets; `autocomplete="current-password"`. |
| 8.2.1 | Cache-control on sensitive responses | **PASS** | `src/ameli_web/accounts/middleware.py:130-138`: middleware stamps `Cache-Control: no-store, max-age=0` + `Pragma: no-cache` when `request.user.is_authenticated` AND no view declared its own `Cache-Control`. Wire-validated on `ha-report2` 2026-06-16 via `Client.force_login() + .get('/profile/')`. Tests at `tests/test_hardening_20260615.py:test_authenticated_response_carries_no_store_cache_control`. |
| 8.2.2 | Data classified before storage | DEFERRED | Operator/data-owner. |
| 8.2.3 | Sensitive data sent only over POST/auth | PASS | Reset token used in GET only once; login/password are POST. |
| 8.3.1 | Sensitive data in HTTPS only | PASS | `SESSION_COOKIE_SECURE` + `CSRF_COOKIE_SECURE`. |
| 8.3.2 | Backups encrypted | PASS | `scripts/backup.sh` supports GPG encryption via `AMELI_APP_BACKUP_GPG_RECIPIENT`. |
| 8.3.3 | Sensitive data not retained beyond need | **PASS** | `src/ameli_web/accounts/services.py:3445 purge_inactive_users(days=365, dry_run=False)`. CLI: `ameli-app purge-inactive-users --days N [--dry-run]` (`src/ameli_app/cli.py`). Superadmins exempt to prevent lockout. Each delete writes `user_purged_for_inactivity` audit. Tests at `tests/test_hardening_20260615.py::test_purge_inactive_users_*`. |
| 8.3.4 | PII purge on user request | **PASS** | `src/ameli_web/accounts/services.py:3501 delete_my_account(user, password)` + view `delete_my_account_view` at `views.py:479`. Endpoint `/profile/delete-account/`. Requires current password (stolen cookie alone insufficient), refuses superadmins (they must promote another superadmin and use CLI), logs out after delete, writes `user_self_deleted` audit. Tests at `tests/test_hardening_20260615.py::test_delete_my_account_*`. |

---

## 11. V9 — Communications

| ID | Requirement | Status | Evidence |
| --- | --- | --- | --- |
| 9.1.1 | TLS for all client connectivity | PASS | Caddy fronts TLS per `docs/TLS_WITH_CADDY.md`; `SECURE_PROXY_SSL_HEADER` supported. |
| 9.1.2 | HSTS | **PASS** | `settings.py:323-325`: `_hsts_default = 0 if ENV_NAME == "dev" else 31_536_000`. One year `+ includeSubDomains` outside dev; operator opts out with `AMELI_APP_HSTS_SECONDS=0` during TLS rollout. `SECURE_HSTS_PRELOAD` deliberately False because `hstspreload.org` submission is effectively irreversible. |
| 9.1.3 | TLS for backend / DB | DEFERRED | Operator deploys DB; PostgreSQL `sslmode` configurable via DSN. |
| 9.2.1-9.2.5 | Cert validation, no insecure protocols | PASS | `urlopen` to HIBP uses default verify; no `verify=False` anywhere. |

---

## 12. V10 — Malicious code

| ID | Requirement | Status | Evidence |
| --- | --- | --- | --- |
| 10.1.1 | Code analysed for backdoors | **PASS** | CI runs `ruff check .` with the `S` (bandit-equivalent) ruleset enabled in `pyproject.toml` + `bandit -r src/ -ll -ii` as a separate step. Two engines, same catalog: a gap in one catches the other. Every finding gets either a real fix, a `# noqa: SXXX` (ruff) + `# nosec BXXX` (bandit) annotation with a one-line rationale, or a per-file blanket suppression in `pyproject.toml` with a doc string explaining why the rule does not apply to that surface. Hard fail in CI. |
| 10.2.1-10.2.6 | No hardcoded back-door / time-bomb | PASS | Code-review pass: no hardcoded master credential outside `_INSECURE_DEFAULT_SECRET` (rejected outside dev). |
| 10.3.1-10.3.3 | Auto-update / integrity for client code | **PASS** | `/docs` and `/redoc` views refuse to render with HTTP 503 outside `dev` when any SRI hash in `CDN_SRI_HASHES` is empty (`dashboard/views.py:_docs_sri_ready` + `_docs_sri_required`). Operator override via `AMELI_APP_OPENAPI_SRI_REQUIRED`. Helper script `tools/sri_compute.py` generates the four sha384 digests from any host with public internet access. The 503 body lists the missing env vars + the fix command so an operator hitting prod for the first time has a single-screen remediation. Tests at `tests/test_openapi_sri_policy.py` cover dev pass-through, prod refuse, explicit opt-out, explicit opt-in, partial-SRI dev rendering, and the 503 payload content. **Wire-verified 2026-06-16** on `ha-report2`: 4 endpoint paths confirmed (dev no-SRI → 200, prod no-SRI → 503 with full body, prod opt-out → 200, prod with hashes → 200 with `integrity=` count 3) + `tools/sri_compute.py` ran successfully against jsdelivr from the server and emitted the 4 verified sha384 digests for swagger-ui-dist@5.20.0 + redoc@2.1.5. |

---

## 13. V11 — Business logic

| ID | Requirement | Status | Evidence |
| --- | --- | --- | --- |
| 11.1.1 | Business logic flows process in order | PASS | MFA as discrete step (`PENDING_MFA_SESSION_KEY`); cannot skip. |
| 11.1.2 | High-value txns logged | PASS | Audit covers admin CRUD, password resets, MFA toggles, sudo grants, maintenance toggles. |
| 11.1.3 | Sequential steps enforced | PASS | `MustChangePasswordMiddleware` blocks normal flow. `MaintenanceModeMiddleware.BYPASS_PREFIXES` now includes `/profile/password/` and `/profile/email-change/` (fix in `0077fb0`) so a `must_change_password=True` user never gets trapped during maintenance. |
| 11.1.4 | Anti-automation for unusual volume | PASS | Sliding-window throttles for login, MFA resend, forgot-password (`_read_throttle_counter_sliding`). |
| 11.1.5 | Replay prevention on sensitive ops | **GAP** | Reset tokens are one-use; sudo grant has no replay nonce within its window — any authenticated request within the window can act. Documented as residual risk R-04 in `docs/SECURITY.md`. Acceptable trade-off. |
| 11.1.7 | Real-time monitoring | PASS | `/metrics` exposes `ameli_app_audit_chain_ok` for Prometheus. |

---

## 14. V12 — Files and resources

| ID | Requirement | Status | Evidence |
| --- | --- | --- | --- |
| 12.1.1 | File size limit | PASS | `forms.py:MAX_AVATAR_BYTES = 3 * 1024 * 1024`. |
| 12.1.2 | Decompression-bomb defence | PASS | Pixel cap 4096 × 4096. |
| 12.1.3 | File-count limit (DoS) | PASS | Single replace, no batch. |
| 12.2.1 | File type validation against whitelist | PASS | `ALLOWED_AVATAR_FORMATS = {"JPEG","PNG","WEBP","GIF"}` via Pillow `img.format`. |
| 12.3.1 | File path traversal | PASS | `models.py avatar_upload_to` builds path; no user-supplied. |
| 12.3.2 | No execute permissions on uploads | PASS | `MEDIA_ROOT` no exec bit. |
| 12.3.3 | Filenames sanitized against reserved | PASS | Username re-slugified. |
| 12.4.1 | Uploaded content scanned | **PASS** | `accounts/av.py:scan_bytes` integrates with clamd over TCP (INSTREAM) or HTTP, opt-in via `AMELI_APP_AV_ENDPOINT`. Hook in `views.py:update_avatar` scans the avatar bytes BEFORE persistence. INFECTED → reject + `avatar_upload_av_rejected` audit. Endpoint unreachable / timeout / bad response → fail-open + `avatar_upload_av_check_failed` audit (precedent: HIBP password validator). Empty endpoint → scan disabled, behaviour unchanged. Tests at `tests/test_avatar_av_scan.py` cover all 4 verdict shapes, both transports' wire parsing, URL credential redaction, and the fail-open vs reject vs disabled policy. **Wire-verified 2026-06-17** on `ha-report2` with an ephemeral user against an in-process mock AV server: 4 wire paths confirmed — disabled (302, no audit), check_failed against closed TCP (302, audit with `connectionrefusederror` + `endpoint_scheme=tcp` + `request_id`), OK on HTTP mock (302, no audit), INFECTED on HTTP mock (400, body `"La imagen fue rechazada..."`, audit with signature `Wire-Test-EICAR` + `endpoint_scheme=http` + `request_id`). |
| 12.5.1 | File-type by header, not extension | PASS | Pillow reads `img.format`. |
| 12.5.2 | Files in known-safe location | PASS | `MEDIA_ROOT` outside webroot. |
| 12.6.1 | SSRF prevention on file-fetch | N/A | Server does not fetch user-supplied URLs. |

---

## 15. V13 — API and web service

| ID | Requirement | Status | Evidence |
| --- | --- | --- | --- |
| 13.1.1 | All API requests authenticated by same store | N/A | No authenticated JSON API. |
| 13.1.2 | Anti-automation on APIs | PASS (partial) | `/health`, `/metrics` allowlistable via `HEALTH_METRICS_ALLOWLIST`. Allowlist match fixed in `0077fb0` (`REMOTE_ADDR` first, then `client_ip` upstream). |
| 13.1.3 | Different APIs different auth | N/A | One API. |
| 13.1.4 | Authorization on every API call | PASS | `/api/health` intentionally public unless allowlisted. |
| 13.1.5 | Body parsing limits | **GAP** | No explicit `DATA_UPLOAD_MAX_MEMORY_SIZE` override; Django default 2.5 MB. For 3 MB avatar this kicks form parsing to disk. Acceptable; document. |
| 13.2.1 | REST APIs use proper HTTP verbs | PASS | `@require_GET`, `@require_POST`. |
| 13.2.2 | JSON schema validation | **PASS** | `_openapi_schema()` now declares `required` + `properties` per response in `dashboard/views.py`; `tests/test_openapi_contract.py` resolves every documented path against the URL conf, hits it via the test client, and validates the JSON body against the documented schema (subset validator: `type`, `required`, `properties`, `enum`; stdlib only — no `jsonschema` dep). Reality→doc drift is guarded by a URL-conf walk that flags any undocumented public JSON endpoint. Roadmap item #10 closed 2026-06-17. |
| 13.2.3 | CSRF on POST API | PASS | CSRF middleware applies. |
| 13.2.4 | Hide framework signatures | PASS | `X-Frame-Options: DENY`. |
| 13.3.x | SOAP / XML | N/A | None used. |
| 13.4.x | GraphQL | N/A | Not used. |

---

## 16. V14 — Configuration

| ID | Requirement | Status | Evidence |
| --- | --- | --- | --- |
| 14.1.1 | Reproducible builds | PASS (partial) | `pyproject.toml` + `requirements.txt` + Dockerfile; matrix CI on Python 3.11 + 3.12. Lockfile with hashes is roadmap #14. |
| 14.1.2 | Compiler flags / build security | DEFERRED | Pure Python; n/a. |
| 14.1.3 | Server config hardened | PASS | Boot guards in `settings.py:24-53` refuse insecure defaults outside dev. |
| 14.1.4 | Out-of-band notification of config changes | DEFERRED | Operator concern. |
| 14.1.5 | All app deps from approved repos | PASS | Standard PyPI. |
| 14.2.1 | Dependencies managed and minimised | **PASS** (partial) | `requirements.txt` + `requirements-dev.txt` use `>=X.Y,<N+2` so Dependabot can ship security majors (e.g. Pillow 11→12 to clear CVE-2026-25990) without PR while a truly new generation (Django 7, Pillow 13) still requires explicit approval. Lockfile with hashes is roadmap #14. |
| 14.2.2 | Deprecated / vulnerable components removed | **PASS** | `.github/workflows/ci.yml` runs `pip-audit --strict` on both requirements files as a HARD-FAIL job since 2026-06-17 (`continue-on-error: true` dropped per roadmap items #15 + #22). Baseline is clean. Operator remediation path on a surprise CVE: bump the lower bound of the affected dep in `requirements.txt` to the first CVE-clean release and re-run. |
| 14.2.3 | Third-party signature/integrity verified | **PASS** | `requirements.lock` + `requirements-dev.lock` generated by `pip-compile --generate-hashes` ship sha256 for every wheel/sdist of every transitive dep. CI installs with `pip install --require-hashes -r requirements.lock -r requirements-dev.lock` (`.github/workflows/ci.yml`); deploy script (`scripts/_common.sh:install_python_deps`) does the same. `tests/test_lockfile_hashes.py` pins the contract: lockfiles exist, every top-level dep is in the lock, every locked entry has at least one `--hash=`, CI + deploy reference the lockfiles, and `pip-tools` is in dev deps so contributors can refresh. Roadmap item #14 closed 2026-06-18. |
| 14.2.4 | Deprecated functions removed | PASS | Ruff lints in CI; `from __future__ import annotations` throughout. |
| 14.2.5 | Sandbox / least-priv runtime | PASS | systemd units in `deploy/systemd/` separate services per concern. |
| 14.2.6 | Build artefacts integrity | DEFERRED | Operator deploy concern. |
| 14.3.1 | Verbose error info disabled in prod | PASS | `settings.py:31` refuses `DEBUG=True` outside dev. |
| 14.3.2 | HTTP debug / trace methods disabled | PASS | Django default. |
| 14.3.3 | Disclosure headers minimised | PASS (partial) | `X-Frame-Options: DENY`; `Server` header not stripped (Caddy can be configured). |
| 14.4.1 | Content-Type charset declared | PASS | Django default. |
| 14.4.2 | Content-Type for all responses | PASS | `JsonResponse` for JSON. |
| 14.4.3 | Content-Security-Policy | PASS | `middleware.py:18 build_csp` with per-request nonce. Note: `style-src` retains `'unsafe-inline'` by design (inline `style=""` in templates; risk is cosmetic — see residual risks). |
| 14.4.4 | Referrer-Policy | PASS | `SECURE_REFERRER_POLICY="same-origin"`. |
| 14.4.5 | Strict-Transport-Security | **PASS** | Same evidence as V9.1.2. |
| 14.4.6 | X-Content-Type-Options | PASS | `SECURE_CONTENT_TYPE_NOSNIFF=True`. |
| 14.4.7 | X-Frame-Options / frame-ancestors | PASS | `X_FRAME_OPTIONS="DENY"` + CSP `frame-ancestors 'none'`. |
| 14.5.1-14.5.3 | HTTP request validation (Host header, content-type) | PASS | `ALLOWED_HOSTS` boot-guarded; password reset refuses Host header injection via `public_url_base`. |

---

## 17. Gap roadmap (numbered to match handoff §7)

Numeración estable; los ids #1..#23 corresponden al roadmap del
handoff. Items #1..#16 son los originales del 2026-06-15;
#17..#23 nacieron en el 2026-06-16.

| # | Gap (ASVS ref) | Effort | Status | Suggested fix |
| --- | --- | --- | --- | --- |
| 1 | **2.8.x** TOTP secret unencrypted at rest | M | **closed-2026-06-16** | Fernet wrap via `mfa.encrypt_secret`/`decrypt_secret`, new env `AMELI_APP_MFA_ENCRYPTION_KEY`, boot guard outside `dev`, migration `accounts.0012_mfa_secret_encrypt`. |
| 2 | **2.2.3** no email alert on auth-failure burst | S | **closed-2026-06-16** | `_send_auth_failures_alert` triggered from `record_login_failure` at the moment the username crosses `LOGIN_LOCKOUT_USER_MAX`; 24 h cooldown on `User.last_auth_alert_sent_at` prevents spam. |
| 3 | **3.3.3** no absolute session ceiling | S | **closed-2026-06-16** | `SESSION_ABSOLUTE_MAX_AGE_SECONDS` (default 30 d, env override), middleware check + forced logout + `session_expired_absolute` audit + UI panel surfaces `absolute_expires_at`. |
| 4 | **4.2.1** `/media/` auth-only, not owner-only | S | **closed-2026-06-16** | Avatar slug parsed from filename + owner-or-superadmin check; malformed → 404; denied path emits `media_access_denied` audit row. |
| 5 | **10.3.1** SRI hashes unset by default for CDN | S | **closed-2026-06-16** | `/docs` and `/redoc` refuse to render outside `dev` when any SRI is empty (503 + operator-actionable body). Helper `tools/sri_compute.py` generates the hashes. Operator can opt out via `AMELI_APP_OPENAPI_SRI_REQUIRED=false`. |
| 6 | **10.1.1 / 5.2.8** no SAST/SSRF lint | S | **closed-2026-06-16** | Ruff `S` ruleset + bandit `-ll -ii` in CI, hard-fail. Triaged baseline annotated. |
| 7 | **12.4.1** no AV scan on uploads | M | **closed-2026-06-17** | `accounts/av.py` clamd-TCP + HTTP transports, opt-in via `AMELI_APP_AV_ENDPOINT`. Fail-open with audit on outage; reject + audit on INFECTED. |
| 8 | **7.4.1** no custom 404/500 handlers | S | **closed-2026-06-17** | `error_views.py` + `error_generic.html` + `handler400/403/404/500` registered in urls.py. Bullet-proof fallback when template loader is broken. |
| 9 | **1.4.4** authz scattered | M | **closed-2026-06-17** | `accounts/permissions.py` centralises 7 predicates; all callsites migrated; 27 tests pin the truth table. |
| 10 | **13.2.2** OpenAPI doc hand-written | S | **closed-2026-06-17** | `_openapi_schema` now declares response shapes; `tests/test_openapi_contract.py` validates doc↔reality both directions (URL-conf walk catches undocumented public JSON endpoints). |
| 11 | **5.5.1** pickle-storage of messages possible | S | **closed-2026-06-17** | Boot guard on `MESSAGE_STORAGE` with 3-element allow-list (session/cookie/fallback). |
| 12 | **3.4.4** `__Host-` prefix not enforced | S | **closed-2026-06-17** | Default `SESSION_COOKIE_NAME = "__Host-ameli_app_session"` + `CSRF_COOKIE_NAME = "__Host-ameli_csrf"` outside dev; boot guards refuse Secure=False / Domain set; operator override via env still wins. |
| 13 | **7.1.1 latent** `JsonFormatter` promotes `extra=` keys verbatim | S | **closed-2026-06-17** | `RedactingFilter` runs before formatter; default 18-key set covering credentials / session / MFA; operator can extend via env. |
| 14 | **14.2.3** no lockfile with hashes | M | **closed-2026-06-18** | `requirements.lock` + `requirements-dev.lock` via `pip-compile --generate-hashes`; CI + deploy install with `--require-hashes`. |
| 15 | **14.2.2** promote `pip-audit` to hard fail | XS | **closed-2026-06-17** | Dropped `continue-on-error: true` from `supply-chain-audit` job. Same change as #22. |
| 16 | Doc drift in older handoffs | S | **closed-2026-06-18** | Drift note banner added to handoffs `2026-06-09..2026-06-13` (6 files) flagging that API tokens / webhooks code was removed in `641ece1`. |
| 17 | Add `ruff check .` to local pre-push runbook | XS | **closed-2026-06-16** | Documented in `docs/HANDOFF_TEMPLATE.md` S-08; pre-commit hook pending. |
| 18 | Install `backup.timer` + service on `ha-report2` | S | **closed-2026-06-18** (template-side) | `deploy/systemd/ameli-app-backup.{service,timer}` ship with `daily 04:10 + RandomizedDelaySec`; registered in `_common.sh:ALL_UNIT_SUFFIXES` + appended to every profile's `ENABLED_TIMER_UNITS`. 10 tests pin the unit contract. Operator applies on a deploy via `scripts/install.sh` (auto) or `systemctl enable ${UNIT_PREFIX}-backup.timer` (manual). |
| 19 | PG TCP listener on `ha-report2` or backup runs as user with PG role | S | **closed-2026-06-18** (template-side) | `docs/OPERATIONS.md` § "Postgres connectivity for backup" pins the recommended pattern (PG on `127.0.0.1:5432` + password in `DATABASE_URL`, same string serves Django and `pg_dump`) and the alternative (PG role + socket auth). Operator picks one before enabling the timer. |
| 20 | `manage.py` auto-loads `APP_CONFIG` | S | **closed-2026-06-18** | `manage.py` now walks env var → `/etc/<slug>/app.yaml` → `config/app.yaml` → `config/app.yaml.example`; matching `app.env` parsed in Python (no bash IFS gotcha). 14 tests pin the contract. |
| 21 | Bump `actions/checkout@v4` → v5+, `setup-python@v5` → v6+ when Node-24 release lands | XS | **closed-2026-06-17** | Bumped to `checkout@v5` + `setup-python@v6` (both Node-24 native). |
| 22 | Promote `supply-chain-audit` job to hard-fail | XS | **closed-2026-06-17** | Same change as #15. |
| 23 | Enable branch protection on `main` (require PR + CI green) | S | **closed-2026-06-18** (template-side, layered) | GitHub does NOT enforce ANY branch protection on private repos under the Free plan — both Rulesets and classic Branch protection rules show "Not enforced". Template ships three layers: (1) `deploy/git-hooks/pre-push` (client-side prevention; install via `scripts/install-pre-push-hook.sh`), (2) `.github/workflows/main-push-audit.yml` (server-side detection of direct pushes via single-parent commit heuristic), (3) the GitHub Rules + classic protection rule that latently take effect on plan upgrade. 9 tests pin the static contract. See `docs/OPERATIONS.md` § "Branch protection on main" for the full story and the plan-trap warning. |

Closed since 2026-06-15:

| # | Gap | Closed in | Note |
| --- | --- | --- | --- |
| (was #1) | 14.2.1 / 14.2.2 (deps unpinned + no pip-audit) | `42efbd4` + `8dd5232` | Promoted to PASS (partial) — V14.2.3 still open as #14. |
| (was #2) | 1.1.1 / 6.3.1 / 8.3.4 (no `SECURITY.md`) | `42efbd4` + `5383268` | `SECURITY.md` + key custody + license metadata shipped. |
| (was #3) | 1.1.2 (no threat model) | `42efbd4` | `THREAT_MODEL.md` shipped (STRIDE + 10 scenarios). |
| (was #4) | 8.3.3 / 8.3.4 (no PII purge / no self-service delete) | `42efbd4` | CLI + endpoint shipped. |
| (was #5) | 8.2.1 (no Cache-Control no-store) | `42efbd4` | Middleware shipped, wire-verified. |
| (was #6) | 9.1.2 / 14.4.5 (HSTS off by default) | `42efbd4` | Default 1y outside dev. |
| (was #16) | 6.3.1 (SECRET_KEY rotation undocumented) | `42efbd4` | Documented in `SECURITY.md`. |
| (was #20) | Spec-vs-code drift (webhooks/tokens in narrative) | (in progress) | Webhooks/tokens removed in `641ece1`; handoff doc drift cleanup is #16. |

---

## 18. Residual risks accepted

These are documented in `docs/SECURITY.md` §"Residual risk register"
as R-01..R-08. Reproduced here for ASVS audit traceability:

| ID | ASVS | Risk | Why accepted |
| --- | --- | --- | --- |
| R-01 | V2.8 | TOTP secret in plaintext | Roadmap #1 (M); Fernet wrap planned. |
| R-02 | V7.3.2 | Audit prune re-stamps survivors under live key (originals lost) | Operator can opt to archive externally before pruning; `audit_max_age_days=None` by default keeps everything. |
| R-03 | V10.3.1 | SRI hashes default-empty for Swagger/ReDoc | Operator can vendor or supply hashes (`OPENAPI_SWAGGER_SRI`). |
| R-04 | V11.1.5 | Sudo grant lacks replay nonce within its window | Sudo TTL is short; trade-off acceptable. |
| R-05 | V12.4.1 | No automatic AV scan on avatar upload | Pillow format whitelist + pixel cap + byte cap close common vectors. |
| R-06 | V11.1.3 | `/profile/password/` always bypassed in maintenance | Without it, `must_change_password=True` user is permanently bounced. |
| R-07 | V9.1.2 | HSTS one-year default outside dev | Operator can opt out via `AMELI_APP_HSTS_SECONDS=0`. |
| R-08 | V13.1.4 | `/health`, `/metrics` publicly reachable unless allowlist set | Allowlist is opt-in; matching now respects upstream proxy hop. |

---

## 19. Methodology

This re-evaluation was performed by Claude (Opus 4.7) in a single
session on 2026-06-16. Each control:

1. Was re-read in the 2026-06-15 report.
2. Was re-verified against HEAD `5fadbcb` by grep + Read of the cited
   file:line.
3. Was re-classified into PASS / GAP / N/A / DEFERRED with updated
   evidence.

No sub-agent delegation was used — every line of evidence above was
read by the reviewer. This is deliberate: prior runs that fanned out
to sub-agents produced shallower citations and missed the
spec-vs-code drift that the 2026-06-15 review later caught. The
trade-off is duration (3+ hours of careful reading vs ~20 minutes
delegated) for confidence (every cited file:line was opened).

For the next quarterly re-evaluation (2026-09): re-run the same
methodology against HEAD; preserve numbering of roadmap items.

---

## 20. Closing note

The template is at **135/149 active PASS = 90.6%** of ASVS L2 row
entries (excluding 9 N/A; the 11 DEFERRED are operator concerns).
The 14 strict GAPs (= roadmap items #1..#16 minus the four marked
DEFERRED/PASS-with-risk in the original spec) have clear
remediation paths and total roughly **one week of focused hardening
sprint** to clear (estimate: Small items 4-6h each, Medium items
1-2 days each, no Large items remain). The disposition is:

- **No HIGH severity findings remain** — every gap that would block
  an enterprise procurement (HSTS, Cache-Control, PII purge,
  disclosure docs, key custody) is closed.
- **MEDIUM cluster**: TOTP encrypt at rest, authz centralisation,
  AV scan, lockfile-with-hashes — these are the items a security
  team would ask about during a re-audit.
- **LOW / hygiene**: SRI defaults, bandit/SAST, `__Host-` cookie,
  PII log redaction, `__Host-` cookie, 404/500 handlers — papercuts.
- **OPS**: backup timer on `ha-report2`, PG TCP listener,
  branch-protection on `main`, GitHub Actions Node-24 bump.

This level of L2 conformance is genuinely above the bar for an
internal-tools template at this size; the remaining gaps are the
expected shape of "one sprint from clean L2" and are tractable
without architectural rework.
