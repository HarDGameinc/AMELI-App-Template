# Skills Review — AMELI App Template

**Review date:** 2026-06-25  
**Skills evaluated:** accessibility, bash-defensive-patterns, django-expert, django-patterns, django-security, python-testing-patterns, sqlalchemy-alembic-expert-best-practices-code-review, seo

---

## 1. Accessibility (WCAG 2.2)

### Strengths
- Skip-link (`src/ameli_web/templates/base.html:38`) — first focusable element, visible on focus.
- `:focus-visible` outline ring with `--accent` color (`app.css:16`).
- `prefers-reduced-motion` disables all animations (`app.css:19-24`).
- `aria-*` attributes throughout: `aria-expanded` on menu toggles, `aria-selected` on tabs, `aria-hidden` on icon glyphs, `aria-label` on buttons, `aria-modal` on dialogs, `aria-live="polite"` on flash messages and feedback containers.
- Tab panels use `role="tablist"`, `role="tab"`, proper `aria-selected` toggling.
- Color contrast is adequate in both themes (light: `#17202a` on `#f6f7fb`; dark: `#e7ebf3` on `#0f1420`).
- Breadcrumbs have `aria-label="Breadcrumb"`.
- Error pages show `request_id` for user reference.

### Gaps
| Issue | Location | Severity | WCAG SC |
|-------|----------|----------|---------|
| No `<h1>` on most pages (only `.profile-name` as `<h2>`) | `base.html` uses `<h1>` for header title, but inner pages don't always have a semantic heading structure | Medium | 1.3.1 |
| Login form error is a `<div>` with `.visible` class, no `aria-describedby` linking the error to the input | `login.html:24-28` | Low | 3.3.1 |
| No visible focus indicator for the theme toggle tooltip hover (keyboard users can't reach the tooltip content) | `app.css:122-127` | Low | 1.4.13 |
| Profile's `.password-strength-bar` uses `span` with only background color to indicate strength — no text alternative for the "weak/medium/strong" label | `profile.html:249` | Low | 1.4.1 |
| No ARIA live region on AJAX swap targets (partial panel swaps don't announce new content) | `app.js:245-273` | Medium | 4.1.3 |
| Back-to-top button injected via JS but focus is not managed after click | `app.js:475-477` | Low | 2.4.3 |

### Recommendations
- Ensure every page has a uniquely descriptive `<h1>`.
- Add `role="alert"` or `aria-describedby` to form error containers.
- Add `role="status"` with `aria-live="polite"` on pagination panel containers that receive AJAX swaps.

---

## 2. Bash Defensive Patterns

### Strengths
- All scripts use `set -euo pipefail` (e.g., `scripts/install.sh:2`, `scripts/_common.sh:2`).
- `require_root()` checks EUID before proceeding (`_common.sh:163-167`).
- `load_env_file()` handles whitespace stripping, quoting, comments, and doesn't override already-set vars (`_common.sh:64-87`).
- `bool_is_true()` normalizes multiple truthy representations (`_common.sh:134-139`).
- `fail()` supports explicit exit codes for script-specific error taxonomy (`_common.sh:119-132`).
- `repair_permissions()` sets conservative `644`/`755`/`750` with `|| true` to survive readonly filesystems.
- `render_systemd_units()` uses sed substitution with proper quoting.
- Lockfile install path under `--require-hashes` (ASVS V14.2.3 compliance in `install.sh:281-283`).
- `copy_project_tree()` has fallback from rsync to tar when rsync is unavailable.

### Gaps
| Issue | Location | Severity |
|-------|----------|----------|
| `log()` uses `printf` but no `logger` for syslog integration | `_common.sh:115-117` | Low |
| No `trap` for cleanup on error (e.g., rollback partial install) | all scripts | Medium |
| `repair_permissions()` unconditionally `chown -R root:root "${APP_DIR}"` which changes ownership of .venv before restoring it in the next block — creates a small window where venv is owned by root | `_common.sh:291-301` | Low |
| `copy_if_missing` backtick quoting for `mode` parameter uses `mkdir -p "$(dirname ...)"` which relies on proper variable expansion in edge cases | `_common.sh:187-197` | Low |
| No `set -x` for debug mode (no `DEBUG=1` or `-v` flag support) | all scripts | Low |

### Recommendations
- Add `trap` handlers for rollback in `install.sh` and `update.sh`.
- Consider `logger` integration for production audit trails.

---

## 3. Django Expert / Django Patterns

### Strengths
- **Clean project structure:** `ameli_app` (runtime/cli) separated from `ameli_web` (Django-specific). Clear boundaries.
- **Custom `AbstractUser`** subclass with role field, MFA fields, audit cooldown, and theme preference — all in one model (`models.py:16-113`).
- **MFA stacked-method pattern:** TOTP + email can be simultaneously enrolled, with independent `mfa_totp_enabled`/`mfa_email_enabled` booleans (`models.py:60-61`).
- **Hash-chained audit log:** `AuditEvent` with `prev_hmac`/`hmac` for tamper detection (`audit/models.py:6-17`).
- **Atomic throttle counters:** `ThrottleCounter` with `unique_together` + `SELECT FOR UPDATE` pattern to prevent TOCTOU on rate limits (`models.py:193-220`).
- **Email retry queue:** `OutboundEmail` with exponential backoff, max attempts, TTL, and audit trail (`models.py:223-273`).
- **Single-row singleton:** `MaintenanceMode` uses pk=1 enforcement via service layer (`models.py:276-301`).
- **Password policy validator:** `validators.py` (145 lines) with Django validator integration.
- **AJAX pagination system:** `pagination.py` with partial views, `history.pushState`, cookie-persisted per_page.
- **CSP + Trusted Types + SRI** integrated at the Django middleware/template level — uncommon and well-executed.
- **Sudo prompt pattern:** Re-authentication for sensitive admin actions, with MFA support, retry after grant.

### Architecture Issues
| Issue | Location | Severity |
|-------|----------|----------|
| `services.py` at 3793 lines is a god object — orchestrates user CRUD, MFA, password, email, audit, sessions, notifications | `accounts/services.py` | HIGH |
| `views.py` at 1267 lines with inline JSON handling, form processing, and partial-render logic | `accounts/views.py` | HIGH |
| Mix of class-based views (`TemplateLoginView`) and function-based views (`profile_view`, `admin_panel_view`) with no consistent pattern | `accounts/views.py` | Medium |
| No use of Django REST Framework for API endpoints — raw `JsonResponse` with manual JSON parsing | `accounts/views.py:70-91` | Medium |
| `admin_views.py` at ~1400+ lines with inline HTML generation in Python strings for modals | `admin_views.py` | Medium |
| `settings.py` at 746 lines — consider splitting into `settings/__init__.py`, `settings/base.py`, `settings/prod.py`, etc. | `settings.py` | Low |

### ORM / Query Patterns
- Good use of `select_related`/`prefetch_related` where visible.
- `ThrottleCounter` uses `select_for_update()` correctly for atomic increments.
- `AuditEvent` ordering by `-created_at` with hash chain — efficient read pattern.
- `OutboundEmail` indexed composite `(status, next_retry_at)` for worker queries.

### Recommendations
- Split `services.py` into domain modules: `services/user.py`, `services/mfa.py`, `services/email.py`, `services/audit.py`.
- Adopt DRF or at least `django.http.JsonResponse` helpers with consistent envelope format.
- Split `settings.py` into a settings package.
- Move raw JSON body parsing (`_json_body`) to a reusable middleware or mixin.

---

## 4. Django Security

### Strengths
- **CSP enforced** with per-request nonces for inline scripts (`settings.py`).
- **Trusted Types policy** (`ameli-template`) enforced via CSP header (`base.html:29-33`).
- **SRI hashes** for all own static assets via custom `{% sri_for %}` tag.
- **Honeypot field** in login form (`login.html:20-23`).
- **CSRF tokens** on every state-changing action via `x-csrf-token` header + form field.
- **Password policy:** 12-char minimum, upper/lower/digit/symbol, validated client + server.
- **MFA:** TOTP + email with recovery codes, brute-force throttled login, cookie-thief hardening (password prompt for MFA enrollment/disabling).
- **Audit log** with hash chain for tamper detection.
- **Throttle counters** with `select_for_update()` to prevent TOCTOU on rate limits.
- **Maintenance mode** denies writes from non-staff users.
- **Session management:** DB-persisted sessions, ceiling timeout, forced change on password update, revocation support.
- **Hard lock** (no time-based auto-unlock) after repeated lockout windows (`models.py:47-48`).
- **AV scan on avatar upload** (`accounts/av.py`).
- **Double-opt-in email change** with alert to old address.
- **MFA secret encryption** via Fernet (`mfa.py`).
- **Auth failure alert cooldown** (`last_auth_alert_sent_at` field).
- **ASVS L2 compliance:** 151 PASS / 0 strict GAP (per `COMPLIANCE_ASVS_L2_2026-06-16.md`).

### Gaps
| Issue | Location | Severity |
|-------|----------|----------|
| No rate limiter on password change endpoint (profile password form uses `requestJson` with no client-side backoff) | `profile.html` inline JS | Low |
| No explicit `SECURE_SSL_REDIRECT` in settings (relies on Caddy at proxy level) | `settings.py` | Low (infra) |
| Some inline JS in templates uses `{{ csrf_token }}` as a JS variable — exposed in source if CSP is bypassed | `admin/panel.html:537` | Low |
| Password generator (`app.js:62-81`) uses `crypto.getRandomValues` but falls back to `Math.random` — should require `crypto` | `app.js:54-59` | Medium |

### Recommendations
- Make `crypto.getRandomValues` mandatory in `ameliGeneratePassword` — log a console warning and refuse to generate if unavailable.
- Review all inline `<script>` blocks for hard-coded `{{ csrf_token }}` exposure and migrate to cookie-based token reading where possible.
- Add rate limiting on `/admin/change-password` and `/profile/change-password`.

---

## 5. Python Testing Patterns

### Strengths
- **97 test files** (91 unit + 4 e2e + 2 conftest) — comprehensive coverage.
- **85% coverage floor** enforced via `pyproject.toml`.
- **pytest** with Django plugin, conftest-driven fixtures.
- Test categories:
  - Account guards (`test_account_guards.py`)
  - Admin CRUD (`test_admin_users_export.py`, `test_admin_users_pagination.py`)
  - MFA (totp, email, stacked, recovery UX, secret encryption)
  - Email (retry, double-opt-in change, password reset, auth failures alert)
  - Security hardening (blocks 1-4, phase B, cookie thief, CSRF, session timeout)
  - Pagination (page size persistence, partial guards, clear filters)
  - Avatar (validation, AV scan, upload UI)
  - CLI (`test_cli.py`, `test_cli_shell.py`)
  - Health and metrics endpoints
  - Docker stack verification
  - Script validation (backup, install, restore, systemd)
- **E2E tests** with Playwright (`tests/e2e/`) — login flow, avatar upload, password change.
- **Explicit markers** for e2e (`--run-e2e`), CI-only tests.

### Gaps
| Issue | Location | Severity |
|-------|----------|----------|
| No frontend JS tests (no Jest, Playwright component tests, or Vitest) | entire project | Medium |
| No accessibility tests (axe-core, pa11y, or similar) | entire project | Medium |
| No API contract tests beyond `test_openapi_contract.py` (which checks Swagger output, not runtime behavior) | `tests/test_openapi_contract.py` | Medium |
| Some tests lack `transactional_db` marker where they actually modify DB (already noted in `CLAUDE_HANDOFF_2026-06-24` as fixed for e2e) | various | Low |
| No snapshot or visual regression tests for templates | entire project | Low |
| E2E tests require explicit `--run-e2e` flag — not run in CI by default | `tests/e2e/conftest.py` | Low |

### Recommendations
- Add Jest or Vitest for JS function testing (password generator, strength evaluator, debounce).
- Add Playwright component/accessibility assertions to existing e2e suite (e.g., `toHaveFocus()`, `toHaveAccessibleName()`).
- Add API contract tests using `pytest-django` + JSON schema validation against the OpenAPI spec.

---

## 6. SQLAlchemy / Alembic Expert

### Strengths
- **Alembic environment** configured at `migrations/env.py` with proper `target_metadata` and migration script template.
- **Versioned migrations** under `migrations/versions/`.
- Django ORM for web models (accounts, audit), Alembic for any SQLAlchemy models — dual-ORM setup is documented.
- `alembic.ini` at project root with matching config.

### Gaps
| Issue | Location | Severity |
|-------|----------|----------|
| No SQLAlchemy models visible in the `src/` tree besides what Alembic manages — unclear if the Alembic setup is actively used or legacy | `migrations/versions/` empty | Medium |
| If dual ORMs (Django + SQLAlchemy) are active, no documentation on which models live where | `docs/ARCHITECTURE.md` | Low |
| No database migration tests (no test that runs `alembic upgrade` + `alembic downgrade` in CI) | entire project | Medium |

### Recommendations
- Clarify in `ARCHITECTURE.md` whether SQLAlchemy/Alembic is active or vestigial.
- If active, add a CI test that runs `alembic upgrade head` then `alembic downgrade -1` to verify forward/backward migratability.
- If inactive, remove `alembic.ini`, `migrations/`, and the SQLAlchemy dependency from `pyproject.toml`.

---

## 7. SEO

Limited applicability — this is an internal operational template, not a public-facing website. Notes for completeness:

- **No `<meta name="description">`** in `base.html`. Not critical for internal apps but easy to add.
- **No `robots` meta tag** — internal apps should set `<meta name="robots" content="noindex, nofollow">`.
- **No canonical URL** — not needed for internal tooling.
- **Open Graph / Twitter Card** tags absent but irrelevant for this use case.

### Recommendations
- Add `<meta name="robots" content="noindex, nofollow">` to `base.html` as a security measure for internal deployments.

---

## Summary of Cross-Cutting Findings

| Area | Critical (P0) | High (P1) | Medium (P2) | Low (P3) |
|------|---------------|-----------|-------------|----------|
| **Accessibility** | — | — | AJAX live regions, heading structure | Form error linking, tooltip keyboard access |
| **Bash** | — | No trap/rollback | — | Debug mode, logger, venv ownership window |
| **Django/Patterns** | `services.py` god object (3793 lines) | `views.py` size, no DRF | Inconsistent view patterns, raw JSON handling | settings.py splitting |
| **Security** | — | `Math.random` fallback in password generator | — | CSRF token in inline JS, rate limiting on password change |
| **Testing** | — | — | No JS tests, no a11y tests, no migration tests | E2E not in CI by default |
| **SQLAlchemy** | — | Unclear if Alembic is actively used | No migration tests | Documentation gap |
| **SEO** | — | — | Missing `noindex` meta | Missing meta description |
