# AMELI App Template: canonical handoff

## Purpose

This repository is the Django-first standard template for AMELI applications
that will be exposed to real users on the internet or on internal operational
networks.

## Official architecture

- `src/ameli_app/`
  - config
  - database helpers
  - CLI
  - workers
  - version helpers
- `src/ameli_web/`
  - Django settings, urls and ASGI
  - auth, sessions, profile, admin and audit
  - dashboard shell
  - `/docs`, `/redoc`, `/openapi.json`
- `manage.py`
  - Django management entrypoint

## Official runtime

- Official web runtime: Django ASGI via `python -m ameli_app.api`
- Compatibility launcher: `python -m ameli_app.web`
- The old FastAPI runtime is no longer the official web layer.

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

Compatibility aliases currently kept:

- `create-access` -> `create-user`
- `list-accesses` -> `list-users`

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

## Current branch direction

- This template is being rewritten in-place from the old FastAPI base to a
  Django-first base inspired by Metro.
- If there is conflict between old FastAPI docs and current code, current code
  and this file win.
