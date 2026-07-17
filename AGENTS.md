# AMELI App Template — canonical handoff

## Reading order (LLM sessions)

1. **`AGENTS.md`** — this file: purpose, architecture, policies.
2. **`docs/HANDOFF_TEMPLATE.md`** — handoff structure + skills playbook (S-01 to S-08).
3. **Most recent `docs/CLAUDE_HANDOFF_YYYY-MM-DD_*.md`** — session context to continue from.
4. **`docs/SECURITY.md`** + **`docs/THREAT_MODEL.md`** — security posture and STRIDE trust boundaries.
5. **`docs/COMPLIANCE_ASVS_L2_2026-06-16.md`** — current ASVS L2 mapping (151 PASS, 0 strict GAP).
6. **`docs/BUILDING_NEW_APP.md`** — onboarding for forks: what you inherit, what to rename, what NOT to touch.
7. **`CLAUDE.md`** — per-project instruction overrides for LLM agents.

## Purpose

Official **Django-first template** for AMELI applications exposed to real users (internet or internal operational networks). Provides auth, MFA, profile, admin panel, audit log, and deployment tooling out of the box.

## Architecture

```
src/ameli_app/          # Runtime, CLI, workers, static assets, config helpers
  config.py             # YAML-based app config loader
  cli.py                # ameli-app CLI entry point
  api.py                # Django ASGI launcher (Uvicorn)
  web.py                # Alternate web launcher
  database.py           # DB helpers
  password_policy.py    # Server-side policy validation
  workers/              # Background workers (capture, notify, maintenance)
  static/               # CSS (app.css), JS (app.js)

src/ameli_web/          # Django web layer
  settings/             # Django settings — domain-split package (PC-4 closed)
    __init__.py         #   Orchestrator (imports submodules in critical order)
    base.py             #   BASE_DIR, PROJECT_DIR, CFG, ENV_NAME, ALLOWED_HOSTS, TRUSTED_PROXIES
    integrations.py     #   CDN SRI, health allowlist, HIBP, AV, OTel, Silk toggle
    auth.py             #   PASSWORD_HASHERS, validators, AUDIT_HMAC_KEY, MFA_ENCRYPTION_KEY, LOGIN_URL
    cookies.py          #   SESSION_COOKIE_*, CSRF_COOKIE_*, __Host- guards
    security_headers.py #   HSTS, X-Frame-Options, proxy SSL, MESSAGE_STORAGE
    i18n_static.py      #   LANGUAGE_CODE, TIME_ZONE, STATIC_URL, MEDIA_ROOT + path guards
    media.py            #   Avatar transform knobs (AVATAR_FORMAT / MAX_DIMENSION / WEBP_QUALITY) (D-5)
    database.py         #   DATABASES + psycopg pool option
    applications.py     #   INSTALLED_APPS, MIDDLEWARE, TEMPLATES, WSGI/ASGI
    email.py            #   EMAIL_BACKEND, SMTP, PASSWORD_RESET_TIMEOUT
  urls.py               # URL configuration
  asgi.py / wsgi.py     # ASGI/WSGI entry points
  accounts/             # Auth, MFA, profile, sessions, password reset
    models.py           # User, UserSession, MFARecoveryCode, MFAEmailChallenge,
                        # EmailChangeRequest, ThrottleCounter, OutboundEmail,
                        # MaintenanceMode
    services/           # Business logic — domain-split package (PC-1 fully closed)
      __init__.py       #   Pure re-export surface (~200 lines)
      audit.py          #   Hash-chained audit log, HMAC key rotation (462 lines)
      auth_alerts.py    #   Auth-failure alert (ASVS V2.2.3) (189 lines)
      email_change.py   #   Email-change double-opt-in flow (302 lines)
      email_queue.py    #   SMTP circuit breaker, outbox pattern (426 lines)
      images.py         #   Avatar transform: resize + WebP + strip EXIF (D-5)
      maintenance.py    #   Maintenance mode get/enable/disable (83 lines)
      mfa.py            #   TOTP, email MFA, recovery codes (545 lines)
      password_reset.py #   Password reset request/verify/complete (178 lines)
      reporting.py      #   User + email-queue summaries + audit serialization (286 lines)
      retention.py      #   Retention sweep + audit chain re-anchor (194 lines)
      session.py        #   Session sync/revoke, listing/pagination (234 lines)
      sudo.py           #   Sudo grants, brute-force gate (211 lines)
      throttle.py       #   Atomic counters, lockout, rate limits (495 lines)
      user.py           #   User CRUD, serialize, avatars, password/email/account (543 lines)
    views.py            # View functions (1267 lines — target for splitting)
    mfa.py              # MFA secret encryption/decryption, QR code render
    forms.py            # Django forms
    validators.py       # Password policy validators
    middleware.py        # Auth middleware (433 lines)
    context_processors.py
    templatetags/sri.py # Subresource Integrity tag
  audit/                # Hash-chained audit log
    models.py           # AuditEvent with prev_hmac/hmac chain
  dashboard/            # Home, health, docs, redoc views
  admin_views/          # Admin panel views — domain-split package (PC-3 closed)
    __init__.py         #   Pure re-export surface
    _common.py          #   Decorators + PER_PAGE_COOKIE constants + helpers
    panel.py            #   admin_panel (HTML dashboard)
    users.py            #   users list/CRUD + password reset + MFA disable + unlock
    audit.py            #   admin_audit (list)
    exports.py          #   audit / users CSV+JSON export
    maintenance.py      #   maintenance toggle + status
    metrics.py          #   email queue metrics
    sessions.py         #   sessions list + revoke
    sudo.py             #   sudo grant + email code + status + django-admin gate
  error_views.py        # 400/403/404/500 handlers

manage.py               # Django management entrypoint (autodiscover config)
```

