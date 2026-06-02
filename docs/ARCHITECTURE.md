# Architecture

`AMELI_APP_TEMPLATE` is the standard Django-first foundation for AMELI apps.
It is intentionally domain-neutral and focuses on authentication, user
management, admin, API docs and operational deployment.

## Layers

- `src/ameli_app/`
  - runtime configuration
  - database helpers
  - CLI commands
  - workers and maintenance wrappers
  - shared version and password policy helpers
- `src/ameli_web/`
  - Django settings
  - ASGI application
  - routes and views
  - accounts, sessions and audit models
  - dashboard, profile and admin web shell
- `scripts/`
  - install, update, backup and validation lifecycle
- `deploy/systemd/`
  - systemd templates rendered per environment/profile
- `config/`
  - YAML defaults intended to be copied into real apps

## Runtime model

- Official web runtime: `python -m ameli_app.api`
- Official framework: `Django ASGI + Uvicorn`
- Official database target: `PostgreSQL`
- Local fallback only: `SQLite`

## Request surface

- Public dashboard: `/`
- Account access: `/login`, `/logout`, `/profile`
- Admin shell: `/admin`
- Health: `/health`, `/api/health`
- API documentation: `/docs`, `/redoc`, `/openapi.json`

## Security baseline

- managed users with roles `superadmin` and `public`
- persisted sessions
- persisted audit trail
- forced password change supported on first login
- password policy shared by UI, generators and backend validation

## Deployment model

`APP_ENV=prod|dev` selects instance names, filesystem paths and service names.
`APP_SYSTEMD_PROFILE` decides which services and timers are enabled for an
instance. Secrets belong in env files; defaults belong in YAML.

Production, staging and QA should be designed around PostgreSQL. SQLite is kept
only to make local bootstrap easier when a developer does not have a database
ready yet.
