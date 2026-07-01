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

## Install / Update

- **Install:** `scripts/install.sh` — venv, deps, migrate, check, optional superadmin bootstrap, systemd units
- **Update:** `scripts/update.sh` — pull code, reinstall deps, re-run migrations/checks
- **Validate:** `scripts/validate_installation.sh` — CLI + Django health + PostgreSQL check
- **Lockfile:** `requirements.lock` with `--require-hashes` (ASVS V14.2.3)
- **Systemd:** 16 unit files in `deploy/systemd/`, configurable via `APP_SYSTEMD_PROFILE`

## Testing

- **Framework:** pytest + pytest-django
- **Coverage:** ≥85% (enforced in `pyproject.toml`)
- **Static analysis:** ruff (enforces S security band), mypy (0 errors in 51 source files)
- **E2E:** Playwright (`tests/e2e/`, opt-in via `--run-e2e`)
- **Test count:** 91 unit files + 4 e2e files (as of 2026-06-24)

### Test categories
- Account guards, login, MFA (TOTP, email, stacked, recovery UX, secret encryption)
- Admin CRUD (users, audit, sessions), pagination, partial swap guards
- Security hardening (blocks 1-4, phase B, cookie thief, CSRF, session timeout)
- Email (retry, double-opt-in change, password reset, auth failures alert)
- Avatar (validation, AV scan, upload UI)
- CLI, health, metrics, telemetry
- Installation scripts, backups, Docker stack, systemd units

## State of the project (v0.4.0-django, 2026-06-30)

### Known architectural debt (prioritized)
1. **`accounts/services/` (PC-1 CLOSED, 2026-07-01)** — 14 domain modules; `__init__.py` is a pure re-export surface (~200 lines)
2. **`accounts/views/` (PC-2 CLOSED, 2026-07-01)** — 9 domain modules; `__init__.py` re-exports
3. **`admin_views/` (PC-3 CLOSED, 2026-07-01)** — 10 domain modules; `__init__.py` re-exports
4. **`settings/` (PC-4 CLOSED, 2026-07-01)** — 10 domain modules; `__init__.py` orquesta imports en orden crítico
5. **Inline JS in templates** — `admin/panel.html` (~650 lines), `profile.html` (~470 lines)

### Frontend design gaps
- No signature visual element (generic admin panel look)
- System-default typography (no typeface pairing)
- Palette is the AI-generic blue-on-white default
- No visual hierarchy beyond identical grey panels
- Inline styles in templates instead of utility classes

### Testing gaps
- No JavaScript unit tests (password generator, strength evaluator, debounce)
- No accessibility tests (axe-core, pa11y)
- No migration tests (alembic upgrade/downgrade)
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
| `docs/ARCHITECTURE.md` | Technical structure |
| `docs/FIRST_INSTALL_DJANGO.md` | First install guide |
| `docs/OPERATIONS.md` | Operational procedures |
| `docs/SECURITY.md` | Security posture |
| `docs/THREAT_MODEL.md` | STRIDE threat model |
| `docs/COMPLIANCE_ASVS_L2_*.md` | ASVS L2 compliance snapshots |
| `docs/HANDOFF_TEMPLATE.md` | Session handoff structure |
| `docs/FRONTEND_DESIGN_REVIEW.md` | Frontend design audit |
| `docs/SKILLS_REVIEW.md` | Multi-skill code review |
| `docs/PHASE_A_PREPROD_AUDIT_*.md` | Pre-production audit report |
| `docs/PHASE_B_SECURITY_REVIEW_*.md` | Security review report |
| `docs/TLS_WITH_CADDY.md` | TLS/Caddy configuration |
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
- SQLAlchemy/Alembic setup if unused (currently configured but no active models)

## Out-of-scope (not yet addressed)

- `BUILDING_NEW_APP.md` onboarding document (Phase D)
- `sqlalchemy-alembic-expert-best-practices-code-review` is a skill name
- Threat model gap analysis (Phase B item #2)
- Structural code review for `services.py` (Phase C)
- Backup destructive restore wire test
- MFA TOTP e2e path
