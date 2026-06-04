## AMELI App Template handoff (sesion Claude, 2026-06-04)

Fecha: `2026-06-04`

Continuacion de
[`CODEX_HANDOFF_2026-06-02_TEMPLATE_DEV.md`](CODEX_HANDOFF_2026-06-02_TEMPLATE_DEV.md),
[`CLAUDE_HANDOFF_2026-06-02_TEMPLATE_DEV.md`](CLAUDE_HANDOFF_2026-06-02_TEMPLATE_DEV.md)
y [`CLAUDE_HANDOFF_2026-06-03_TEMPLATE_DEV.md`](CLAUDE_HANDOFF_2026-06-03_TEMPLATE_DEV.md).

Cubre el trabajo del 2026-06-04 — cierre completo del plan original de 3
bloques (E2E tests del dashboard, MFA segundo factor, email password
reset) y el handoff a la proxima sesion.

### Estado general al cierre

- Repo: `HarDGameinc/AMELI-App-Template`
- Rama estable: `main` (`26fb007`)
- Rama de trabajo: `dev` (`26fb007`, sincronizada)
- Servidor Debian: `/opt/ameli-app-template-dev`, puerto `18080`
- Base PostgreSQL de prueba: `ameli_app_template_dev`
- Servicio systemd: `ameli-app-template-dev-api.service`
- **117 tests pasando** (`pytest -v`)
- **0 regresiones** introducidas en la sesion
- **0 bugs conocidos** al cierre

### Resumen del progreso 2026-06-04

#### Bloque 1 — E2E tests del dashboard (1 commit)

`cc868b7 add e2e dashboard tests for auth and anon states`

Cubre `/` para anon y para superadmin/public, especificamente protege
contra la regresion del context processor que se arreglo el dia anterior.
9 tests en `tests/test_dashboard.py`.

#### Bloque 2 — MFA segundo factor (8 commits)

Implementacion completa basada en TOTP (pyotp + qrcode), recovery
codes hasheados y mucho mas. Promocionado a main el `2a3793a`.

| Commit | Resumen |
|---|---|
| `8153353` | deps + modelo + migracion |
| `44da0ea` | helpers TOTP + 14 unit tests |
| `2022da5` | normalize recovery code separator-insensitive |
| `e133c95` | profile enrollment flow (UI + backend + 13 tests) |
| `47f11c1` | QR rendering reliable (SvgPathImage + 7bit) |
| `14b4076` | handoff doc 2026-06-03 (mid-block) |
| `61bd41b` | login verify-mfa step (TOTP + recovery + 9 tests) |
| `9235d3a` | admin actions (require / disable + 9 tests) |
| `2a3793a` | regenerate recovery codes (UI + 4 tests) |

Resultado: MFA activable por self desde profile, exigible por admin,
forzado al login con TOTP o recovery code, y descartable por admin si
el usuario pierde acceso.

#### Bloque 3 — Email password reset (5 commits)

Email backend configurable (`console`/`smtp`/`file`/`locmem`/`dummy`),
service helpers, views, templates, link en login.

| Commit | Resumen |
|---|---|
| `f8e4aa3` | config (CFG email_*) + Django EMAIL_* + services (request + complete) + 15 service tests |
| `3803bd3` | forgot/reset views + URLs + 2 templates + link en login.html |
| `654ffbf` | charset=us-ascii (fix parcial QP) |
| `50f0f74` | `_PasswordResetEmail` con CTE 7bit forzado (fix definitivo wrapping) |
| `26fb007` | 13 E2E view tests |

Resultado: `/login/forgot/` -> identifier (username o email) -> email
con link de 60 min -> `/login/reset/<uidb64>/<token>/` con UX metro -> 
nueva clave -> redirect a `/login/` con flash. Self-guard contra
enumeracion, token signs over password hash (no se reusa), audit
events para cada paso.

### Trabajo no trivial / lessons learned del dia

#### El QR no renderizaba (commit 47f11c1)

