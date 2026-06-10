# Operations

## Local validation

```bash
python -m venv .venv
. .venv/bin/activate
pip install -r requirements.txt -r requirements-dev.txt
pip install -e .
pytest
ruff check .
ruff format --check .
python manage.py migrate --noinput
python manage.py check
```

The preferred local path is to set `DATABASE_URL` to PostgreSQL. If no local
database is available yet, SQLite can be used temporarily through
`AMELI_APP_SQLITE_PATH`.

## Linux install

```bash
sudo APP_ENV=dev APP_SLUG=ameli-new-app APP_PACKAGE=ameli_new_app bash scripts/install.sh
```

The installer preserves `/etc/<instance>/app.env` and `/etc/<instance>/app.yaml`
if they already exist, creates the virtualenv, installs dependencies, runs
`manage.py migrate`, runs `manage.py check` and optionally bootstraps the first
superadmin. A real server install is expected to have `DATABASE_URL` pointing
to PostgreSQL.

## Health checks

```bash
ameli-app config-check --config config/app.yaml.example
ameli-app db-status --config config/app.yaml.example
curl http://127.0.0.1:18080/health
curl http://127.0.0.1:18080/api/health
```

## First install reference

Use the full first-install walkthrough in:

- `docs/FIRST_INSTALL_DJANGO.md`

## Backup

```bash
sudo APP_ENV=prod bash scripts/backup.sh
```

## Audit chain verification (H6)

Enable the HMAC chain by setting `AMELI_APP_AUDIT_HMAC_KEY` in the env
file. From then on every `record_audit` call writes a per-row hmac
plus the previous row's hmac; `ameli-app verify-audit` walks the chain
and reports the first divergence.

Run it manually:

```bash
.venv/bin/ameli-app verify-audit
```

Exit code 0 = clean, exit code 1 = tampering detected. Use range flags
to spot-check a window:

```bash
.venv/bin/ameli-app verify-audit --from-id 1000 --to-id 2000
```

### Schedule it (systemd timer)

The repo ships templates for a per-hour run:

- `deploy/systemd/ameli-app-verify-audit.service`
- `deploy/systemd/ameli-app-verify-audit.timer`

`scripts/install.sh` renders them like the other timers. Wire an alert
hook so a broken chain produces an operator notification:

```ini
# /etc/systemd/system/ameli-app-template-prod-verify-audit.service.d/alert.conf
[Service]
OnFailure=alert-on-audit-tamper.service
```

Where `alert-on-audit-tamper.service` is whatever you already use for
critical alerts (Slack webhook, email, PagerDuty, etc.).

### Rotating the HMAC key

Don't, if possible. Rotating breaks every historical row's
verification (they were stamped with the old key). If you must:

1. Export the audit table to cold storage.
2. Clear the existing `hmac` and `prev_hmac` columns on the live rows
   (they become legacy entries the verifier skips):
   ```bash
   .venv/bin/ameli-app shell -c "
   from ameli_web.audit.models import AuditEvent
   AuditEvent.objects.update(hmac='', prev_hmac='')
   "
   ```
3. Replace `AMELI_APP_AUDIT_HMAC_KEY` and restart the service.
4. New rows pick up the new chain from there.
