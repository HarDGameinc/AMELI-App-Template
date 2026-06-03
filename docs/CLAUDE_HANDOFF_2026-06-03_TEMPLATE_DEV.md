## AMELI App Template handoff (sesion Claude, 2026-06-03)

Fecha: `2026-06-03`

Este documento continua la linea de los handoffs previos
[`CODEX_HANDOFF_2026-06-02_TEMPLATE_DEV.md`](CODEX_HANDOFF_2026-06-02_TEMPLATE_DEV.md)
y [`CLAUDE_HANDOFF_2026-06-02_TEMPLATE_DEV.md`](CLAUDE_HANDOFF_2026-06-02_TEMPLATE_DEV.md).
Cubre el trabajo del 2026-06-03 sobre el Template Django-first y se
detiene mid-bloque para que otra IA o equipo siga sin perder contexto.

### Estado general

- Repo: `HarDGameinc/AMELI-App-Template`
- Rama estable: `main` (`cc868b7`)
- Rama de trabajo: `dev` (`615a878`)
- Servidor Debian: `/opt/ameli-app-template-dev`, puerto `18080`, host `0.0.0.0`
- Base PostgreSQL: `ameli_app_template_dev`
- Servicio systemd: `ameli-app-template-dev-api.service`

### Resumen del progreso 2026-06-03

#### Cerrados y promocionados a main (`cc868b7`)

1. **Bug `record_audit` con `actor=None`** — `actor_username` ahora cae a `""` para que el signal `user_login_failed` no produzca 500 en credenciales invalidas. Commit `6df5a00`.
2. **Self-guards backend** — `update_user_account` rechaza self-disable y self-role-change; `reset_user_password` rechaza self-reset; ambos antes de tocar DB (fail-fast). Commits `3627437` + `835fa23`. 12 tests en `tests/test_account_guards.py`.
3. **Dashboard polish** — `/` con hero adaptativo (auth/anon), `summary-cards-compact`, sidebar adaptativo, switch a `render()` para que corran context processors. Commits `7790dad` + `182247f`.
4. **E2E tests del dashboard** — `tests/test_dashboard.py` con 9 tests cubriendo auth y anon, especificamente protegen contra la regresion del context processor. Commit `cc868b7`.

Estado de la suite al cierre de `cc868b7`: **39 tests pasando**.

#### En `dev` por encima de `cc868b7` — bloque MFA en progreso

`dev` tiene 5 commits por encima de `main`. **No promocionados todavia**.

```
615a878 make mfa qr code render reliably in browsers   [pendiente de verificar visualmente]
0f3bb45 add mfa profile enrollment, confirm and self-disable flow
1c53bd9 make recovery code normalization separator-insensitive
6dd8a0d add totp helpers and recovery code primitives
c939668 add mfa data model, fields and migration
```

##### `c939668` — Commit 1/6: deps + modelo + migracion

- Agrega `pyotp>=2.9.0` y `qrcode>=7.4.0` a `requirements.txt`
- User model gana 3 campos: `mfa_secret` (CharField max 64), `mfa_enabled`, `mfa_required`
- Nuevo modelo `MFARecoveryCode(user FK, code_hash CharField(128), created_at, used_at)`
- Migracion `accounts/migrations/0003_mfa.py` escrita a mano
- Validado en servidor: `Applying accounts.0003_mfa... OK`, sin warning de makemigrations

##### `6dd8a0d` + `1c53bd9` — Commit 2/6: helpers TOTP

