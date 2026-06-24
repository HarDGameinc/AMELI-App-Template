# AMELI App Template: canonical handoff

## Reading order for any new session

1. This file (`AGENTS.md`) — purpose, architecture, policies.
2. [`docs/HANDOFF_TEMPLATE.md`](docs/HANDOFF_TEMPLATE.md) — the
   canonical structure every session handoff follows + the skills
   playbook (S-01 to S-08) for reusable plays.
3. The most recent `docs/CLAUDE_HANDOFF_YYYY-MM-DD_*.md` — the
   session-specific context the next session continues from.
4. [`docs/SECURITY.md`](docs/SECURITY.md) +
   [`docs/THREAT_MODEL.md`](docs/THREAT_MODEL.md) — security
   posture and STRIDE-style trust boundaries.
5. [`docs/COMPLIANCE_ASVS_L2_2026-06-16.md`](docs/COMPLIANCE_ASVS_L2_2026-06-16.md)
   — current ASVS L2 mapping (151 PASS, 0 strict GAP, supersedes
   the [`2026-06-15`](docs/COMPLIANCE_ASVS_L2_2026-06-15.md)
   snapshot which the early handoffs reference).

When the new session is by an LLM agent, also read `CLAUDE.md` for
the per-project instruction overrides.

## Purpose

This repository is the canonical Django-first template for AMELI applications
that will be exposed to real users on the internet or on internal operational
networks.

## Database policy

- Official database standard: `PostgreSQL`
- Local convenience fallback only: `SQLite`
- Any real deployment, staging or QA environment should be planned around
  `DATABASE_URL` and PostgreSQL from the beginning.

## Official architecture

- `src/ameli_app/`
  - config
  - database helpers
  - CLI
  - workers
  - version helpers
  - static assets reusable across new apps
- `src/ameli_web/`
  - Django settings, urls and ASGI
  - auth, sessions, profile, admin and audit
  - dashboard shell
  - `/docs`, `/redoc`, `/openapi.json`
- `manage.py`
  - Django management entrypoint

## Official runtime

- Official web runtime: Django ASGI via `python -m ameli_app.api`
- Alternate launcher: `python -m ameli_app.web`
- The template no longer depends on a FastAPI runtime layer.

## Minimum public routes

- `/`
- `/login`
- `/logout`
- `/profile`
- `/admin`
- `/health`
- `/api/health`
- `/docs`
- `/redoc`
- `/openapi.json`

## User model and security baseline

- Roles:
  - `superadmin`
  - `public`
- Sessions are persisted in DB.
- Audit events are stored in DB.
- Password policy:
  - minimum 12 characters
  - at least 1 uppercase
  - at least 1 lowercase
  - at least 1 number
  - at least 1 allowed symbol from `! @ # $ % ^ & * ( ) - _ = + ?`
- Superadmin bootstrap supports forced password change at first login.

## CLI baseline

- `ameli-app version`
- `ameli-app config-check`
- `ameli-app db-status`
- `ameli-app bootstrap-admin`
- `ameli-app create-user`
- `ameli-app list-users`
- `ameli-app worker-once`
- `ameli-app notify-once`
- `ameli-app maintenance`

## Install/update expectations

- `scripts/install.sh`
  - creates venv
  - installs deps
  - runs `manage.py migrate`
  - runs `manage.py check`
  - optionally bootstraps superadmin
- `scripts/update.sh`
  - refreshes code
  - reinstalls deps
  - reruns migrations/checks
- `scripts/validate_installation.sh`
  - validates CLI and Django health basics
  - assumes a real install should have PostgreSQL configured

## Source-of-truth files to keep aligned

- `VERSION`
- `pyproject.toml`
- `README.md`
- `AGENTS.md`

## What not to port into this template

- Metro-specific capture logic
- Metro-specific incidents or snapshots
- Metro-specific data sources
- Metro-specific text or branding

## Documentation baseline

- Main onboarding: `README.md`
- Canonical runtime and continuity reference: `AGENTS.md`
- First install guide: `docs/FIRST_INSTALL_DJANGO.md`
- Technical structure: `docs/ARCHITECTURE.md`
- Operations: `docs/OPERATIONS.md`
