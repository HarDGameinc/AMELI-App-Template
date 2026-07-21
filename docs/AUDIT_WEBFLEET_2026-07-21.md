# Audit — WebFleet outbound integration (2026-07-21)

Architecture audit for an outbound integration from a Django AMELI app
against the **WebFleet** REST API (TomTom fleet management platform).
The audit stays at the **template layer** — it lists what to verify and
which existing template pieces to reuse — because the integration itself
belongs in a child app (see [§5](#5-location-and-when-to-lift-into-the-template)).

Companion docs:
- [`SECURITY.md`](SECURITY.md) — threat model, controls.
- [`PRIVACY.md`](PRIVACY.md) — data inventory, retention, user rights.
- [`OPERATIONS.md`](OPERATIONS.md) — operational procedures, secret rotation.
- [`DECISIONS.md`](DECISIONS.md) — architectural decisions (#7 template
  propagation, #9 dev environment).

## 1. Scope

- **Flow**: outbound only. The child app calls the WebFleet REST API
  (positions, vehicles, drivers, routes). WebFleet does NOT push to us
  (no inbound webhooks in this scope; if that changes, a separate audit
  section is needed for HMAC verification + replay protection + IP
  allowlist).
- **CORS: not applicable.** The integration is server-to-server; CORS is
  browser-only. Confirmed by inspection (no `django-cors-headers`, no
  `CORS_*` settings, no `Access-Control-*` headers set — only COOP/CORP
  which are cross-origin *isolation*, not CORS).
- **PII implications**: significant. Vehicle positions tied to a driver
  are location data under GDPR / Chile Law 21.719 (data protection).
  License plates linked to an operator can also qualify. Anything the
  child persists from the WebFleet response crosses into `PRIVACY.md`.

## 2. Audit findings by surface

Not defects in the template — this is a **checklist** the implementer
must satisfy when the child app writes the WebFleet client. Each row
names the risk, the mitigation, and the existing template piece to
reuse.

### 2.1 Credentials (API key / OAuth2)

| Item | Requirement | Reuse |
|---|---|---|
| Storage | Never hardcode. Env var via `app.env`. If the provider issues long-lived refresh tokens, encrypt at rest with Fernet — same pattern as the TOTP secret. | [`settings/auth.py:85`](../src/ameli_web/settings/auth.py) `AMELI_APP_MFA_ENCRYPTION_KEY`; [`accounts/mfa.py`](../src/ameli_web/accounts/mfa.py) encrypt/decrypt |
| Rotation | Runbook entry with cadence, portal steps, dual-key rollout window. | Extend [`OPERATIONS.md:1355`](OPERATIONS.md) → "Secret rotation" (4 keys documented today; WebFleet becomes the 5th) |
| No logs | Exception messages routinely include the endpoint URL and auth headers. Wrap them before logging. | [`accounts/av.py:154`](../src/ameli_web/accounts/av.py) `_redact` — copy the pattern into the WebFleet client |
| OAuth2 (if applicable) | Separate access token (in-memory / short cache) from refresh token (persisted encrypted). Preemptive refresh before expiry with jitter. | — no direct precedent in the template; document design decision in the child |

### 2.2 Wire (HTTP client)

| Item | Requirement | Reuse |
|---|---|---|
| TLS verification | Never `verify=False`. Default cert store. | [`cli.py`](../src/ameli_app/cli.py) `_handle_template_check` — stdlib `urllib.request.urlopen(..., timeout=...)` pattern; already ships with `# noqa: S310  # nosec B310` where needed |
| Timeout | Explicit, always. Suggested: 10 s for synchronous single-record calls; 60–120 s for bulk history queries. | Same as above (`--timeout` arg in template-check) |
| Retry + circuit breaker | Half-open state, exponential backoff with jitter, threshold + cooldown from settings. | **[`accounts/circuit_breaker.py:40`](../src/ameli_web/accounts/circuit_breaker.py) — `CircuitBreaker` class is generic.** Today it has `get_av_breaker`, `get_hibp_breaker`, `get_smtp_breaker`. Add `get_webfleet_breaker` in the child (~10 LOC following the same pattern) or import the class directly. |
| SSRF | If `vehicle_id` / `driver_id` land in the URL, use `urllib.parse.quote`, never string concat. Base URL as a hardcoded constant. | — pattern discipline; no template code to reuse |
| Observability | Auto-tracing via OTel. | Already in the lock: `opentelemetry-instrumentation-urllib` ([`requirements.lock:369`](../requirements.lock)). Just name the outbound span so it filters cleanly. |

### 2.3 Rate limits and cost

WebFleet has per-plan quotas and per-endpoint rate limits. A bug can
burn the plan's quota in minutes and lock the child out.

| Item | Requirement | Reuse |
|---|---|---|
| Client-side throttle | Track your outbound rate. Alert at 80 % of quota. | [`accounts/models.py:211`](../src/ameli_web/accounts/models.py) `ThrottleCounter` — scope=`"outbound_webfleet"`, key per endpoint. The atomic bumper [`services/throttle.py:58`](../src/ameli_web/accounts/services/throttle.py) `_bump_throttle_counter` reuses cleanly for outbound. |
| 429 handling | Respect `Retry-After`. The circuit breaker fails fast after N consecutive 429s. | [`circuit_breaker.py`](../src/ameli_web/accounts/circuit_breaker.py) — same instance |
| Cache | GETs of slow-changing data (vehicle list, zones) with short TTL. | Django cache framework (already available; no extra dep) |

### 2.4 Data at rest (the big one)

This is the surface that most demands the child-app-side effort. Do
NOT persist the raw WebFleet JSON. Normalize to Django models with
only the fields the app uses; smaller payload = faster backup encryption,
cleaner audit, less erasure surface.

| Item | Requirement | Reuse |
|---|---|---|
| Retention windows | Positions, driver events, route history each get an explicit window. Document the choice per jurisdiction. | Extend [`services/retention.py:29–33`](../src/ameli_web/accounts/services/retention.py) with e.g. `webfleet_positions_max_age_days`, sweep pattern identical to existing rows |
| Access control | The template ships `superadmin` / `public`. A fleet integration needs at minimum a third role (e.g. `fleet_manager`) and probably per-vehicle ownership. | [`models.py:16`](../src/ameli_web/accounts/models.py) User model + role choices — extend in the child; keep the `has_role` / decorator pattern |
| Erasure | On driver leave: purge or anonymize their position history? Trade-off same as audit vs. erasure. Document explicitly. | [`PRIVACY.md §8`](PRIVACY.md) "Audit log vs. erasure" pattern — extend the same way |
| Backups | Everything above lands in `pg_dump`; enforce GPG recipient. Note that a backup restored *after* erasure must be re-purged. | [`OPERATIONS.md`](OPERATIONS.md) "Backup + restore" already covers `AMELI_APP_BACKUP_GPG_RECIPIENT` |

### 2.5 Failure modes

| Item | Requirement | Reuse |
|---|---|---|
| Graceful degradation | When WebFleet is down or the breaker is open, the UI shows "data temporarily unavailable" — not 500. Propagate breaker state to views. | Pattern: catch `CircuitBreakerOpen` in the view, render a degraded state |
| Health probe | Consider a barely-there ping to a WebFleet version endpoint in `/health/deep`. Fail the deep probe when the breaker is open. | Existing `/health/deep` structure ([`OPERATIONS.md`](OPERATIONS.md) §Health checks) |
| Alerting | "N consecutive failures to WebFleet in M minutes" → email operator. | [`services/auth_alerts.py`](../src/ameli_web/accounts/services/auth_alerts.py) — clone the auth-failure alert pattern (threshold + cooldown + throttle) |

### 2.6 Audit trail

Every **mutation** the child performs against WebFleet (create geofence,
change a vehicle plan) belongs in the local audit chain — HMAC-protected
against a later "no fui yo" dispute.

| Item | Requirement | Reuse |
|---|---|---|
| Log the mutation | `AuditEvent` with `action="webfleet_<verb>"`, payload = normalized parameters (NO raw secrets). | [`audit/models.py`](../src/ameli_web/audit/models.py) + [`services/audit.py`](../src/ameli_web/accounts/services/audit.py) — same call sites as any other audit event |
| Log ONLY on mutation | Reads to WebFleet should NOT flood the audit log — they go to normal request logs / OTel spans. | Pattern discipline; no template code change |

### 2.7 Compliance — PRIVACY.md addendum

The child app extends `PRIVACY.md`, not the template's copy.

- Add WebFleet to **§7 Third-party processors**: what leaves the host
  (auth credentials, request parameters — never end-user data unless
  the API takes it), TomTom's jurisdiction, DPA reference. See
  [`PRIVACY.md:122`](PRIVACY.md) for the shape.
- Extend **§2 Data inventory** with the new stores (positions,
  driver_events, routes …), fields, purpose, and protection notes.
- Extend **§3 Retention** with the windows chosen for those stores.
- Extend **§6 User rights** — how a driver's data is accessed,
  rectified, and erased when they request it (per data-subject request
  in the operator's jurisdiction).
- Extend **§10 What the operator must decide per deploy** — legal
  basis for processing location data (typically contract with the
  fleet operator, sometimes legitimate interest; rarely consent),
  cross-border transfer to TomTom, retention rationale.

## 3. Reusable template pieces (summary)

The child does **not** need to reinvent any of these. Every column
below is a working, tested piece already in the template:

| Need | Reuse | File |
|---|---|---|
| Circuit breaker (retry + backoff + open/half/closed states) | `CircuitBreaker` class — generic | [`accounts/circuit_breaker.py:40`](../src/ameli_web/accounts/circuit_breaker.py) |
| Outbound HTTP with timeout, no SSL surprises | `_handle_template_check` reference implementation | [`ameli_app/cli.py`](../src/ameli_app/cli.py) |
| Client-side rate limit tracking | `ThrottleCounter` + `_bump_throttle_counter` | [`accounts/models.py:211`](../src/ameli_web/accounts/models.py), [`services/throttle.py:58`](../src/ameli_web/accounts/services/throttle.py) |
| Retention sweep with tunable windows | `services/retention.py` argument pattern | [`services/retention.py:29`](../src/ameli_web/accounts/services/retention.py) |
| Fernet encryption for tokens at rest | TOTP secret storage precedent | [`settings/auth.py:85`](../src/ameli_web/settings/auth.py), [`accounts/mfa.py`](../src/ameli_web/accounts/mfa.py) |
| Secret rotation runbook shape | OPERATIONS "Secret rotation" section | [`OPERATIONS.md:1355`](OPERATIONS.md) |
| PII redaction in exception logs | `_redact` helper | [`accounts/av.py:154`](../src/ameli_web/accounts/av.py) |
| Hash-chained audit trail | `AuditEvent` + `services/audit.py` | [`audit/models.py`](../src/ameli_web/audit/models.py) |
| Auto-tracing for outbound HTTP | `opentelemetry-instrumentation-urllib` already installed | [`requirements.lock:369`](../requirements.lock) |
| Third-party processor documentation shape | PRIVACY.md §7 | [`docs/PRIVACY.md:122`](PRIVACY.md) |

## 4. What is NOT in scope for this audit

- **Inbound webhooks from WebFleet.** If added later, they need HMAC
  signature verification, replay protection (timestamp + nonce),
  IP allowlist, rate limit on our receiving endpoint, and idempotency
  keys. Separate audit section.
- **The WebFleet API contract itself** (endpoint shape, auth scheme
  specifics, quota tiers). The auditor writing this document does not
  have API access; the implementer verifies against WebFleet's current
  docs and adjusts. What is documented here is *what to verify*, not
  claims about WebFleet's product.

## 5. Location — and when to lift into the template

**Recommendation: implement in the child app** (Starlink or a new fork),
not in the template.

Reasoning:
- WebFleet is a **vertical** concern (fleet management). Only apps that
  manage vehicles will call it. Others should not carry the code or the
  supply-chain surface.
- The template's own principle
  ([DECISIONS #7](DECISIONS.md#7-template-update-propagation--git-upstream--releases-not-a-package-yet))
  is "keep the core lean; child apps diverge for verticals".
- **Rule of Three**: if a *second* AMELI app also integrates WebFleet
  later, extract to a versioned `ameli-fleet` package (this maps to
  DECISIONS #7 model C applied at the vertical layer). Do not
  pre-generalize before the second use case exists.

## 6. Open questions (implementer to answer before coding)

1. **Auth scheme**: API key (single static header) or OAuth2 (access +
   refresh)? Determines credential storage (env-only vs Fernet at rest)
   and refresh flow complexity.
2. **Expected volume**: how many vehicles, how many positions per hour?
   Determines whether client-side throttling and endpoint-level caching
   are day-one requirements.
3. **Persistence model**: only current snapshot (live dashboard) or
   historical (routes, mileage, event log)? Historical persistence
   triggers the full PRIVACY block (retention, erasure, backups).
4. **Location**: which child app? Determines file paths and the
   PRIVACY.md addendum target.

## 7. Change log

- **2026-07-21** — initial audit. Written during the WebFleet integration
  planning session; no code shipped yet. The document is the deliverable
  requested by the operator ("por el momento documentalo").