- Nuevo modulo `src/ameli_web/accounts/mfa.py` con:
  - `generate_secret()` (base32 via pyotp)
  - `provisioning_uri(secret, username, issuer)` (otpauth://)
  - `verify_totp(secret, code, valid_window=1)` (acepta drift ±30s, rechaza inputs invalidos)
  - `generate_recovery_code()` y `generate_recovery_codes(count=10)` (alfabeto sin caracteres confusos)
  - `normalize_recovery_code(code)` (case + separator insensitive)
  - `hash_recovery_code(code)` (SHA-256 hex)
  - `recovery_codes_match(stored, candidate)` (constant-time)
- Tests en `tests/test_mfa_helpers.py` — 14 pasando

##### `0f3bb45` — Commit 3/6: profile enrollment + UI

Backend:
- `services.start_mfa_enrollment(actor_username)` — sobrescribe pending, genera secret, devuelve `{secret, provisioning_uri, qr_svg}`
- `services.confirm_mfa_enrollment(actor_username, code)` — verifica codigo, activa MFA, genera 10 recovery codes (hashes), retorna plaintext una sola vez
- `services.disable_mfa_for_self(actor_username, current_password)` — re-confirma password antes de limpiar
- `services.serialize_mfa_status(user)` — para context de templates
- 3 nuevas views en `accounts/views.py`: `mfa_start_view`, `mfa_confirm_view`, `mfa_disable_view` (todas `@login_required @require_POST`, retornan JSON)
- 3 nuevas URL names: `profile-mfa-start`, `profile-mfa-confirm`, `profile-mfa-disable`
- `profile_view` ahora incluye `mfa_status` en context
- Audit events: `mfa_enrollment_started`, `mfa_enrollment_completed`, `mfa_enrollment_failed`, `mfa_disabled_by_self`

UI:
- Tab Seguridad gana panel "Autenticacion de dos factores (2FA)" con 4 estados mutuamente exclusivos: `disabled`, `pending`, `recovery`, `enabled`
- Flujo: Activar 2FA → POST start → muestra QR + secret + input → POST confirm → muestra 10 recovery codes una vez → reload → estado enabled
- Desactivar inline pide la contrasena actual
- "Estado de seguridad" card incluye fila 2FA con cuenta de codigos restantes
- CSS nuevo: `.mfa-pending-grid`, `.mfa-qr-shell`, `.mfa-pending-meta`, `.mfa-recovery-list`

Tests:
- `tests/test_mfa_service.py` — 13 tests cubriendo lifecycle, guard de password al desactivar, recovery code lifecycle y `serialize_mfa_status` en los 3 estados

##### `615a878` — Patch: QR rendering

- Cambia `SvgImage` → `SvgPathImage` en `render_qr_svg` (single path en vez de rects)
- Strip del XML prolog para que innerHTML lo trate como fragmento limpio
- CSS para el shell: `min-height:200px`, SVG fijo a 200×200, forzar `fill:#000` en el path

**PENDIENTE DE VERIFICACION VISUAL**: el QR no se renderizo en la primera prueba (cuadro blanco vacio); este commit es el fix. El usuario tuvo que cortar la sesion antes de confirmarlo. Primer paso del siguiente turno: aplicar el commit y verificar que el QR ahora si renderiza.

### Bloque MFA — commits que quedan

| # | Commit | Estado | Resumen |
|---|---|---|---|
| 1 | `c939668` | DONE | deps + modelo + migracion |
| 2 | `6dd8a0d` + `1c53bd9` | DONE | helpers TOTP + tests |
| 3 | `0f3bb45` + `615a878` | **VERIFICAR QR** | profile enrollment flow + UI |
| 4 | — | TODO | login `/login/verify-mfa` step (redirect post-password si MFA enrolado, aceptar TOTP o recovery code, audit success/failure, retry counter) |
| 5 | — | TODO | admin MFA actions (badge de status en lista, "Requerir MFA" PATCH, "Deshabilitar MFA del usuario" sin password) |
| 6 | — | TODO | regenerate recovery codes desde profile (action que invalida las viejas y genera 10 nuevas) |

### Bloque siguiente despues de MFA

**Email password reset (recovery flow)** — pendiente desde el plan original. Touch points:

- Backend email (django.core.mail). Por defecto usar `console.EmailBackend` para dev, `smtp.EmailBackend` para prod via config
- Routes nuevas: `/login/forgot/` (form con email/username) y `/login/reset/<token>/` (form con new password)
- Modelo `PasswordResetToken` o usar `django.contrib.auth.tokens.default_token_generator` (mas idiomatico, no necesita tabla)
- Templates: `accounts/password_reset_request.html`, `accounts/password_reset_confirm.html`, email templates
- Audit: `password_reset_requested`, `password_reset_completed`
- Link en `login.html` "¿Olvidaste tu contrasena?"
- Tests E2E + service tests

### Decisiones tomadas durante la sesion

Para que la siguiente IA no las re-discuta:

- **MFA stack**: `pyotp + qrcode` custom (no `django-otp` ni `django-two-factor-auth`) — control total del UI, no choca con metro shell
- **Politica MFA**: opcional por usuario + admin puede requerirlo individualmente (campo `mfa_required` en User)
- **Recovery codes**: 10 codigos one-time al enrolar, alfabeto sin caracteres confusos, formato XXXX-XXXX-XXXX, normalize separator-insensitive
- **Self-guard backend**: minimo (rechaza self-disable y self-role-change y self-reset-password). Acepta `must_change_password` para self porque es legitimo
- **Promocion dev → main**: cherry-pick lineal manual, sin merge commits

### Estado de tests al cierre

- En `cc868b7` (main): **39 tests pasando**
- En `615a878` (dev): se agregaron `test_mfa_helpers.py` (14) y `test_mfa_service.py` (13). Total esperado: **66 tests pasando** despues de deploy

`test_mfa_helpers` ya corrio verde en el servidor (14/14). `test_mfa_service` se commiteo pero el usuario corto sesion antes del primer `pytest` sobre ese archivo. Primer paso del siguiente turno: correr `DATABASE_URL= .venv/bin/pytest tests/test_mfa_service.py -v` y confirmar **13 passed**.

### Estado real del servidor al cierre

```
git log --oneline -1
# 615a878 make mfa qr code render reliably in browsers   (pendiente de aplicar)
```

El servidor estaba en `0f3bb45` (commit 3 sin el QR fix) cuando el usuario corto. Primer paso del siguiente turno en el servidor:

```bash
cd /opt/ameli-app-template-dev
git fetch origin
git reset --hard origin/dev
systemctl restart ameli-app-template-dev-api.service
```

### Orden recomendado para retomar

1. **Deploy del QR fix** (`615a878`) en el servidor. Cargar `/profile` → Seguridad → Activar 2FA → confirmar que el QR se ve correctamente.
2. **Correr `pytest tests/test_mfa_service.py -v`** y confirmar 13 passed.
3. **Verificar el flujo end-to-end manualmente**:
   - Escanear QR con Google Authenticator / Authy
   - Tipear el codigo de 6 digitos
   - Confirmar que aparecen 10 recovery codes en formato XXXX-XXXX-XXXX
   - Click "Listo, los guarde" → reload → ver estado "Activo"
   - Desactivar tipeando password → reload → vuelve a "Inactivo"
4. **Commit 4/6 MFA**: login `/login/verify-mfa` step. Cambios necesarios:
   - Override `form_valid` en `TemplateLoginView` (`accounts/views.py`): si user.mfa_enabled, NO llamar a auth_login; guardar `pending_mfa_user_id` en session; redirect a `/login/verify-mfa/`
   - Nueva view `verify_mfa_view`: GET muestra form (input para 6 digitos + link "usar recovery code"); POST valida; on success llama auth_login y limpia session; on fail audit + retry
   - Templates: `accounts/verify_mfa.html`
   - URLs: `/login/verify-mfa/`
   - Tests: pendiente_mfa → verify_mfa con codigo OK → fully logged in; con recovery code → marca como used; codigo invalido → 400 + audit
5. **Commit 5/6 MFA**: admin actions. Badge de MFA status en la tarjeta de usuario en `/admin`. Botones "Requerir MFA" / "Deshabilitar MFA del usuario" (sin password, esto es admin).
6. **Commit 6/6 MFA**: regenerate recovery codes desde profile. Action que invalida las viejas (delete + bulk_create new) y muestra nuevas una sola vez.
7. **Promocionar** todo el bloque MFA a main con cherry-pick lineal.
8. **Bloque siguiente**: email password reset.

### Archivos clave del trabajo actual

- [`src/ameli_web/accounts/mfa.py`](../src/ameli_web/accounts/mfa.py) — helpers TOTP + QR
- [`src/ameli_web/accounts/services.py`](../src/ameli_web/accounts/services.py) — `start_mfa_enrollment`, `confirm_mfa_enrollment`, `disable_mfa_for_self`, `serialize_mfa_status`
- [`src/ameli_web/accounts/views.py`](../src/ameli_web/accounts/views.py) — `mfa_start_view`, `mfa_confirm_view`, `mfa_disable_view`
- [`src/ameli_web/accounts/urls.py`](../src/ameli_web/accounts/urls.py) — rutas MFA
- [`src/ameli_web/accounts/models.py`](../src/ameli_web/accounts/models.py) — campos User MFA + modelo `MFARecoveryCode`
- [`src/ameli_web/accounts/migrations/0003_mfa.py`](../src/ameli_web/accounts/migrations/0003_mfa.py) — migracion hecha a mano
- [`src/ameli_web/templates/accounts/profile.html`](../src/ameli_web/templates/accounts/profile.html) — panel MFA en tab Seguridad
- [`src/ameli_app/static/css/app.css`](../src/ameli_app/static/css/app.css) — estilos `.mfa-*`
- [`tests/test_mfa_helpers.py`](../tests/test_mfa_helpers.py) — 14 tests
- [`tests/test_mfa_service.py`](../tests/test_mfa_service.py) — 13 tests
- [`AGENTS.md`](../AGENTS.md) — politica canonica

### Comandos utiles de continuidad

Local:

```bash
git log --oneline --decorate -10
git status --short --branch
```

Servidor (despues de pull, restart si cambio Python):

```bash
cd /opt/ameli-app-template-dev
git fetch origin
git reset --hard origin/dev
git log --oneline -1
systemctl restart ameli-app-template-dev-api.service
```

Tests (DATABASE_URL vacio para que use SQLite test DB):

```bash
DATABASE_URL= .venv/bin/pytest -v                          # full suite
DATABASE_URL= .venv/bin/pytest tests/test_mfa_service.py -v
```

Smoke test de self-guards (sin DB):

```bash
DJANGO_SETTINGS_MODULE=ameli_web.settings .venv/bin/python -c "
import django; django.setup()
from ameli_web.accounts.services import update_user_account, reset_user_password
for label, call in [
    ('self-disable', lambda: update_user_account('admin', 'admin', enabled=False)),
    ('self-demote', lambda: update_user_account('admin', 'admin', role='public')),
    ('self-reset', lambda: reset_user_password('admin', 'admin')),
]:
    try: call(); print(f'FAIL: {label} permitido')
    except ValueError as e: print(f'OK {label} bloqueado -> {e}')
"
```

### Bugs conocidos al cierre

- **QR rendering no verificado**: commit `615a878` deberia arreglarlo pero falta confirmar visualmente en `/profile`.
- Ninguno mas conocido.

### Pendientes opcionales para futuras sesiones

- **Pulir Sesiones tab del profile**: botones "Revocar sesion" y "Cerrar otras sesiones" son planos. Aplicar mismo estilo metro que el resto del profile. Bajo esfuerzo, baja prioridad.
- **Empezar primera app heredada del Template**: validar el flujo real de copiar/renombrar a una app concreta. Mayor scope, estrategico.

### Conversacion completa del 2026-06-03

En orden:

1. Patch del bug `record_audit` con actor None + verificacion via login fallido.
2. Auditoria backend del self-guard + fix minimo + smoke test + tests.
3. Promocion dev → main con cherry-pick lineal.
4. Tests para self-guards (12 tests).
5. Dashboard polish (hero adaptativo, summary-cards, sidebar adaptativo, switch a render()).
6. Tests E2E del dashboard (9 tests).
7. Promocion dev → main.
8. **Bloque MFA arrancado** (commits 1-3 de 6 hechos, commit 3.5 con QR fix pendiente de verificar).
9. Este handoff.
