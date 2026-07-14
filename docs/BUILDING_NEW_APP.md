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
- CI workflow: ruff + bandit + mypy + pytest (matrix 3.11-3.14)
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

## 2. Naming

> ### ⚠️ Renaming the Python packages is OPTIONAL and cosmetic — do NOT start here
>
> This section used to say a fork **must** rename the `ameli_app` /
> `ameli_web` packages. A **dry run on 2026-07-14 — the first time the
> procedure was actually executed — disproved that**:
>
> - A child that **keeps the package names** (only `[project].name` in
>   `pyproject.toml` changed) passes the **full suite (1118), `ruff`, and
>   `manage.py check` (0 issues) out of the box**. Nothing functional depends
>   on the package name — the deployed identity is env-driven (`APP_SLUG`,
>   `APP_PACKAGE`, `APP_NAME`; see the deploy table below).
> - Following the old 5-row "rename" table left **~740 references across ~250
>   files** untouched (every `from ameli_web…`, the tests, and
>   `DJANGO_SETTINGS_MODULE`), so the app **would not even start**. It was
>   never a 5-item manual edit.
> - The old verification tip (`pytest` after rename) **gives a false pass**
>   when the template is `pip install -e`'d in your venv: imports resolve to
>   the template's `src/`, not your fork's. It hid the breakage entirely.
>
> **Recommended default: keep the package names.** The only naming you need is
> the env-driven deploy identity below — no source edits.

**If you still want to rebrand the packages** (purely cosmetic — operator-facing
`ameli_*` in stack traces), treat it as a scripted refactor, not a manual edit:
`grep -rl 'ameli_app\|ameli_web' src tests scripts pyproject.toml manage.py`
then `git mv` the two package dirs and `sed` every reference (packages, all
`from …` imports, `DJANGO_SETTINGS_MODULE`, `[tool.setuptools.package-data]`,
the mypy/django-stubs settings-module keys, and the tests). Verify in a **clean
venv** (`pip install -e .` of the FORK, template uninstalled) or the `pytest`
pass is meaningless.

### Deploy / config rename (env-var driven, NO source change)

| Variable | Default | Override at install time |
|---|---|---|
| `APP_NAME` | `AMELI App Template` | `APP_NAME="Your App" bash scripts/install.sh` |
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

## 6. Keeping up with the template (upstream updates)

Your app is born by copying this template and then diverges (your
renames, models, views). Meanwhile the Core (`accounts/`, `audit/`,
`settings/`, middleware, CLI, deploy) keeps improving upstream —
especially **security fixes** (e.g. the Django 5.2.16 CVE patch in
v0.5.2). Pull those in with a git **upstream remote**. See
[`DECISIONS.md`](DECISIONS.md) #7 for *why* this model (git upstream)
rather than a Copier template or an `ameli-core` package.

### One-time: add the template as a remote

```bash
git remote add template https://github.com/HarDGameinc/AMELI-App-Template.git
git fetch template --tags
```

Record which template release your app was born from (or last synced to)
so "how far behind am I" is answerable — e.g. a line in your app's
`README.md` / handoff: `Template lineage: v0.5.2-django`.

### Consultar — is there a newer template version?

The template publishes a **GitHub Release + tag per promotion**
(`vX.Y.Z-django`); security fixes are called out in the notes. The CLI
does the compare for you:

```bash
ameli-app template-check          # JSON: current lineage vs latest release + status
```

It compares your **template lineage** (env `AMELI_APP_TEMPLATE_LINEAGE`,
else a root `TEMPLATE_LINEAGE` file, else the app's `VERSION`) against the
latest release, and exits **1 when behind** (cron-friendly). Point it at a
fork with `--repo owner/name` (or `AMELI_APP_TEMPLATE_REPO`). The template
repo is **private**, so set `GITHUB_TOKEN` (a read-only token) — otherwise
the API returns 404. Manual alternatives:

```bash
gh release view --repo HarDGameinc/AMELI-App-Template   # latest release + notes
git fetch template --tags && git tag -l 'v*-django' | tail -5
```

(Or watch the repo → Releases, or subscribe to its `releases.atom` feed.)

### Enviar — pull the update in

- **A security fix / single change (recommended — surgical):** cherry-pick
  the specific commit; minimal conflict surface.
  ```bash
  git fetch template
  git log --oneline template/main | head        # find the fix commit
  git cherry-pick <sha>
  ```
- **A broad catch-up:** merge the template branch, resolving conflicts
  where your app diverged from the Core.
  ```bash
  git merge template/main        # conflicts land in files you customized
  ```
  Conflicts concentrate in what you renamed/extended (§2, §3); the Core
  you did **not** touch (§4) usually merges clean — which is exactly why
  §4 matters for keeping this channel cheap.

After either path, run the full suite (`APP_ENV=dev pytest` + `ruff`) and
update your lineage note.

### When the fleet grows

Manual cherry-pick/merge gets heavy across many apps. The stronger
channel — extracting the shared Core into a versioned `ameli-core`
package so fixes ship via `pip install -U` + Dependabot auto-PRs — is
**deferred by decision** (`DECISIONS.md` #7). Adopt it when the
maintenance cost justifies the refactor.

---

## 7. Where to read next

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

## 8. Open questions for your fork

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
