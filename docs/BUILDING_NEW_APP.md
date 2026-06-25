# Building a new app on the AMELI App Template

Onboarding guide for engineers forking the AMELI App Template to
build a new application. The template ships an auth/MFA/audit/admin
backbone + deployment scaffolding; your job is to **add the domain
logic** without re-doing the security and ops layers.

If you only want to install the template as-is, read
[`FIRST_INSTALL_DJANGO.md`](FIRST_INSTALL_DJANGO.md) instead.
This document assumes you are creating a NEW app that inherits
from this template.

---

## 1. What you inherit

The template gives you, out of the box, the items listed below.
**These are battle-tested and pinned by regression tests** —
treat them as a black box you can configure but should not
re-implement.

### Authentication and account management
- `User` model with role (`public` / `superadmin`) + display name
  + theme preference + avatar.
- Login with sliding-window throttle per IP + per user; permanent
  lockout after N consecutive lockout windows.
- Password policy (12+ chars, 4 categories) with Argon2id hashing
  (configurable work factors).
- Password reset (token-based, single-use, single-window).
- MFA stacked methods: TOTP + email, both can be enrolled
  simultaneously. Recovery codes one-time.
- Cookie-thief hardening: `current_password` required before any
  MFA enrolment / recovery code regeneration (see
  `tests/test_cookie_thief_hardening.py`).
- Session management: DB-persisted, revocable, absolute ceiling
  timeout.
- Email change with double-opt-in (alert email to old address +
  POST-confirmation interstitial on the new address).
- `must_change_password` flag forces a standalone password-change
  page that hides all other profile data until rotation.

### Audit and compliance
- `AuditEvent` model with HMAC SHA-256 forward chain. CLI helpers:
  `ameli-app verify-audit-chain`, `ameli-app rotate-audit-key`.
- ASVS L2 baseline: 151 PASS, 0 strict GAP (see
  [`COMPLIANCE_ASVS_L2_2026-06-16.md`](COMPLIANCE_ASVS_L2_2026-06-16.md)).
- Threat model at [`THREAT_MODEL.md`](THREAT_MODEL.md) covers
  STRIDE per trust boundary + 17 attack scenarios.

### Admin panel
- `/admin/` custom panel: user CRUD, audit log search, sessions
  table, maintenance toggle, email queue widget.
- Sudo gate: every privileged admin action requires a fresh
  re-auth grant with MFA support.
- Native Django admin at `/django-admin/` is gated by sudo +
  `is_staff` predicate (so a DB-bypass-modified User row still
  hits the gate).

### Operations
- 16 systemd units in `deploy/systemd/`: api, web, worker,
  capture (instanced via `@`), maintenance, notifier,
  backup, verify-audit. All parameterized through env vars.
- Backup script with optional GPG encryption + MANIFEST.sha256
  for integrity. Restore script with `verify` and destructive
  modes.
- Pre-push git hook blocks direct push to `main` / `master`.
- CI workflow: ruff + bandit + mypy + pytest (matrix 3.11+3.12)
  + supply-chain audit (pip-audit on hash-verified lockfile) +
  Playwright e2e.

### Frontend baseline
- Single `app.css` (~820 lines) + `app.js` (~480 lines) with
  CSS custom properties for three-mode theming (light / dark /
  auto). No framework dependency.
- WCAG-baseline accessibility (skip-link, `:focus-visible`,
  `prefers-reduced-motion`, ARIA semantic roles).
- CSP per-request nonces + Trusted Types policy
  (`ameli-template`) + SRI on own static assets.
- Spanish UI with active-voice copy; English code/comments.

---

## 2. What to rename

The template uses two Python packages and a slug. A real fork
must change all three.

### Source rename (one-time, manual)