## Runtime

- **Web:** Django ASGI via `python -m ameli_app.api` (Uvicorn)
- **Alternate:** `python -m ameli_app.web`
- **Database:** PostgreSQL (production) / SQLite (local dev)
- **No FastAPI dependency.**

## Public routes

| Route | Description | Auth |
|-------|-------------|------|
| `/` | Dashboard home | Optional |
| `/login` | Login | None |
| `/logout` | Logout | Session |
| `/profile` | User profile (tabs: general, security, sessions) | Required |
| `/profile/email-change/*` | Double-opt-in email change flow | Required |
| `/admin` | Admin console (users, audit, sessions, maintenance) | Superadmin |
| `/health` | Health endpoint (JSON) | None |
| `/api/health` | API health (JSON) | None |
| `/docs` | Swagger UI | Configurable |
| `/redoc` | ReDoc | Configurable |
| `/openapi.json` | OpenAPI schema | None |

## Security model

### Authentication
- **Password policy:** 12+ chars, ≥1 upper, ≥1 lower, ≥1 digit, ≥1 symbol from `!@#$%^&*()-_=+?`
- **MFA:** TOTP (app) + email (simultaneous enrollment supported)
- **Recovery codes:** Generated on MFA enrollment, one-time use
- **Throttling:** Atomic `ThrottleCounter` with `select_for_update()` — prevents TOCTOU
- **Hard lock:** After repeated lockout windows (no time-based unlock)
- **Session management:** DB-persisted, revocable, absolute ceiling timeout
- **Cookie-thief hardening:** Password required for MFA enrollment/disabling/regeneration

### Authorization
- Roles: `superadmin` (full access) / `public` (self-service only)
- Admin requires sudo prompt for sensitive actions (with MFA support)

### Frontend security
- **CSP:** Per-request nonces on all inline `<script>` tags
- **Trusted Types:** `ameli-template` policy enforced via CSP header
- **SRI:** `{% sri_for %}` computes SHA-384 hashes for own static assets
- **Honeypot:** Hidden field in login form traps bots
- **CSRF:** `x-csrf-token` header on all state-changing requests
- **AV scan:** Avatar uploads scanned before storage

### Audit
- `AuditEvent` table with hash chain (`prev_hmac` / `hmac`) for tamper detection
- Auth failure alerts with configurable cooldown
- Email change alerts sent to old address

## CLI commands

| Command | Description |
|---------|-------------|
| `ameli-app version` | Print version |
| `ameli-app config-check` | Validate config |
| `ameli-app db-status` | Database connectivity check |
| `ameli-app bootstrap-admin` | Create initial superadmin |
| `ameli-app create-user` | Create user from CLI |
| `ameli-app list-users` | List all users |
| `ameli-app worker-once` | Run worker once |
| `ameli-app notify-once` | Process email queue once |
| `ameli-app maintenance` | Toggle maintenance mode from CLI |
| `ameli-app template-check` | Compare template lineage vs the latest release (exit 1 if behind) |

## Install / Update