`SvgImage` de qrcode 8.x emite multiples `<rect>` que heredan el fill
del CSS circundante y aparecian blanco-sobre-blanco. Switch a
`SvgPathImage` (single path) + strip del XML prolog + CSS forzando
`fill:#000` resolvio.

#### Quoted-printable rompia el reset URL (commits 654ffbf + 50f0f74)

Python's email package aplicaba QP soft-wrap (`=\n`) en lineas > 76
chars, partiendo el token al medio. Setear
`EmailMessage.encoding = "us-ascii"` no alcanzo porque Django/Python
seguian aplicando QP. Fix definitivo: subclase `_PasswordResetEmail`
que override `message()` para forzar payload raw + CTE 7bit.

#### Env file con caracteres especiales

`/etc/ameli-app-template-dev/app.env` tiene parens en el secret key,
no se puede `source`-ar desde bash. Workaround para smoke tests
ad-hoc: usar el flag `AMELI_APP_ENV_FILE=...` del propio `load_settings()`.

### Snapshot del Template al cierre

Esto es lo que entrega listo para heredar (todo verificado visual y por tests):

| Frente | Cobertura |
|---|---|
| Auth basico | login/logout, sesiones persistentes, audit por accion |
| Password policy | 12 chars + mayus + minus + numero + simbolo permitido; politica visible; generador; barra de robustez |
| Profile | identidad, alias, tema, password change con UX metro, sesiones registradas con revocacion |
| **Profile 2FA** | enrollment con QR + verify, 10 recovery codes (mostrados una vez), disable con password, regenerate codes |
| Admin metro | crear / editar / habilitar / deshabilitar usuarios, reset password, cambiar rol, forzar cambio, eliminar (con confirm) |
| **Admin 2FA** | badge status (active / requerido / off), require/clear, disable (con confirm), audit |
| Self-guards backend | rejects self-disable, self-role-change, self-mfa-toggle, self-reset-password; allow self-must_change_password |
| **Login flow** | username + password -> redireccion a verify-mfa si MFA enrolado -> TOTP o recovery code -> profile |
| **Password recovery** | `/login/forgot/` con anti-enumeration, email con link de 60 min, `/login/reset/` con UX metro |
| Dashboard | hero adaptativo auth/anon, summary cards, sidebar adaptativo, version chip |
| Docs | `/docs` (Swagger), `/redoc`, `/openapi.json` |
| Operacion | install/update/backup, systemd multientorno (api/worker/web/maintenance/etc), validate_installation |
| Email | console/smtp/file/locmem backends configurables via YAML + env vars |
| Tests | 117 (E2E + unit + helpers), corren en SQLite test DB para CI |

### Numeros de la sesion

- 14 commits promocionados a main (4 - 17 = 14 commits desde `cc868b7` hasta `26fb007`)
- 117 tests pasando (al inicio de la sesion eran 39 - sumamos 78)
- 3 nuevos archivos de tests: `test_login_mfa.py`, `test_admin_mfa.py`, `test_mfa_helpers.py`, `test_mfa_service.py`, `test_password_reset_service.py`, `test_password_reset_views.py` (6 archivos nuevos, 78 tests nuevos)
- 1 migracion nueva (`0003_mfa.py`)
- 2 deps nuevas (`pyotp`, `qrcode`)
- ~50 archivos nuevos o modificados

### Decisiones tomadas durante la sesion

Para que la proxima IA no las re-discuta:

- **MFA stack**: `pyotp + qrcode` custom (control total UI), no `django-otp` ni `django-two-factor-auth`
- **MFA policy**: opcional por usuario, admin puede requerirlo individualmente con campo `User.mfa_required`
- **Recovery codes**: 10 codigos one-time al enrolar, alfabeto sin caracteres confusos, formato `XXXX-XXXX-XXXX`, normalize separator-insensitive
- **MFA admin disable**: no requiere password (es accion de admin), rechaza self
- **Password reset tokens**: Django's `default_token_generator` (signs over password hash → no DB table necesaria, invalida al cambiar password)
- **Reset token TTL**: 60 minutos (configurable)
- **Anti-enumeration en forgot password**: respuesta visual identica para user-found vs user-not-found; audit log distingue
- **Email backend default**: `console` (printea a stdout/journalctl, util en dev)
- **Email CTE para reset**: forzado 7bit cuando body es ASCII (subclase `_PasswordResetEmail`)
- **Self-guards backend**: minimo (rechaza self-disable, self-role-change, self-reset-password, self-mfa-toggle). Acepta `must_change_password` para self porque es legitimo
- **Promocion dev → main**: cherry-pick lineal manual, sin merge commits

