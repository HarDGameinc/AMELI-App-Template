# Threat model — AMELI App Template

STRIDE-style pass over the template's trust boundaries and security
controls. The model evolves with the codebase; cite this file and
revise on any change that touches a trust boundary (new auth path,
new external integration, new persistence layer, new exec surface).

Pair with [`SECURITY.md`](SECURITY.md) (operational policy) and
[`COMPLIANCE_ASVS_L2_2026-06-16.md`](COMPLIANCE_ASVS_L2_2026-06-16.md)
(control mapping, supersedes the 2026-06-15 snapshot).

## 1. Assets

| Asset | Confidentiality | Integrity | Availability |
| --- | --- | --- | --- |
| User credentials (password hash, TOTP secret, recovery codes) | High | High | Medium |
| Session cookies | High | High | Medium |
| Audit log (HMAC-chained) | Medium | **Critical** | High |
| User PII (email, display name, avatar) | High | Medium | Low |
| Configuration secrets (`AUDIT_HMAC_KEY`, `SECRET_KEY`, SMTP creds) | **Critical** | High | High |
| Backup archives | High | High | Medium |
| Operator console (`/admin/`) | High | High | High |

## 2. Trust boundaries

```
            ┌────────────────────────────────────────────┐
            │           Internet / corp network          │
            └────────────────────────────────────────────┘
                              │ TLS
              ┌───────────────▼────────────────┐
              │      Caddy (reverse proxy)     │  ← trust boundary T1
              └───────────────┬────────────────┘
                              │ HTTP (loopback)
              ┌───────────────▼────────────────┐
              │      uvicorn + Django ASGI     │  ← trust boundary T2
              │  (request_id, security headers,│
              │   sudo gate, maintenance flag) │
              └───────────────┬────────────────┘
                              │ DB protocol
              ┌───────────────▼────────────────┐
              │    PostgreSQL (or SQLite dev)  │  ← trust boundary T3
              └────────────────────────────────┘

   ┌──────────────────────────┐
   │ ameli-app CLI (operator) │  ← trust boundary T4
   └─────────────┬────────────┘
                 │
   ┌─────────────▼────────────┐
   │ systemd notifier / mtnce │  ← trust boundary T5
   │ workers (SMTP, sweep)    │
   └──────────────────────────┘
```

- **T1**: TLS termination boundary. The reverse proxy is responsible
  for HTTPS, HSTS, optional WAF, IP allowlists for ops endpoints.
- **T2**: HTTP request boundary inside Django. Middleware enforces
  authentication, sudo grants, CSP, maintenance mode, request-id
  propagation, idle/disabled-user logout.
- **T3**: Persistence boundary. The DB stores HMAC-chained audit rows,
  hashed credentials, sessions, and operational queues.
- **T4**: Operator boundary. CLI commands run as the deploy user; the
  audit-key rotation reads keys via `--*-env` / `--*-stdin` (never argv).
- **T5**: Async worker boundary. SMTP delivery + retention sweep run
  out-of-band; failures land as structured journalctl ticks.

## 3. STRIDE per boundary

### T1 — Reverse proxy

| Threat | Vector | Mitigation |
| --- | --- | --- |
| Spoofing | Spoofed `X-Forwarded-For` to bypass throttle | `TRUSTED_PROXIES` allowlist (`settings.py`); `client_ip` only honours XFF when REMOTE_ADDR is in the list. |
| Tampering | Header injection (newlines in `X-Request-Id`) | `_coerce_inbound` regex `[A-Za-z0-9._-]{1,128}` (`request_id.py:36`). |
| Information disclosure | TLS downgrade | `SECURE_HSTS_SECONDS=31536000` outside dev; `SECURE_PROXY_SSL_HEADER` hint in `settings.py:308`. |
| Denial of service | Volumetric attack | Operator-tier concern; rate-limit at the proxy. |
| Elevation of privilege | Host header injection on password reset | `_build_public_base_url` refuses to fall back to `request.build_absolute_uri` outside dev (`accounts/views.py`). |

### T2 — Django application