- **Install:** `scripts/install.sh` — venv, deps, migrate, check, optional superadmin bootstrap, systemd units
- **Update:** `scripts/update.sh` — pull code, reinstall deps, re-run migrations/checks
- **Validate:** `scripts/validate_installation.sh` — CLI + Django health + PostgreSQL check
- **Lockfile:** `requirements.lock` with `--require-hashes` (ASVS V14.2.3)
- **Systemd:** 16 unit files in `deploy/systemd/`, configurable via `APP_SYSTEMD_PROFILE`
- **Server facts (never guess):** paths/unit names/port are *derived* from
  `APP_INSTANCE`, not fixed — see `docs/OPERATIONS.md` → "Deployed instance —
  ground truth" before any server op. Run `validate_installation.sh` to have
  the box report them; don't hardcode a service name or `/opt/...` path.

## Testing

- **Framework:** pytest + pytest-django (Python); Node's built-in
  `node:test` for JS helpers (`tests/js/`, run `node --test tests/js/*.test.js`)
- **Coverage:** ≥85% (enforced in `pyproject.toml`)
- **Static analysis:** ruff (enforces S security band), mypy (0 errors)
- **E2E:** Playwright (`tests/e2e/`, opt-in via `--run-e2e`)
- **CI matrix:** Python 3.11 · 3.12 · 3.13 · 3.14 (on Django 5.2 LTS,
  SQLite) + a `test-postgres` job running the suite against real
  PostgreSQL (Python 3.13) + a `js-unit` job for the JS tests + e2e +
  pip-audit
- **JS unit tests (D-4):** password generator, strength evaluator, debounce

### Test categories
- Account guards, login, MFA (TOTP, email, stacked, recovery UX, secret encryption)
- Admin CRUD (users, audit, sessions), pagination, partial swap guards
- Security hardening (blocks 1-4, phase B, cookie thief, CSRF, session timeout)
- Email (retry, double-opt-in change, password reset, auth failures alert)
- Avatar (validation, AV scan, upload UI)
- CLI, health, metrics, telemetry
- Installation scripts, backups, Docker stack, systemd units

## State of the project (v0.5.9-django, 2026-07-17)