| From | To | Where |
|---|---|---|
| `src/ameli_app/` | `src/your_app/` (snake_case) | Python source root for runtime + CLI + workers |
| `src/ameli_web/` | `src/your_web/` (snake_case) | Django project package: settings, urls, accounts, audit, dashboard |
| `ameli_app.cli:main` | `your_app.cli:main` | `pyproject.toml` `[project.scripts]` |
| `ameli-app-template` | `your-app-name` | `pyproject.toml` `[project].name` |
| `ameli-app` | `your-app` | `[project.scripts]` entry-point key (the CLI command) |

After rename, the CLI command becomes `your-app version` /
`your-app config-check` / etc.

> **TIP**: do the renames in one commit so the diff is reviewable
> as a unit. After rename, run `pytest tests/ --ignore=tests/e2e`
> to confirm no missed import paths.

### Deploy / config rename (env-var driven, NO source change)

| Variable | Default | Override at install time |
|---|---|---|
| `APP_NAME` | `AMELI App Template` | `sudo APP_NAME="Your App" bash scripts/install.sh` |
| `APP_SLUG` | auto-detected from directory name | `APP_SLUG=your-app-prod` |
| `APP_PACKAGE` | `ameli_app` | `APP_PACKAGE=your_app` (match source rename) |
| `APP_ENV` | `dev` | `APP_ENV=prod` |

`scripts/install.sh` templates the systemd unit files
(`__APP_NAME__`, `__APP_SLUG__`, `__APP_PACKAGE__`, etc.) at
install time, so you do NOT need to edit `deploy/systemd/*` by
hand.

### Config rename (`config/app.yaml`)

When you copy `config/app.yaml.example` to your real
`/etc/<slug>/app.yaml`, update:

```yaml
app:
  name: "Your App"
  slug: "your-app"
  # ...
```

The `slug` here MUST match the `APP_SLUG` env var used at install
time so logs / metrics / units all carry the same name.

### Env var prefix (`AMELI_APP_*`)

The template's env vars all start with `AMELI_APP_` (e.g.
`AMELI_APP_DJANGO_SECRET_KEY`, `AMELI_APP_AUDIT_HMAC_KEY`,
`AMELI_APP_SQLITE_PATH`). The prefix is **hardcoded** in
`settings.py` and the CLI. For a child app you have two options:

- **Keep the prefix**: simpler, works out of the box, but logs
  will mention `AMELI_APP_*` in error messages even for your app.
- **Rebrand to `YOUR_APP_*`**: grep + sed across `src/` and
  `scripts/`. Estimated cost ~1h including test fixups.

The first option is the recommended starting point; rebrand later
if the operator-facing naming bothers you.

---

## 3. What to extend

### Capture worker (`src/ameli_app/workers/capture.py`)

Intentional placeholder. Replace `run_once(settings)` with your
ingestion logic (poll an API, drain a queue, snapshot a data
source). The systemd timer `your-app-capture-primary.timer`
calls this on schedule. Off by default; enable per environment
in the systemd profile.

### Custom Django models

Add a new Django app (e.g. `your_web/domain/`) for your
domain models. Inherit from the existing patterns:

- Use `User` as the FK target for user-owned data
  (`from your_web.accounts.models import User`).
- Use `record_audit(...)` from `your_web.accounts.services` to
  record domain-significant actions in the audit chain.
- Use `ThrottleCounter` from
  `your_web.accounts.services._bump_throttle_counter` for any
  new rate-limited surface (do NOT roll your own).
- Use `transaction.atomic` + `select_for_update()` for any
  mutation that races (the throttle counter is a good template).

### Custom views

Add a new Django app for view code. Keep the project's view
patterns:

- Decorate auth-required views with `@login_required`.
- Decorate write-mode admin views with `@superadmin_required +
  @sudo_required`.
- POST-only mutating endpoints use `@require_POST` (NEVER GET-driven
  state change — see `email_change_confirm_view` for the
  interstitial pattern).
- JSON endpoints use the `_json_body` / `_json_error` helpers
  from `your_web.accounts.views` (or extract them to a shared
  module if you have many).
- Any endpoint that exposes the password or session cookie
  needs `Cache-Control: no-store` — the
  `SecurityHeadersMiddleware` already stamps this on
  authenticated responses.