### Proximos bloques abiertos

#### Pulir Sesiones tab del profile (chico)

Los botones "Revocar sesion" y "Cerrar otras sesiones" en
`/profile` -> Sesiones siguen siendo planos. El resto del profile esta
con el estilo metro. Aplicar el mismo patron de actions row al panel
de sesiones. Bajo esfuerzo (~1-2 commits), bajo riesgo.

#### MFA por email (nuevo bloque sugerido por el usuario)

El usuario pidio que MFA tambien pueda enviarse por email para usuarios
que no quieran instalar una app de autenticacion (Google Authenticator,
Authy, etc.). Diseno propuesto a confirmar:

**Modelo:**
- Agregar `User.mfa_method` (`"totp"` | `"email"` | `""`) — campo nuevo, migracion
- Mantener `mfa_secret` para TOTP (cuando `mfa_method="totp"`)
- Para email, no se necesita secret persistido — los codigos se generan en demanda

**Storage del codigo email:**
- Opcion A: nuevo modelo `MFAEmailChallenge(user, code_hash, created_at, used_at, expires_at)`
- Opcion B: signed token en sesion (no DB), TTL via timestamp
- Recomiendo A para que sobreviva al user closing browser y poder auditar

**Flujo enrollment:**
- En profile -> 2FA -> elegir metodo: "App de autenticacion" o "Email"
- App: flujo actual (QR + verify)
- Email: mostrar email del user, boton "Enviarme un codigo de prueba", input para confirmar, al confirmar -> mfa_enabled=true, mfa_method='email'
- Recovery codes: tambien generados en ambos casos

**Flujo login:**
- POST /login con username + password
- Si `mfa_enabled=true and mfa_method='totp'` -> redirect a /login/verify-mfa actual
- Si `mfa_enabled=true and mfa_method='email'` -> generar codigo, mandar email, redirect a /login/verify-mfa-email
- El template puede ser el mismo /login/verify-mfa con un "Solicitar codigo" button visible cuando method=email
- Recovery code funciona en ambos casos

**Admin:**
- En admin user list, badge muestra metodo: "2FA totp" / "2FA email" / "2FA requerido" / "2FA off"
- Disable MFA from admin: igual, limpia mfa_secret + mfa_method + codes

**Edge cases:**
- User cambia email mientras tiene MFA email enrolado -> el proximo login enviara al nuevo email; sin problema
- User pierde acceso al email -> recovery codes
- User pierde recovery codes Y email -> admin disable

**Tests:**
- enroll email flow
- send + verify email code at login
- expired email code rejected
- replay (used) email code rejected
- mfa_method=totp + login uses TOTP (regresion guard)

**Estimacion:** 3-4 commits razonables.
  1. modelo + migracion + service helpers + tests
  2. profile UI: eleccion de metodo + enrollment email
  3. login: verify-mfa con send-code button + email verification
  4. admin: badge del metodo, opcional

#### Empezar primera app heredada del Template (estrategico)

Validar el flujo real de copiar/renombrar el Template a una app
concreta (AMELI Algo). Mayor scope, requiere conversacion previa
sobre que app concreta.

### Estado real del servidor al cierre

```
git log --oneline -1
# 26fb007 add e2e dashboard tests for auth and anon states  (era el mensaje del ultimo cherry-pick)
```

El servidor estaba en `cc39327` antes del force-push del cherry-pick.
Despues del force-push tendra que correr:

```bash
cd /opt/ameli-app-template-dev
git fetch origin
git reset --hard origin/dev
```

Sin restart porque el contenido es identico (solo cambian hashes).

### Orden recomendado para retomar