Since v0.4.4: D-5 avatar transform pipeline (`services/images.py`: resize
+ WebP + strip EXIF/GPS), an interactive client-side avatar cropper
(`app.js:setupAvatarCropper`), the CI matrix widened to Python 3.11-3.14
on Django 5.2 LTS (D-6'), JS unit tests via `node:test` (D-4), and D-2
inline password re-auth for the MFA panel (replacing native
`prompt`/`confirm`/`alert`) plus a secure-context-gated clipboard
fallback for the recovery-code tools. Since v0.4.10: agent docs
(CONTRIBUTING/RELEASE/DECISIONS), Postgres-in-CI, an axe-core a11y gate
(light+dark, keyboard, and modal focus-trap — a11y++, `v0.4.12`), and D-1
visual identity (`v0.4.13`): navy+teal palette + DM Sans/IBM Plex
typography, plus a second theming axis — user-selectable color palettes
(Teal/Índigo/Ámbar/Violeta via ``data-palette``, orthogonal to
light/dark/auto; status colors stay constant across palettes). D-1 Phase B
(`v0.4.14`): palette-aware hero treatment (accent wash + bar + shadow),
header aligned to the content max-width, panel radius/spacing polish. D-1
Phase C (`v0.4.15`): signature "telemetry pulse" sparkline in the header
(decorative, palette-colored; /health is IP-allowlisted so the pulse does
not probe it). Phase D (`v0.4.16`): motion — staggered reveal on load +
hover states, reduced-motion-safe. **D-1 complete**, and `dev` was
**promoted to `main` as `v0.5.0-django`** (2026-07-07, PR #1 — the first
release; tag/release published, `main` is no longer frozen). `v0.5.1`
(2026-07-08): a defensive security review (3 agents by vuln class + manual
verification) closed 7 logic/config findings — env fail-closed (M1),
enforced `mfa_required` (M2), avatar-IDOR keyed on exact `avatar.name` (L1),
narrowed `decrypt_secret` (L2), two-step email-cancel (L3), last-active-
superadmin invariant (L4), honest throttle-atomicity docstring (M3); plus a
branded favicon and web-font license attribution. `v0.5.3` (2026-07-12)
completes **M3** — the deferred atomic redesign of the per-user login gate:
reserve-then-verify on a dedicated `login_gate_user` scope turns the soft
ceiling into a hard one (closing the check-then-act race), with
reset-on-success wired to `user_logged_in`; the IP gate stays failure-based
soft by design. Same release adds the `ameli-app template-check` CLI (the
update-channel "consultar" piece, `DECISIONS.md` #7), a secret-rotation
runbook and a CycloneDX SBOM procedure (both in `OPERATIONS.md`). `v0.5.4`
(2026-07-13): dropped `'unsafe-inline'` from the main CSP `style-src` — the
46 inline `style=""` across 11 templates moved to utility classes in
`app.css` (identical declarations, no visual change), leaving `script-src`
(nonces) and `style-src` (`'self'`) both inline-free; `/django-admin` +
`/docs` keep `'unsafe-inline'` for framework/CDN styles. Same release adds
an `AMELI_APP_HSTS_INCLUDE_SUBDOMAINS` env override and flips the HSTS
`includeSubDomains` **default to OFF (opt-in)**, matching Django — a host no
longer asserts HSTS for a subtree it was not told it owns (`includeSubDomains`
only ever scopes the emitting host's own subdomains, per RFC 6797, not
siblings or the parent). On the live `ha-report2` host HSTS is **Caddy-managed
per-site**; `app.example.com` got `max-age=31536000` (no `includeSubDomains`)
added to its Caddy block, and the vestigial LAN/VPN ufw allows for the
loopback-only `18080` were removed. The same release also closes two testing
gaps — Django **migration reversibility + drift** tests plus the
`0012` MFA-secret encrypt/decrypt **data-backfill** coverage, and an
**`aria-live` announcement** pass (global `#a11y-live` region + `announce()`
for the admin pagination/filter swaps, and `aria-live` on the four admin
action feedbacks). `v0.5.5` (2026-07-14) is a **security release**: the repo
went **public** (which makes GitHub Actions, CodeQL and Dependabot free), and
CodeQL's very first run found a real weakness in the second factor — the
6-digit email MFA code was digested with a bare SHA-256 into
`MFAEmailChallenge.code_hash`, so a DB-**read** compromise (SQLi, leaked
backup) could exhaust the 10⁶ space in milliseconds and recover the live code.
It is now a keyed HMAC (`salted_hmac` over `SECRET_KEY`, which never lives in
the DB) — the same reasoning that already encrypts the TOTP secret at rest.
Same release stops three handlers echoing raw SMTP exceptions to unprivileged
(and pre-MFA) callers. `pip` is deliberately excluded from Dependabot: the
hash-pinned `requirements*.lock` are already audited more precisely by
`pip-audit` on every push and on the weekly cron. `v0.5.6` (2026-07-15) is a
**maintenance** release (no app-runtime change): the first real dry run of the
"build a child app" path corrected `BUILDING_NEW_APP §2` (keeping the package
names is the recommended default and works out of the box — the old "must
rename" procedure left ~740 broken references and its verification step gave a
false pass) and fixed two `template-check` CLI bugs it surfaced (a non-ASCII
`UnicodeEncodeError` that broke the security-note channel, and an opaque
rate-limit error), plus the CI action bumps and pointing Dependabot at `dev`.
`v0.5.7` (2026-07-16) is a **maintenance** release fixing the **dev
Docker/compose path** (no app-runtime change; `src/` and the systemd/prod
deploy untouched): the child-app Docker dry-run surfaced 5 bugs — compose env
vars used inert un-prefixed names (falling back to the insecure default
`SECRET_KEY` + `DEBUG=False`), the editable-install `.pth` broke `import
ameli_web` at runtime (fixed with `PYTHONPATH=/app/src`), the image installed
the loose `requirements.txt` ranges instead of the hash-pinned lock (now
`--require-hashes -r requirements.lock` + a `dev` build target for in-container
pytest), `VERSION` was not copied (so `/health` read `v0.0.0-dev`), and a
missing `.gitattributes` let a Windows autocrlf clone break `.sh` in Linux
containers. +6 regression tests in `test_docker_stack.py` guard the fixes.
`v0.5.8` (2026-07-17) is a **docs** release (no app-runtime change) that ships
three consolidated pieces: **`docs/PRIVACY.md`** (data inventory, retention,
user rights — access/rectification/self-service erasure via
`/profile/delete-account/` — with `§10` calling out what the operator must
decide per deploy: legal basis, DPO, cross-border, portability, consent),
**`DECISIONS.md` #8** (tiered Windows/WSL2/Docker dev-environment strategy —
Windows daily loop, WSL2 for Linux parity on demand, Docker out of the agent
loop; **superseded same-day by #9**: WSL2 IS the single dev environment,
Windows-native is fallback only, no double work), and a correction that
`requirements.lock` and `requirements-dev.lock`
are **complementary, not superset/subset** (the earlier "superset" claim was
plausible only because `pytest-django` pulls `django` into both — a full dev
env needs installing both; verified on WSL2 Ubuntu 24.04: Linux suite runs
**1156 passed / 28 skipped** vs Windows 1126 / 58). `v0.5.9` (2026-07-17,
same day) ships the **`DECISIONS.md` #9 correction of #8**: WSL2 is THE
single dev environment (one clone, one venv, same hash-pinned lock that
ships to prod), local deployment runs directly under WSL2 (`python -m
ameli_app.api` against a local Postgres — no Docker), production stays on
the Linux VM `ha-report2`, and Windows-native is fallback only. `CONTRIBUTING.
md` inverted accordingly. All validated on the dev server / CI; see the
latest `docs/CLAUDE_HANDOFF_*`.

### Known architectural debt (prioritized)
1. **`accounts/services/` (PC-1 CLOSED, 2026-07-01)** — 14 domain modules; `__init__.py` is a pure re-export surface (~200 lines)
2. **`accounts/views/` (PC-2 CLOSED, 2026-07-01)** — 9 domain modules; `__init__.py` re-exports
3. **`admin_views/` (PC-3 CLOSED, 2026-07-01)** — 10 domain modules; `__init__.py` re-exports
4. **`settings/` (PC-4 CLOSED, 2026-07-01)** — 10 domain modules; `__init__.py` orquesta imports en orden crítico
5. **Inline JS in templates (CLOSED, 2026-07-03)** — extracted to external SRI-protected `static/js/profile.js` + `static/js/admin-panel.js`; templates inject server values via `data-*` on a hidden config element

### Frontend design (D-1 COMPLETE — A+B+C+D, v0.4.16)
- ~~No signature visual element~~ → header telemetry-pulse sparkline (D-1 Phase C ✓)
- ~~System-default typography~~ → DM Sans + IBM Plex Sans (D-1 Phase A ✓)
- ~~AI-generic blue-on-white palette~~ → navy+teal + 4 selectable palettes (D-1 Phase A ✓)
- ~~No visual hierarchy beyond identical grey panels~~ → palette hero + aligned layout (D-1 Phase B ✓)
- ~~No motion~~ → staggered reveal + hover states, reduced-motion-safe (D-1 Phase D ✓)
- Remaining: inline styles in a few templates (utility-class refactor is optional, not D-1)

### Testing gaps
- JS unit tests exist for the pure helpers (D-4, node:test); the DOM-wiring
  paths (cropper drag/zoom, pagination swap) are still e2e-only
- Accessibility smoke covers axe-core WCAG 2.1 A/AA (critical+serious) on
  login / forgot-password / dashboard / profile / admin in **both light
  and dark themes**, plus keyboard checks (skip-link is the first Tab
  stop; login form is reachable) plus admin dialog focus management
  (role=dialog/aria-modal, Tab trapped inside the modal, Escape closes,
  focus restored to the trigger) — `tests/e2e/test_accessibility.py`.
  **`aria-live` coverage audited 2026-07-13**: flash messages + maintenance
  banner (`role=status` in `base.html`) and the MFA / email / sudo JS
  feedbacks already announce; the admin **pagination/filter swaps were
  silent** (`aria-busy` only) — added a global `#a11y-live` region +
  `announce()` in `app.js` so each swap announces its result summary
  (`tests/test_a11y_live_region.py` + `tests/e2e/test_a11y_announce.py`).
  The four admin-panel action feedbacks (maintenance / create-user /
  change- & reset-password, updated by `admin-panel.js`) were likewise not
  live regions — fixed with `role=status aria-live=polite`. Both verified in
  a real browser. Deferred by choice: password strength/match hints are not
  live-announced (would fire on every keystroke)
- ~~No Django migration tests (apply/rollback in CI).~~ **CLOSED
  2026-07-13** — `tests/test_migrations.py`: drift (`makemigrations --check`
  in-suite) + a reverse-to-zero/re-apply round-trip proving every first-party
  migration (incl. the three `RunPython` data migrations) is reversible. Runs
  on the shared test DB with `transaction=True` + a `finally` that re-migrates
  to head. Note: the stack uses **Django migrations only** — there is no
  Alembic / SQLAlchemy (verified 2026-07-06, see `TECH_EVOLUTION.md`)
- No visual regression tests

## Source-of-truth files

- `VERSION` — current version string
- `pyproject.toml` — dependencies, tool config, metadata
- `README.md` — user-facing onboarding
- `AGENTS.md` — canonical handoff reference
- `requirements.lock` — pinned hashed dependencies

## Documentation index

| File | Purpose |
|------|---------|
| `README.md` | Main onboarding |
| `CONTRIBUTING.md` | Contributing conventions: branches, commits, pre-push checks, Windows dev notes |
| `docs/RELEASE.md` | Version scheme + bump ritual (the four files) + when to bump |
| `docs/DECISIONS.md` | Architecture decisions (ADR-lite): the durable "why" |
| `docs/ARCHITECTURE.md` | Technical structure |
| `docs/FIRST_INSTALL_DJANGO.md` | First install guide |
| `docs/OPERATIONS.md` | Operational procedures (starts with "Deployed instance — ground truth": derive server paths/units, never guess) |
| `docs/SECURITY.md` | Security posture |
| `docs/PRIVACY.md` | Data inventory, retention, user rights (access/rectification/erasure); deploy-specific gaps flagged |
| `docs/THREAT_MODEL.md` | STRIDE threat model |
| `docs/COMPLIANCE_ASVS_L2_*.md` | ASVS L2 compliance snapshots |
| `docs/HANDOFF_TEMPLATE.md` | Session handoff structure |
| `docs/FRONTEND_DESIGN_REVIEW.md` | Frontend design audit |
| `docs/THEMING.md` | Light/dark/auto theme model + the "Auto follows the browser" gotcha |
| `docs/TECH_EVOLUTION.md` | Stack/tooling assessment: keep vs evolve, ranked opportunities |
| `docs/SKILLS_REVIEW.md` | Multi-skill code review |
| `docs/PHASE_A_PREPROD_AUDIT_*.md` | Pre-production audit report |
| `docs/PHASE_B_SECURITY_REVIEW_*.md` | Security review report |
| `docs/TLS_WITH_CADDY.md` | TLS/Caddy configuration |
| `docs/SERVER_HARDENING.md` | Host/deployment hardening checklist (systemd sandbox, network, Postgres, SSH, secrets, backups) |
| `docs/I18N.md` | Internationalization notes |
| `docs/THIRD_PARTY_LICENSES.md` | Third-party license attributions |

## Available skills

| Skill | Location | Triggers |
|-------|----------|----------|
| accessibility | `.agents/skills/accessibility/` | a11y, WCAG, screen reader, keyboard nav |
| bash-defensive-patterns | `.agents/skills/bash-defensive-patterns/` | shell scripts, CI/CD, production scripts |
| django-expert | `.agents/skills/django-expert/` | Django models, views, ORM, migrations, DRF |
| django-patterns | `.agents/skills/django-patterns/` | Django architecture, REST API, ORM, caching |
| django-security | `.agents/skills/django-security/` | Auth, CSRF, XSS, SQL injection, secure deploy |
| frontend-design | `.agents/skills/frontend-design/` | Visual design, typography, palette, layout |
| find-skills | `.agents/skills/find-skills/` | Discovering new skills |
| python-executor | `.agents/skills/python-executor/` | Sandboxed Python execution |
| python-testing-patterns | `.agents/skills/python-testing-patterns/` | pytest, fixtures, mocking, TDD |
| seo | `.agents/skills/seo/` | Meta tags, structured data, sitemaps |
| sqlalchemy-alembic-expert | `.agents/skills/sqlalchemy-alembic-expert-best-practices-code-review/` | SQLAlchemy ORM, Alembic migrations |
| sqlalchemy-orm | `.agents/skills/sqlalchemy/` | SQLAlchemy toolkit and ORM |
| customize-opencode | `<built-in>` | opencode.json, agents, subagents, MCP |

## What not to port into new apps

- Metro-specific capture logic, incidents, snapshots, data sources, text, or branding
- FastAPI runtime layer (template is Django-only)
- (SQLAlchemy/Alembic is already gone — replaced by Django's
  `connection.cursor()` in `ameli_app/database.py`; not a dependency. The
  DSN parser still tolerates `postgresql+psycopg://`-style schemes on
  purpose.)

## Out-of-scope (not yet addressed)

- `BUILDING_NEW_APP.md` onboarding document (Phase D)
- `sqlalchemy-alembic-expert-best-practices-code-review` is a skill name
- Threat model gap analysis (Phase B item #2)
- Structural code review for `services.py` (Phase C)
- Backup destructive restore wire test
- MFA TOTP e2e path