### Custom templates

Inherit from `base.html` for any new page:

```html
{% extends "base.html" %}
{% block title %}Your Page — {{ block.super }}{% endblock %}
{% block content %}
  <section class="panel">
    <!-- your content -->
  </section>
{% endblock %}
```

You inherit: header / footer / skip-link / CSP nonce / Trusted
Types policy / robots meta / theme toggle / current-user widget /
maintenance banner.

### Custom settings

Override Django settings via env vars (preferred) or by editing
`your_web/settings.py`. Keep the boot guards (`AUDIT_HMAC_KEY`,
`MFA_ENCRYPTION_KEY`) — they raise `RuntimeError` outside dev if
the keys are missing, preventing a misconfigured deploy from
serving traffic.

If you split `settings.py` into a package (`settings/base.py`,
`settings/prod.py`, etc.), keep the boot-guard contract: a
`RuntimeError` at import time outside dev when a critical key is
missing.

---

## 4. What you MUST NOT touch

The following invariants are pinned by regression tests. Breaking
them means breaking the security model.

| Invariant | Pinned by |
|---|---|
| Cookie thief cannot enroll MFA on a stolen session | `tests/test_cookie_thief_hardening.py` |
| Cookie thief cannot regenerate recovery codes | `tests/test_cookie_thief_hardening.py` |
| Cookie thief cannot bypass `current_password` re-auth on MFA enrolment | `tests/test_cookie_thief_hardening.py` |
| `verify_mfa_view` POST is throttled | `tests/test_cookie_thief_hardening.py` |
| `must_change_password` user is bounced from `/profile/` to standalone form | `tests/test_cookie_thief_hardening.py` |
| Sudo brute-force is gated | `tests/test_phase_b_hardening.py` |
| Email change token compared in constant time | `tests/test_phase_b_hardening.py` |
| `change_email_for_self` requires `current_password` | `tests/test_phase_b_hardening.py` |
| `update_preferences` JSON branch caps display name length | `tests/test_phase_b_hardening.py` |
| `email_change_confirm_view` is two-step (mail-scanner safe) | `tests/test_phase_b_hardening.py` |
| Maintenance gate fails CLOSED on DB error | `tests/test_phase_b_hardening.py` |
| Django admin gated by `is_staff` + sudo | `tests/test_phase_b_hardening.py` |
| Password generator refuses non-cryptographic randomness | `tests/test_phase_qw_hardening.py` |
| `<meta robots noindex>` ships in every page | `tests/test_phase_qw_hardening.py` |
| Lockfile is hash-verified | `tests/test_lockfile_hashes.py` |
| Audit chain integrity | `tests/test_security_hardening_block*.py` |
| Session absolute ceiling | `tests/test_session_absolute_ceiling.py` |
| Boot guards refuse missing secrets outside dev | `tests/test_settings_boot_guards.py` |

If you have a strong reason to relax one of these, the answer is:
**document the residual risk** in your own `SECURITY.md` rather
than weakening the test. The template's threat model
(`THREAT_MODEL.md`) shows the residual risk pattern (R-01 through
R-12 with explicit acceptance criteria).

---

## 5. First-hour smoke checklist

A successful onboarding looks like this. Each step should take
less than 5 minutes.

