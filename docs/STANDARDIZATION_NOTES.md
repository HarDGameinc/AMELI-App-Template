# Standardization Notes

This template consolidates patterns observed across AMELI apps:

- Metro Status: modular API, worker separation, tests, CI and multienvironment deploy.
- Notifier: `src/` package layout, CLI-first operation and rich YAML config.
- Omega Receiver: admin dashboard, ingest API, security and functional tests.
- Report Starlink: roles, audit mindset, permissions and robust operations scripts.
- Bandwidth: dev/prod coexistence and deployment validation.

## Defaults chosen

- New apps use `src/<package>` rather than a root `app/` folder.
- PostgreSQL is the default persistence layer.
- Alembic is the migration mechanism.
- `.env` stores secrets/runtime values.
- YAML stores domain defaults, catalogs and feature toggles.
- API/admin routes are token-ready from the first commit.

