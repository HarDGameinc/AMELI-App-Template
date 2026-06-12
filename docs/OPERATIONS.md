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

## Outbound email retry queue (#3)

Flows that can tolerate eventual delivery (password reset emails,
admin-initiated MFA-disabled notifications) use
`services.send_with_retry`. On transient SMTP failure the message
is persisted to `accounts_outboundemail` instead of bubbling the
exception up to the request handler.

The `notify-once` worker drains the queue using an exponential
backoff (1 min → 5 min → 15 min → 1 h → 6 h) and gives up after
5 attempts, recording an `email_failed_permanent` audit row for
the operator to investigate. Rows carrying an `expires_at` (e.g.
a password-reset URL whose token TTL elapsed) are dropped without
an SMTP attempt — better than shipping a dead link.

Schedule it via systemd timer alongside the other workers:

```bash
.venv/bin/ameli-app notify-once
```

Inspect the queue:

```bash
.venv/bin/ameli-app shell -c "
from ameli_web.accounts.models import OutboundEmail
for row in OutboundEmail.objects.exclude(status='sent').order_by('next_retry_at'):
    print(row.pk, row.status, row.attempts, row.next_retry_at.isoformat(), row.subject, row.to_emails)
"
```

Force a retry now (move the next_retry_at backwards):

```bash
.venv/bin/ameli-app shell -c "
from django.utils import timezone
from ameli_web.accounts.models import OutboundEmail
OutboundEmail.objects.filter(status='pending').update(next_retry_at=timezone.now())
"
.venv/bin/ameli-app notify-once
```

Flows that need the user to see a failure immediately (the profile
test-email button, MFA codes during login) keep using
`.send(fail_silently=False)` and surface the exception to the
caller — the queue is opt-in.

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

Run these steps as a single shell session so the `OLD_KEY` /
`NEW_KEY` variables stay defined. The recipe is intentionally
paranoid — an empty/typo'd variable blanking the env file is the
exact failure mode the #6 verification hit on dev.

1. **Verify the chain is clean first.** Rotation refuses to run when
   the source chain is broken (it would paper over tampering). Use
   `--strict-precondition` so a pipeline can tell "chain broken,
   can't rotate" (exit 3) apart from other errors (exit 1).
   ```bash
   .venv/bin/ameli-app verify-audit --strict-precondition
   ```
   Must print `{"ok": true, ...}`.

2. **Capture the current key and generate the new one into env
   vars (not argv).** Passing keys as `--from-key/--to-key` puts
   them in `ps`/`/proc/<pid>/cmdline` and shell history. Read them
   into env vars with `read -s` (silent) and use `--from-key-env`
   / `--to-key-env` instead. The guards below abort if either is
   empty.
   ```bash
   OLD_KEY=$(grep '^AMELI_APP_AUDIT_HMAC_KEY=' /etc/ameli-app-template-<env>/app.env | cut -d= -f2-)
   NEW_KEY=$(.venv/bin/python -c "import secrets; print(secrets.token_urlsafe(48))")
   export OLD_KEY NEW_KEY
   [ -n "$OLD_KEY" ] || { echo "ABORT: OLD_KEY is empty"; return 1 2>/dev/null || exit 1; }
   [ -n "$NEW_KEY" ] || { echo "ABORT: NEW_KEY is empty"; return 1 2>/dev/null || exit 1; }
   [ "$OLD_KEY" != "$NEW_KEY" ] || { echo "ABORT: keys are identical"; return 1 2>/dev/null || exit 1; }
   ```
   If you'd rather not have the new key in your environment at all,
   skip the `export` and use `--to-key-stdin` in step 3.

3. **Run the rotation in one go (recommended).** `--apply-env` makes
   the helper atomically rewrite the env file after the DB is
   re-stamped, so you can't end up with a rotated DB and a stale env
   file (or worse, a blanked env file from a typo'd `sed`). Then
   restart the service.
   ```bash
   sudo -E .venv/bin/ameli-app rotate-audit-key \
     --from-key-env OLD_KEY \
     --to-key-env NEW_KEY \
     --apply-env /etc/ameli-app-template-<env>/app.env || {
       echo "ABORT: rotation failed; env file untouched"
       return 1 2>/dev/null || exit 1
   }
   sudo systemctl restart ameli-app-template-<env>-api.service
   unset OLD_KEY NEW_KEY   # keep them out of the shell after rotation
   ```
   Exit codes: `0` = full success, `2` = rotation refused (chain
   broken / bad args / unresolvable key), `4` = DB rotated but
   env-file write failed (in-memory key still mismatches;
   investigate before restarting).

   On success the JSON response contains a `next_steps` array and
   `rotated: N`.

   **stdin variant** (when you cannot or don't want to export the
   keys): pipe two lines, from-key first.
   ```bash
   { printf '%s\n%s\n' "$OLD_KEY" "$NEW_KEY"; } | sudo .venv/bin/ameli-app \
     rotate-audit-key --from-key-stdin --to-key-stdin \
     --apply-env /etc/ameli-app-template-<env>/app.env
   ```

   **Legacy two-step variant with raw argv keys** is still
   supported but **discouraged** — the keys are visible in
   `ps`/history:
   ```bash
   # NOT RECOMMENDED: keys land in /proc/<pid>/cmdline
   sudo .venv/bin/ameli-app rotate-audit-key \
     --from-key "$OLD_KEY" --to-key "$NEW_KEY" || {
       echo "ABORT: rotation failed; do NOT touch the env file"
       return 1 2>/dev/null || exit 1
   }
   sudo sed -i "s|^AMELI_APP_AUDIT_HMAC_KEY=.*|AMELI_APP_AUDIT_HMAC_KEY=$NEW_KEY|" \
     /etc/ameli-app-template-<env>/app.env
   sudo systemctl restart ameli-app-template-<env>-api.service
   ```

4. **Sanity-check the post-rotation chain.**
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