```bash
# 1. Clone + rename
git clone https://github.com/HarDGameinc/AMELI-App-Template your-app
cd your-app
# Do the source renames in §2; commit as a single change.

# 2. Install deps + bootstrap secrets
python -m venv .venv && source .venv/bin/activate
pip install --require-hashes -r requirements.lock -r requirements-dev.lock
pip install -e . --no-deps

# 3. Generate the three critical keys (DO NOT REUSE between envs)
python -c "import secrets; print(secrets.token_urlsafe(64))"  # DJANGO_SECRET_KEY
python -c "import secrets; print(secrets.token_urlsafe(64))"  # AUDIT_HMAC_KEY
python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"  # MFA_ENCRYPTION_KEY

# 4. Set the keys (and DB URL) in your .env
export AMELI_APP_DJANGO_SECRET_KEY=<from step 3>
export AMELI_APP_AUDIT_HMAC_KEY=<from step 3>
export AMELI_APP_MFA_ENCRYPTION_KEY=<from step 3>
export DATABASE_URL=postgresql://user:pass@localhost:5432/your_app
# OR for SQLite local dev:
export AMELI_APP_SQLITE_PATH=/tmp/your-app.sqlite3

# 5. Migrate + bootstrap superadmin
cd src
python -m django migrate --noinput
python -m django check
cd ..
your-app bootstrap-admin --username admin --password 'TempPass!12?'

# 6. Run the app
python -m your_app.api  # uvicorn on settings.api.port

# 7. Smoke test in a browser
# - GET / → dashboard renders
# - GET /login → form renders
# - POST /login with admin creds → bounces to /profile/password/
#   (must_change_password=True from bootstrap)
# - Change the password → lands on /profile/
# - Open /admin/ → user list renders
# - Open /docs → Swagger UI renders

# 8. Run the suite
pytest tests/ --ignore=tests/e2e   # should be the template's 1033 + your additions
```

If this checklist passes within an hour, the template is doing its
job. If a step fails, file an issue against the template before
you continue — the failure is likely a template bug, not your fork.

---

## 6. Where to read next

| Doc | When to read |
|---|---|
| [`SECURITY.md`](SECURITY.md) | Before deploying outside dev — covers ASVS posture + residual risk register + crypto key custody policy. |
| [`THREAT_MODEL.md`](THREAT_MODEL.md) | Before adding any new auth path, external integration, or persistence layer — §6 lists the cadence triggers. |
| [`OPERATIONS.md`](OPERATIONS.md) | Before installing on a server — covers systemd profiles, backup / restore, maintenance toggle, DB pool tuning. |
| [`FIRST_INSTALL_DJANGO.md`](FIRST_INSTALL_DJANGO.md) | Step-by-step installation in Spanish, both local + Debian server. |
| [`COMPLIANCE_ASVS_L2_2026-06-16.md`](COMPLIANCE_ASVS_L2_2026-06-16.md) | Mapping each ASVS L2 control to a file:line in the codebase. |
| [`HANDOFF_TEMPLATE.md`](HANDOFF_TEMPLATE.md) | Before opening a session-handoff doc for an LLM agent or a human teammate. |
| [`SKILLS_REVIEW.md`](SKILLS_REVIEW.md) | Latest cross-cutting findings (architecture, security, testing, accessibility) — your fork inherits this debt. |
| [`FRONTEND_DESIGN_REVIEW.md`](FRONTEND_DESIGN_REVIEW.md) | Before customizing the visual identity (typography, palette, signature element). |

---

## 7. Open questions for your fork

These are decisions the template explicitly defers to the child
app. Document the answer in your own handoff doc when you make
each call.

1. **Visual identity** — keep the template's neutral grey panels
   or commit to a brand palette + display face (see
   `FRONTEND_DESIGN_REVIEW.md` §9 for a concrete proposal).
2. **Database engine** — Postgres is the official path; SQLite is
   a documented fallback for local dev / demos. CI runs SQLite
   today (see handoff 2026-06-25 §4 Decision 1).
3. **Capture worker** — implement, disable, or remove entirely
   depending on whether your app ingests external data.
4. **Native Django admin** — keep gated behind sudo (default) or
   disable entirely (`INSTALLED_APPS` removes `django.contrib.admin`).
5. **Telemetry** — opt-in to OpenTelemetry by setting
   `AMELI_APP_OTEL_EXPORTER_OTLP_ENDPOINT`; otherwise the OTel
   packages are loaded but dormant.
6. **Public API** — the template ships `/docs` + `/redoc` +
   `/openapi.json` as scaffolding. If your app has a real API,
   wire it into the OpenAPI schema by editing
   `dashboard/views.py:_openapi_schema()`.