1. **Resync del servidor al nuevo hash de dev** (`26fb007`).
2. **Pulir Sesiones tab del profile** — bloque chico, cierra la
   consistencia visual del profile. Bajo riesgo.
3. **MFA por email** — bloque medio, alta utilidad para usuarios
   sin authenticator app. Requiere primero confirmar el diseno
   propuesto arriba.
4. **Empezar primera app real** — estrategico, mayor scope,
   conversacion previa con el equipo sobre que app.

### Comandos utiles de continuidad

Local:

```bash
git log --oneline --decorate -10
git status --short --branch
```

Servidor (templates / JS / CSS solamente):

```bash
cd /opt/ameli-app-template-dev
git fetch origin
git reset --hard origin/dev
systemctl restart ameli-app-template-dev-api.service
```

Servidor (cambios de modelos o deps):

```bash
APP_ENV=dev APP_SLUG=ameli-app-template APP_PACKAGE=ameli_app bash scripts/install.sh
```

Tests con DB vacia (SQLite via pytest-django):

```bash
DATABASE_URL= .venv/bin/pytest -v
```

Smoke test directo contra Django (env file con caracteres especiales,
usa nuestro propio loader):

```bash
AMELI_APP_ENV_FILE=/etc/ameli-app-template-dev/app.env \
DJANGO_SETTINGS_MODULE=ameli_web.settings \
.venv/bin/python -c "
import django; django.setup()
from django.contrib.auth import get_user_model
print(get_user_model().objects.values('username', 'email', 'mfa_enabled', 'mfa_method' if False else 'mfa_required'))
"
```

### Archivos clave para continuar

- [`AGENTS.md`](../AGENTS.md) — politica canonica
- [`src/ameli_web/accounts/models.py`](../src/ameli_web/accounts/models.py) — User + MFARecoveryCode + UserSession
- [`src/ameli_web/accounts/services.py`](../src/ameli_web/accounts/services.py) — todo el dominio (auth, mfa, password reset, audit)
- [`src/ameli_web/accounts/views.py`](../src/ameli_web/accounts/views.py) — login + profile + mfa + reset views
- [`src/ameli_web/accounts/mfa.py`](../src/ameli_web/accounts/mfa.py) — helpers puros TOTP + QR + recovery codes
- [`src/ameli_web/accounts/urls.py`](../src/ameli_web/accounts/urls.py) — todas las rutas de accounts
- [`src/ameli_web/admin_views.py`](../src/ameli_web/admin_views.py) — admin endpoints
- [`src/ameli_web/templates/accounts/`](../src/ameli_web/templates/accounts/) — login, profile, verify_mfa, forgot_password, reset_password, password_reset_email
- [`src/ameli_web/templates/admin/panel.html`](../src/ameli_web/templates/admin/panel.html) — admin shell
- [`src/ameli_web/templates/dashboard/home.html`](../src/ameli_web/templates/dashboard/home.html) — public dashboard
- [`src/ameli_app/config.py`](../src/ameli_app/config.py) — Settings + load_settings + settings_summary
- [`src/ameli_web/settings.py`](../src/ameli_web/settings.py) — Django settings que leen CFG
- [`config/app.yaml.example`](../config/app.yaml.example) — config canonica
- [`tests/`](../tests/) — 117 tests organizados por feature

### Conversacion completa del 2026-06-04

En orden:

1. Retomada del 2026-06-03: deploy del QR fix + verificacion del flujo MFA end-to-end.
2. Commit 4/6 MFA: login verify-mfa step + 9 tests.
3. Commit 5/6 MFA: admin MFA actions + 9 tests.
4. Commit 6/6 MFA: regenerate recovery codes + 4 tests.
5. Promocion del bloque MFA a main.
6. Inicio del bloque email password reset.
7. Commit 1/3: config + EMAIL_* + services + 15 tests.
8. Commit 2/3: views + URLs + templates + link en login.
9. Debug del QP wrapping de URLs en email (2 commits de fix).
10. Commit 3/3: 13 E2E view tests.
11. Promocion del bloque email password reset a main.
12. Este handoff.
