# Architecture

This template separates operational AMELI apps into predictable layers:

- `config`: YAML/env loading and runtime settings.
- `api`: HTTP interface, health checks and dashboard routes.
- `database`: SQLAlchemy engine creation and Alembic metadata.
- `workers`: scheduled capture and maintenance jobs.
- `security`: token verification shared by API and admin routes.
- `scripts`: Linux deployment lifecycle.
- `deploy/systemd`: rendered units for production and development instances.

## Data flow

```text
External source
  -> worker/capture
  -> PostgreSQL
  -> API
  -> dashboard/admin
  -> maintenance/backup
```

## Environment model

`APP_ENV=prod|dev` changes instance names and default ports. Secrets live in
env files. Domain catalog/rules live in YAML or CSV under `config/`.

