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

Use case: the key was leaked, or your security policy mandates periodic
rotation. The chain stays verifiable after rotation — the helper
re-stamps every chained row with the new key while preserving the
prev_hmac sequence.

1. **Verify the chain is clean first.** Rotation refuses to run when
   the source chain is broken (it would paper over tampering).
   ```bash
   .venv/bin/ameli-app verify-audit
   ```
   Must print `{"ok": true, ...}`.

2. **Generate the new key.**
   ```bash
   NEW_KEY=$(.venv/bin/python -c "import secrets; print(secrets.token_urlsafe(48))")
   echo $NEW_KEY  # save it; you also need the OLD key for the next step
   ```

3. **Run the rotation.** This re-stamps every chained row in one
   transaction and writes an `audit_key_rotated` row as the new tail
   of the chain. The running service still uses the old in-memory
   key — we only re-stamp the DB rows here.
   ```bash
   .venv/bin/ameli-app rotate-audit-key \
     --from-key "$OLD_KEY" \
     --to-key "$NEW_KEY"
   ```
   On success the response contains `{"ok": true, "rotated": N, ...}`.

4. **Update the env file and restart.** Now the running process
   adopts the new key and starts chaining new rows from the rotation
   row.
   ```bash
   sudo sed -i "s|^AMELI_APP_AUDIT_HMAC_KEY=.*|AMELI_APP_AUDIT_HMAC_KEY=$NEW_KEY|" \
     /etc/ameli-app-template-<env>/app.env
   sudo systemctl restart ameli-app-template-<env>-api.service
   ```

5. **Sanity-check the post-rotation chain.**
   ```bash
   .venv/bin/ameli-app verify-audit
   ```
   Must again print `{"ok": true, ...}` with the new tally including
   the rotation row.

**Caveats**:

- The OLD key cannot verify the chain anymore after step 3. Keep an
  offline copy if you need to retain "history was signed under that
  key" as evidence — anyone with the old key can verify against a
  point-in-time export from before step 3.
- If step 3 fails mid-walk for any reason, the transaction rolls back
  and the chain stays under the old key. You can retry.

If you'd rather wipe and start fresh (e.g. after an irrecoverable
break), use this older recipe instead — it discards verifiability of
the historical rows:

```bash
.venv/bin/ameli-app shell -c "
from ameli_web.audit.models import AuditEvent
AuditEvent.objects.update(hmac='', prev_hmac='')
"
# then update AMELI_APP_AUDIT_HMAC_KEY and restart
```