| Threat | Vector | Mitigation |
| --- | --- | --- |
| Spoofing — session takeover | Cookie theft | `SESSION_COOKIE_HTTPONLY`, `SESSION_COOKIE_SECURE` (outside dev), `SameSite=Lax`, `Cache-Control: no-store` on authenticated responses. |
| Spoofing — credential stuffing | Brute force | Sliding-window throttle per IP + per user (`services.py:_read_throttle_counter_sliding`); permanent lockout after N consecutive windows. |
| Spoofing — phishing target | Look-alike reset URL | `public_url_base` pins the canonical host. |
| Tampering — audit log | Direct DB write | HMAC SHA-256 forward chain + `verify_audit_chain` CLI + systemd timer. Re-chain after prune so post-prune rows stay verifiable. |
| Tampering — CSRF | Cross-origin POST | Django CSRF middleware on every POST; `__Host-` cookie naming pending (ASVS V3.4.4). |
| Tampering — XSS | Reflected/stored markup | Django auto-escape + per-request CSP nonce, no `unsafe-inline` in `script-src`. CSP relaxed only on `/django-admin/*`. |
| Repudiation | Action denial | Every privileged action emits an audit row keyed to the actor; chain prevents silent edits. |
| Information disclosure | Detailed error pages | `DEBUG=False` boot-guarded outside dev; default 404/500 are generic. |
| Information disclosure — username enumeration | Login / forgot-password timing | Forgot-password returns identical payload + Argon2 timing pad (`services.py:request_password_reset`). |
| Information disclosure — PII in logs | Untyped `extra=` dict promoted by JSON formatter | Tracked as ASVS V7.1 gap (#19b in the roadmap). |
| Denial of service | Account lockout abuse | Per-IP + per-user throttles split so an attacker cannot lock a user by burning their IP budget. |
| Elevation of privilege — sudo bypass | Stolen session in `/admin/` | Every write admin endpoint stacks `@superadmin_required + @sudo_required`; sudo grant revoked on password change AND logout (both JSON and HTML branches). |
| Elevation of privilege — SSRF | Operator-supplied URL (avatar export, future webhooks) | Avatar is uploaded, not fetched. Webhooks were removed in `641ece1`; if re-introduced, port `_assert_target_is_safe` (RFC1918, loopback, metadata, reserved). |
| Elevation of privilege — privilege escalation via TOTP | MFA bypass | TOTP / email codes single-use; recovery codes invalidate on use. |
| Elevation of privilege — admin panel via Django native admin | `/django-admin/` is more powerful than `/admin/` | `DjangoAdminSudoGateMiddleware` forces a fresh sudo grant before any `/django-admin/*` request. Gated by `is_staff` (not just `is_superadmin`) so a User row with `is_staff=True` reached via DB bypass still hits the gate. |
| Elevation of privilege — MFA method downgrade / stacked-method takeover | Cookie thief enrolls a SECOND MFA method (e.g. email on a TOTP-only account) or regenerates recovery codes, gaining persistent backdoor | Cookie-thief hardening (Phase B Bloque A, 24-jun): `mfa_start_view`, `mfa_email_start_view`, `mfa_regenerate_view` all require `current_password` re-auth. `verify_mfa_view` also throttled with the login sliding-window so brute-force of the 6-digit space is gated. |
| Elevation of privilege — must-change-password user reads sensitive profile data | Temp credential issued by admin reset gives access to `/profile/` GET which renders MFA enrolment + sessions + audit tabs | `MustChangePasswordMiddleware` allow-list narrowed to `/profile/password/` standalone form (Bloque A4, 24-jun). |
| Information disclosure — telemetry exporter trust | Operator points `AMELI_APP_OTEL_EXPORTER_OTLP_ENDPOINT` to untrusted endpoint; `opentelemetry-instrumentation-psycopg` captures SQL + parameters including PII / credentials in WHERE clauses | Endpoint is opt-in (default OFF). Operator-supplied — falls under §5 (compromised operator). DOCUMENTED in `OPERATIONS.md` §"OpenTelemetry tracing": validate endpoint TLS + tenant ownership before enabling. |
| Information disclosure — profiler activation in prod | `AMELI_APP_SILK_ENABLED=true` accidentally set in prod records full request/response bodies including auth tokens, MFA codes, password fields | Boot guard requires BOTH `AMELI_APP_SILK_ENABLED=true` AND `AMELI_APP_SILK_ALLOW_PROD=true` outside dev (`settings.py:232-241` raises `RuntimeError` on the second-key drift). Two-key activation prevents single-config-drift compromise. Silk DB is local-disk only (not exported). |
| Information disclosure — JSON branch over-posting | `update_preferences` JSON path bypassed form validation, accepted arbitrary-length `display_name` | Slice `[:80]` mirror of model `max_length` (Phase B B4, 24-jun). |
| Denial of service — circuit breaker forced-open | Attacker induces N failures upstream (clamd unreachable, SMTP timeout, HIBP rate-limit) to flip breaker to OPEN; subsequent calls short-circuit | Breakers re-probe on schedule (`half_open_after_seconds` configurable per breaker). Failure modes are FAIL-CLOSED: AV breaker open path REJECTS the upload (no bypass); SMTP breaker queues with retry + caps attempts; HIBP breaker open path REJECTS (assumes leak). State is per-process — restart resets. |
| Denial of service — maintenance gate forced-open | Attacker induces transient DB error during maintenance window so the `MaintenanceModeMiddleware._state` query fails and (previously) returned `active=False`, opening writes | `OperationalError` now FAILS CLOSED with `active=True, read_only=True` (Phase B B6, 24-jun). `ProgrammingError` (unmigrated table) still swallowed silently as legitimate first-boot path. |

### T3 — Database

| Threat | Vector | Mitigation |
| --- | --- | --- |
| Tampering | Attacker with DB write access | Audit chain HMAC catches edits; retention prune re-chains survivors. Backup pipeline produces MANIFEST.sha256 so a silent corruption is caught before restore. |
| Information disclosure | DB exfiltration | Credentials are Argon2id-hashed; audit chain detects exfiltrating actor; encrypted backups (`AMELI_APP_BACKUP_GPG_RECIPIENT`). |
| Denial of service | Unbounded growth | Retention sweep purges sessions, throttle counters, email queue, MFA challenges, email-change requests on a cadence. |

### T4 — Operator CLI

| Threat | Vector | Mitigation |
| --- | --- | --- |
| Information disclosure | Keys leaked via argv (visible in `ps`) | `rotate-audit-key` exposes `--*-env` and `--*-stdin`; argv path is documented as insecure. |
| Tampering | Operator-supplied env file rewrite | `apply_audit_key_to_env_file` uses `O_NOFOLLOW` + atomic rename + parent-dir fsync, refusing to follow a symlink. |
| Elevation | Bootstrap admin password reuse | `bootstrap-admin` forces `must_change_password=True`. |

### T5 — Workers

| Threat | Vector | Mitigation |
| --- | --- | --- |
| Spoofing | Worker writes audit rows in the wrong actor | Workers tag audit rows with `actor=""` (system); the audit verifier doesn't care about actor for chain integrity. |
| Denial of service | Worker crash leaves queue stuck | Retention sweep wraps the run in try/except and emits `{ok:false, error:...}` on failure; SMTP retry queue caps attempts + records `last_error` for the admin panel. |

## 4. Attack scenarios (high-level)

These are the scenarios the team explicitly considers when reviewing a
PR. Each one names the defender(s) that should fire.

| ID | Scenario | First-line defence | Second-line |
| --- | --- | --- | --- |
| S-01 | Stolen session cookie used from another machine | UA / IP delta surfaced in `/profile/sessions/`; user can revoke | `is_active=False` kicks the session on next request |
| S-02 | Credential stuffing campaign | Sliding-window throttle per IP + per username | Permanent lockout after N consecutive lockout windows |
| S-03 | Phishing target lands on look-alike host | `public_url_base` forces the canonical URL in reset emails | HSTS + `__Host-` (pending) |
| S-04 | Insider with DB write tampers an audit row | HMAC chain mismatch on `verify-audit` | Systemd timer paged the operator |
| S-05 | Compromised admin session escalates to Django native admin | `/django-admin/` sudo gate (`DjangoAdminSudoGateMiddleware`) | Recent sudo grant required (`sudo_until` short TTL) |
| S-06 | Email forwarding setting changed to attacker mailbox | Double-opt-in (`/profile/email-change/`) requires password + new-address confirmation | Alert email to OLD address with cancel link |
| S-07 | MFA disabled by social-engineered admin | Admin disabling MFA requires sudo grant | Email notification to the user whose MFA was disabled |
| S-08 | Operator runs CLI with key in argv | Audited via shell history → `ps` of running CLI | `--*-env` / `--*-stdin` are the documented path |
| S-09 | Backup archive intercepted in transit | GPG encryption opt-in via `AMELI_APP_BACKUP_GPG_RECIPIENT` | MANIFEST.sha256 catches corruption |
| S-10 | SSRF via a future webhook URL | `_assert_target_is_safe` (port if/when webhooks return) | Operator network egress policy |
| S-11 | Cookie thief enrolls a SECOND MFA method on victim's account for persistent backdoor | `current_password` re-auth required on `mfa_start_view` / `mfa_email_start_view` / `mfa_regenerate_view` (Phase B A1/A2, 24-jun) | Audit row on every MFA enrolment + email notification to user (path exists in `services.send_*_alert`, planned to wire) |
| S-12 | Attacker holds pending-MFA session and brute-forces TOTP 6-digit space | `check_login_throttle` + `record_login_failure` on `verify_mfa_view` POST (Phase B A3, 24-jun) — same sliding-window infra as password step | Permanent lockout after N consecutive lockout windows |
| S-13 | Operator points OTel exporter at untrusted endpoint; psycopg auto-instrument leaks SQL + PII | Endpoint defaults to UNSET; opt-in via env var only; documented as operator-validated. Falls under §5 (operator compromise). | Disable via `unset AMELI_APP_OTEL_EXPORTER_OTLP_ENDPOINT`; instrumentation can be filtered per-span if needed (future hook) |
| S-14 | django-silk accidentally enabled in prod records full request/response bodies including secrets | Two-key boot guard: `AMELI_APP_SILK_ENABLED=true` AND `AMELI_APP_SILK_ALLOW_PROD=true` required outside dev; single env-var drift refuses to boot. | Silk DB is local-disk only (not network-exported); operator can purge with `python -m silk.management.commands.silk_clear` |
| S-15 | Attacker induces clamd / SMTP / HIBP failure burst to force circuit breaker OPEN, then leverages the open state | Breaker open paths FAIL-CLOSED per call: AV breaker REJECTS upload, SMTP breaker queues with retry cap, HIBP breaker REJECTS password as if leaked. Re-probe schedule prevents permanent denial. | Per-process state — `systemctl restart` resets; operator paged when retry queue exceeds threshold |
| S-16 | Attacker exhausts DB connection pool during maintenance window so the maintenance-state query fails | `MaintenanceModeMiddleware._state` catches `OperationalError` and FAILS CLOSED (`active=True, read_only=True`) — Phase B B6, 24-jun. Previously fail-opened. | Audit log + operator alert on the OperationalError surface |
| S-17 | Holder of a temp credential issued via admin reset reads `/profile/` to enumerate MFA enrolment + active sessions before rotating the password | `MustChangePasswordMiddleware._ALLOWED_EXACT` narrowed to `/profile/password/` standalone form (Phase B A4, 24-jun). Other tabs unreachable until rotation. | Audit row on every `must_change_password` redirect |

## 5. Out of scope

The template does not defend against:

- A compromised reverse proxy. If Caddy is hostile, every other control
  is moot.
- A compromised operator account on the host. The operator can read
  every secret, every key, every audit row.
- A compromised CI / build pipeline. Pin SHAs in `requirements.lock`
  to make this harder; CI security is the operator's concern.
- Side channels on the underlying hardware (Spectre, Rowhammer).
- Coercion of the legitimate user holding a hardware key.

## 6. Review cadence

| Trigger | Action |
| --- | --- |
| New auth path (e.g. OAuth) | Re-do STRIDE on the new boundary; update T2. |
| New external integration | Add to the diagram; STRIDE the boundary. |
| New persistence layer | Update T3; review audit-chain coverage. |
| Major dep upgrade | Re-run security review skill; revise residual risks. |
| New telemetry / profiling pipeline | Re-STRIDE the egress boundary; document operator-validated invariants (TLS, tenant ownership) in `OPERATIONS.md`. |
| New circuit breaker | Document open-path semantics (fail-closed vs fail-open vs queue) in STRIDE T2; add scenario row mirroring S-15. |
| Quarterly | Re-check residual risk register; bump dates. |

## 7. Change log

| Date | Change |
| --- | --- |
| 2026-06-25 | Phase B item #2 (PB-2): added §3 T2 entries for OTel exporter trust (S-13), django-silk activation (S-14), circuit breaker forced-open (S-15), maintenance gate forced-open (S-16), MFA method downgrade (S-11), MFA brute-force on pending session (S-12), must-change-password GET leak (S-17), update_preferences JSON over-posting. Mitigations cite the Phase B Bloque A + B fixes commits `a1e2626` (cookie thief) + `4a131d3` (MED-priority hardening). |
| 2026-06-16 | Initial mapping. ASVS L2 superseded the 2026-06-15 snapshot. |
