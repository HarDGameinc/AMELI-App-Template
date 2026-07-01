# Changelog

## v0.4.2-django — 2026-07-01 (PC-1 cleanup + PC-2)

Cierra el split estructural del paquete `accounts/`: `services/__init__.py`
queda como puro re-export y `accounts/views.py` se convierte en un paquete
por dominios. La API publica esta intacta — todos los imports de
`from ameli_web.accounts.services import X` y de
`from ameli_web.accounts.views import X` siguen funcionando.

### PC-1 cleanup (commit `0268300`)

Extraidos los 4 dominios residuales de `services/__init__.py`:

- `services/retention.py` (194 lineas) — `run_retention_sweep`,
  `_prune_audit_with_anchor`.
- `services/reporting.py` (286 lineas) — `summarize_users`,
  `summarize_email_queue`, `serialize_audit_event`,
  `list_recent_audit_entries`, `_audit_queryset_for_filters`,
  `paginate_audit_for_admin`, `filtered_audit_queryset`,
  `_display_tone_for_action`.
- `services/auth_alerts.py` (189 lineas) — auth-failure alert (ASVS V2.2.3).
- `services/email_change.py` (302 lineas) — double-opt-in flow.

`services/__init__.py` paso de 1104 a ~200 lineas. `EmailChangeRequest`
(modelo) queda re-exportado para preservar `from ameli_web.accounts.services
import EmailChangeRequest`.

### PC-2 (commit `94ce941`)

`accounts/views.py` (1267 lineas) convertido a paquete `accounts/views/`
con 9 modulos por dominio:

- `views/_common.py` (42) — helpers + session keys + logger + User.
- `views/auth.py` (~410) — login + verify MFA.
- `views/profile.py` (~350) — profile page + preferences + avatar + test email.
- `views/password.py` (~285) — change + forgot + reset.
- `views/account.py` (~120) — delete self.
- `views/sessions.py` (~120) — revoke sessions.
- `views/mfa.py` (~225) — 8 MFA endpoints.
- `views/email_change.py` (~210) — 4 email-change endpoints.
- `views/__init__.py` — puro re-export.

`_build_public_base_url` re-exportado desde `views/__init__.py` para tests.

### Fix colateral

`tests/test_code_review_fixes_20260615.py` re-apuntado de
`ameli_web.accounts.services.timezone.now` a
`ameli_web.accounts.services.throttle.timezone.now` (el modulo donde
`_read_throttle_counter_sliding` realmente lee el reloj) tras la extraccion
de `timezone` del top-level de `services/__init__.py`.

### Verificacion

- 1012 tests pass en Windows; 11 pre-existentes de Windows + 1 race
  intermitente del circuit breaker.
- Ruff 0 errores, mypy 0 errores en codigo del paquete.
- S-05 aprobado en `ha-report2`: 29 view symbols importables, 4 rutas
  publicas → 200, 3 privadas → 302, audit chain integro, login manual OK.

## v0.4.1-django — 2026-06-30 (PC-1 cierre)

Refactor interno de `accounts/services.py` (~3793 lineas, un solo modulo) en
un paquete con dominios separados. La API publica esta intacta: todos los
imports de `from ameli_web.accounts.services import X` siguen funcionando.

- Step 2 (commit `58d0061`): `services/audit.py` — cadena de audit, rotacion
  de clave HMAC (462 lineas).
- Step 3 (commit `9bd1233`): `services/throttle.py` — contadores atomicos,
  lockout, rate limits (495 lineas).
- Step 4 (commit `239d34e`): `services/sudo.py` — sudo grants, brute-force
  gate (211 lineas).
- Step 5 (commit `d24b6d8`): `services/email_queue.py` — circuit breaker SMTP,
  outbox pattern, retry queue (426 lineas).
- Step 6 (commit `388e906`): `services/mfa.py` — TOTP, email MFA, recovery
  codes (545 lineas).
- Step 7 (commit `6398881`): `services/session.py` (234 lineas), `services/
  maintenance.py` (83 lineas), `services/password_reset.py` (178 lineas).
- Step 8 (commit `87485f5`): `services/user.py` — CRUD, serialize, avatars,
  password/email change para self, delete account (543 lineas).
- Fix (commit `62c68c8`): lazy imports en `sudo.py` re-targeteados a `.mfa`
  tras el step 6.

`services/__init__.py` queda en 1104 lineas (vs 3793 originales) con
retention sweep, audit reporting, auth-failure alerts y el flow de email
change double-opt-in todavia adentro — esos dominios son candidatos para
futuras iteraciones pero no afectan la limpieza estructural lograda.

Verificacion: 1013 tests pass (mismos 11 failures pre-existentes de Windows,
no son regresion). Ruff 0 errores, mypy 0 errores en codigo del paquete.

## v0.1.0

- Plantilla inicial AMELI para apps Python operacionales.
- Incluye API, dashboard, CLI, workers, PostgreSQL, Alembic, systemd, scripts y
  tests base.

