## AMELI App Template handoff (sesion Claude, 2026-06-05)

Fecha: `2026-06-05`

Continuacion de [`CLAUDE_HANDOFF_2026-06-04_EMAIL_MFA_TEMPLATE_DEV.md`](CLAUDE_HANDOFF_2026-06-04_EMAIL_MFA_TEMPLATE_DEV.md).

Cierra el refactor stacked de MFA, agrega self-service de email en el
profile, valida SMTP real contra Office 365 y arregla incompatibilidad
con Python 3.13. Promueve todo a `main`.

### Estado general al cierre

- Repo: `HarDGameinc/AMELI-App-Template`
- Rama estable: `main` (post-promocion del dia)
- Rama de trabajo: `dev` (sincronizada con `main`)
- Servidor Debian: `/opt/ameli-app-template-dev`, puerto `18080`
- **197 tests pasando** (`pytest -v`)
- **0 regresiones**
- Verificado end-to-end visual: profile stacked, login selector, swap
  method, admin badge granular, stacking sin recovery screen vacia,
  edicion de email + correo de prueba + auto-disable de 2FA email
- Verificado contra **Office 365 SMTP real**: test email, activacion
  2FA email (codigo de 6 digitos), forgot password (link en linea unica)

### Contexto: que estaba pendiente al arrancar

El handoff `2026-06-04_EMAIL_MFA` cerro el commit 2/5 del refactor
stacked (12 tests del service layer + cobertura de coexistencia y
disable por metodo). Quedaba el commit 3/5 explicitamente documentado:
**profile UI con secciones independientes para TOTP y Email** — y
nunca se hizo. La sesion termino con `9ffce31` y `/export`.

Sintoma visible al retomar: el profile mostraba "App de autenticacion
(TOTP)" para un usuario que tenia email enrolado, porque
`serialize_mfa_status` ya devolvia `totp_enabled`/`email_enabled` por
separado y dejo de devolver la clave `method` (singular), pero el
template seguia haciendo `mfa_status.method == "email"` que siempre era
falsy.

### Resumen del progreso 2026-06-05

8 commits promocionados a `main`:

| Commit | Resumen |
|---|---|
| `b4b7160` | refactor mfa to stacked methods (commit 1/5) — venia del 2026-06-04 |
| `9ffce31` | add stacked mfa coexistence and per-method disable tests (2/5) |
| `b1a52fe` | add egg-info to gitignore |
| `002971c` | render stacked mfa methods in profile with per-method disable |
| `255dd96` | add method selector to verify-mfa for users with two factors |
| `a0a31b3` | add e2e tests for stacked profile ui, login selector and admin badge |
| `c21724d` | fix profile mfa email card copy and inline badge layout |
| `93ad309` | skip empty recovery screen when stacking a second mfa method |

#### Profile UI stacked (`002971c`)

- Nuevo panel "Autenticacion de dos factores (2FA)" con header de status
  unificado: `Activo (App + Email)` / `Activo (App de autenticacion)` /
  `Activo (Email)` / `Inactivo`
- Dos cards independientes con badge inline `Activo`/`Inactivo` cada una:
  - **App de autenticacion**: boton `Activar con app` (inactiva) o input
    de password + boton `Desactivar app` (activa)
  - **Email**: boton `Activar con email` (inactiva, deshabilitado si el
    usuario no tiene email registrado) o input de password + boton
    `Desactivar email` (activa)
- Recovery codes mostrados una sola vez abajo (compartidos entre metodos)
  + boton `Regenerar codigos de recuperacion` visible solo si al menos
  un metodo esta activo
- Nuevas views: `mfa_totp_disable_view`, `mfa_email_disable_view`
- Nuevas URLs: `/profile/mfa/totp/disable/`, `/profile/mfa/email/disable/`
- JS refactor: helper `wireDisableButton()` evita duplicar logica entre
  metodos

#### Login method selector (`255dd96`)

- `verify_mfa_view` ahora soporta 3 estados:
  1. **Selector** (cuando el user tiene 2+ metodos activos y no eligio uno):
     renderiza dos cards con `Usar app` / `Recibir codigo por email`
  2. **Input** (cuando el user ya eligio o tiene un solo metodo): formulario
     de codigo + boton "Usar email/app en su lugar" si hay swap disponible
  3. **Selector explicito**: `POST { choose_method: "totp"|"email" }` setea
     `PENDING_MFA_METHOD_KEY` en sesion, dispara envio de email si aplica,
     redirige a `/login/verify-mfa/`
- Nueva clave de sesion `PENDING_MFA_METHOD_KEY`, limpiada por
  `_clear_pending_mfa()` junto al resto
- Email **NO se envia** al llegar al selector — solo al elegir email
- Recovery codes funcionan en cualquier estado

#### Admin badge granular (era heredado, ahora con tests `a0a31b3`)

El refactor stacked del 2026-06-04 ya emitia los badges granulares
(`2FA TOTP+Email` / `2FA TOTP` / `2FA Email` / `2FA requerido` /
`2FA off`) en `admin/panel.html`. La sesion `a0a31b3` agrego los 4
tests E2E que faltaban para cubrir el render.

#### E2E tests (`a0a31b3`)

Nuevo archivo `tests/test_mfa_stacked_views.py` con 18 tests:

| Bloque | Tests |
|---|---|
| Profile rendering | 4 (no mfa, solo totp, solo email, ambos) |
| Per-method disable | 4 (totp keeps email, email keeps totp, wrong password, requires login) |
| Login selector | 5 (selector when 2 methods, choose email triggers send, choose totp no email send, single method skips selector, swap after selection) |
| Admin badge granular | 5 (serialize per-method flags + 4 badge renders) |

#### Fixes UX (`c21724d`, `93ad309`)

- `c21724d`: el copy del card de Email decia "Te mandamos un codigo a
  en cada ingreso" porque el template usaba `current_user.email` y
  `serialize_user` no expone email. Fix: usar `request.user.email`
  directo. Tambien quitamos el stretch del badge moviendolo inline en
  el `<h3>`.
- `93ad309`: al stackear un segundo metodo (ej. TOTP encima de email
  ya activo), la pantalla "Guarda tus codigos de recuperacion" aparecia
  vacia porque `confirm_mfa_enrollment` devuelve `recovery_codes: []`
  en ese caso (los codigos ya se mostraron una vez). Fix JS: helper
  `showRecoveryOrReload()` que recarga el profile si el array es vacio.

### Decisiones tomadas (no re-discutirlas)

- **Login default cuando hay 2+ metodos**: NO autoenviar email; mostrar
  selector primero. Asi evitamos enviar email y rate-limitar a usuarios
  que prefieren TOTP.
- **Default sin metodo elegido y un solo metodo activo**: usar ese
  metodo automaticamente (sin selector, sin overhead UX).
- **Cambio de metodo en plena sesion**: boton `Usar email/app en su
  lugar` reposiciona la sesion via `POST { choose_method }` y vuelve a
  renderizar la pantalla del nuevo metodo. Email se envia recien ahi.
- **Per-method disable**: requiere password. Si era el ultimo metodo,
  borra recovery codes. Si quedaba otro activo, los mantiene.
- **Legacy `disable_mfa_for_self` (nuke all)**: queda en services como
  fallback, pero el UI nuevo no lo usa. Sigue cubierto por
  `test_mfa_stacked.py::test_legacy_disable_for_self_nukes_both_methods`.
- **Stacking de segundo metodo sin recovery screen**: cuando ya
  existen recovery codes, no mostramos pantalla vacia — recargamos el
  profile directamente.
- **Badge granular en admin**: ya estaba en `754dc15` del 2026-06-04,
  ahora con tests.

### Numeros de la sesion

- 8 commits promocionados a `main`
- **183 tests pasando** (165 al inicio + 18 nuevos en `test_mfa_stacked_views.py`)
- 0 migraciones nuevas (`0005_mfa_stacked` venia del dia anterior)
- 0 deps nuevas
- 6 archivos nuevos o modificados:
  - `src/ameli_web/accounts/views.py` (per-method disable + selector)
  - `src/ameli_web/accounts/urls.py` (3 URLs nuevas)
  - `src/ameli_web/templates/accounts/profile.html` (panel stacked + JS)
  - `src/ameli_web/templates/accounts/verify_mfa.html` (selector + swap)
  - `tests/test_mfa_stacked_views.py` (18 tests nuevos)
  - `.gitignore` (egg-info)

### Snapshot del Template al cierre

| Frente | Cobertura |
|---|---|
| Auth basico | login/logout, sesiones persistentes, audit por accion |
| Password policy | 12 chars + mayus + minus + numero + simbolo permitido; politica visible; generador; barra de robustez |
| Profile | identidad, alias, tema, password change con UX metro, sesiones registradas con revocacion |
| **Profile 2FA stacked** | TOTP y Email coexistentes, enrollment independiente, per-method disable, recovery codes compartidos, regenerate |
| Admin metro | crear / editar / habilitar / deshabilitar / reset password / cambiar rol / forzar cambio / eliminar |
| **Admin 2FA granular** | badges: `2FA TOTP+Email` / `2FA TOTP` / `2FA Email` / `2FA requerido` / `2FA off`; require/clear; admin disable (nuke); audit |
| Self-guards backend | rejects self-disable, self-role-change, self-mfa-toggle, self-reset-password; allow self-must_change_password |
| **Login flow stacked** | password -> selector si 2+ metodos -> codigo TOTP/email/recovery -> profile; swap entre metodos in-flight; rate limit + resend para email |
| Password recovery | `/login/forgot/` anti-enumeration, email con link de 60 min, `/login/reset/` con UX metro |
| Dashboard | hero adaptativo auth/anon, summary cards, sidebar adaptativo, version chip |
| Docs | `/docs` (Swagger), `/redoc`, `/openapi.json` |
| Operacion | install/update/backup, systemd multientorno, validate_installation |
| Email | console/smtp/file/locmem backends configurables via YAML + env vars |
| Tests | 183 (E2E + unit + helpers), corren en SQLite test DB para CI |

### Trabajo no trivial / lessons learned del dia

#### El bug invisible despues del refactor

`b4b7160` cambio el shape de `serialize_mfa_status` (quito `method`, agrego
`totp_enabled`/`email_enabled`/`totp_pending`/`email_pending`). Los tests
del service layer cubrian todo. Los tests E2E del bloque email MFA del
2026-06-04 testeaban el endpoint, no el render del profile. Resultado:
el bug se vio recien visualmente en el navegador.

**Lecciones**:
- Tests E2E que afirman sobre `data-mfa-method` y `data-mfa-active`
  hubieran cazado el bug. Ahora estan en `test_profile_renders_*`.
- Los refactors que cambian shape de un dict consumido por templates
  siempre necesitan tests del template, no solo del consumer.

#### El env file con caracteres especiales para smoke tests

Mismo workaround del 2026-06-04: el bash no puede `source` el
`/etc/ameli-app-template-dev/app.env` por los parens en el secret.
Para smoke tests directos contra Django usar el flag
`AMELI_APP_ENV_FILE=...` del loader nuestro.

#### Validacion visual previa al promote

El usuario validate visual en cada feature antes de promover (4
screenshots: stacking, selector, swap, login completo + admin badge).
Esto es lo que cazo los dos UX bugs (`c21724d`, `93ad309`) que la
suite de 165 tests no marcaba.

### Bloque tarde: self-service de email + SMTP real

Cerrado el refactor stacked, surgio un gap UX: el usuario no tenia donde
ingresar/cambiar su email (solo el admin podia desde el panel), asi que
quien no tuviera email no podia activar 2FA email. Ademas queriamos
validar SMTP real (no solo console backend) contra una casilla.

4 commits adicionales:

| Commit | Resumen |
|---|---|
| `a0f95ad` | let users edit their email and send a test email from profile |
| `99842b5` | surface smtp errors as 502 json instead of opaque 500 |
| `4ad592f` | forward args to email message override for python 3.13 policy kwarg |
| (handoff) | actualizacion de este doc |

#### Email editable + correo de prueba (`a0f95ad`)

- `ProfilePreferencesForm` ahora incluye `email` con validacion EmailField
  y normalizacion lowercase + strip
- Nuevo service `change_email_for_self(actor_username, new_email)`:
  - normaliza, detecta cambio real (no-op si es el mismo)
  - si el user tenia 2FA email activo → lo desactiva + borra challenges +
    recomputa `mfa_enabled`; si era el unico metodo activo, borra los
    recovery codes
  - audita `update_my_email` con `mfa_email_disabled: bool`
- Nuevo service `send_profile_test_email(user, last_sent_at)`:
  - cooldown de 30s via `PROFILE_TEST_EMAIL_SESSION_KEY` (sin DB)
  - mismo `_PasswordResetEmail` 7bit para evitar QP wrapping
  - audita `profile_test_email_sent`
- Nueva view + URL `/profile/email/test/`
- UI nueva en el tab "Editar perfil":
  - input email editable con help text
  - warning rojo si `mfa_email_enabled` y el user va a cambiar el email
  - boton "Enviar correo de prueba" visible solo si tiene email guardado
- `serialize_user` ahora expone `email`
- Side panel "Identidad y preferencias" muestra el email guardado o
  "Sin email" en warning

#### Surface SMTP errors (`99842b5`)

`mfa_email_start_view`, `verify_mfa_resend_view` y
`send_profile_test_email_view` ahora atrapan `Exception` ademas de
`ValueError` para devolver el error real del SMTP como JSON 502 en lugar
de un 500 mudo. Esto permite diagnosticar problemas de credenciales /
tenant / firewall directamente desde el navegador.

#### Python 3.13 compat (`4ad592f`)

Python 3.13 agrego un `policy` kwarg a `EmailMessage.message()`. Nuestra
subclase `_PasswordResetEmail` (la que fuerza 7bit para que el reset URL
no se rompa con QP soft-wrap) overrideaba el metodo con la signatura
vieja, asi que en 3.13 fallaba con `TypeError: got an unexpected keyword
argument 'policy'` cada vez que el codigo intentaba enviar un email real.

Fix: aceptar `*args, **kwargs` y reenviarlos al super. Funciona en 3.11
(tests CI) y en 3.13 (servidor).

Tests locales corrian Python 3.11 y no cazaron el bug. Lo cazo el
smoke test contra O365 real.

### Lecciones de SMTP / Office 365

- `5.7.139 Authentication unsuccessful` con un App Password recien
  generado puede significar dos cosas:
  - **Password mal creada**: la pantalla muestra los 16 chars pero la
    generacion falla a nivel directorio (paso real del dia). Verificar
    comparando contra una password que ya funciono en otra app del mismo
    tenant.
  - **SMTP AUTH bloqueado** a nivel buzon o tenant: revisar
    `Get-CASMailbox -Identity X | fl SmtpClientAuthenticationDisabled` y
    M365 Admin Center → Settings → Org Settings → Modern Authentication
    → "Authenticated SMTP" tildado
- Las apps `ameli-notifier` y `ameli-app-template-dev` pueden compartir
  la misma App Password de `ameli@agnov.cl` si estan en la misma
  organizacion. Mejor mantener una sola "fuente de la verdad" en
  `/etc/ameli-notifier/secrets/email_default.password` (no expuesta en
  env files).
- Office 365 funciona contra `smtp.office365.com:587` con `STARTTLS`
  (TLS=true, SSL=false). Gmail funciona contra `smtp.gmail.com:587`
  bajo el mismo patron.
- `EMAIL_FROM` debe ser igual a `EMAIL_USERNAME` en O365 (y en Gmail).

### Proximos bloques abiertos

#### Pulir Sesiones tab del profile (chico)

Mismo punto que el handoff anterior: los botones "Revocar sesion" y
"Cerrar otras sesiones" en `/profile/` → Sesiones siguen siendo planos.
Bajo esfuerzo (~1-2 commits), bajo riesgo.

#### Empezar primera app heredada del Template (estrategico)

Validar el flujo real de copiar/renombrar el Template a una app
concreta (AMELI Algo). Mayor scope, requiere conversacion previa
sobre que app concreta.

#### Refinar estilo del boton "Activar con app" en profile (cosmetico)

Hoy hereda el estilo grande `.primary` y queda visualmente desbalanceado
contra el del card de email. Decidir si reducimos a `.primary` compacto
o mantenemos el tamaño actual.

#### Mover la password del email a un archivo separado (mejora)

Hoy `AMELI_APP_EMAIL_PASSWORD` vive en `app.env`. Otras apps AMELI
(notifier) usan `smtp_password_file: /etc/ameli-X/secrets/...`. Si la
politica de la organizacion lo pide, agregar soporte en `config.py`
para leer la password desde un archivo en lugar del env. Cambio chico.

### Orden recomendado para retomar

1. **Resync local + servidor** al hash de `main` post-promocion del dia.
2. **Pulir Sesiones tab del profile** — bloque chico, cierra consistencia
   visual.
3. **Primera app real heredada** — estrategico, mayor scope.

### Comandos utiles de continuidad

Local:

```bash
git log --oneline --decorate -10
git status --short --branch
```

Servidor (resync sin migraciones nuevas, solo templates / JS / CSS):

```bash
cd /opt/ameli-app-template-dev
git fetch origin
git reset --hard origin/dev
systemctl restart ameli-app-template-dev-api.service
```

Servidor (cuando hay cambios de modelos o deps):

```bash
APP_ENV=dev APP_SLUG=ameli-app-template APP_PACKAGE=ameli_app bash scripts/install.sh
```

Tests con DB vacia (SQLite via pytest-django):

```bash
DATABASE_URL= .venv/bin/pytest -v
```

Smoke test directo contra Django:

```bash
AMELI_APP_ENV_FILE=/etc/ameli-app-template-dev/app.env \
DJANGO_SETTINGS_MODULE=ameli_web.settings \
.venv/bin/python -c "
import django; django.setup()
from django.contrib.auth import get_user_model
U = get_user_model()
for u in U.objects.all():
    print(u.username, u.email, u.mfa_totp_enabled, u.mfa_email_enabled)
"
```

### Archivos clave para continuar

- [`AGENTS.md`](../AGENTS.md) — politica canonica
- [`src/ameli_web/accounts/models.py`](../src/ameli_web/accounts/models.py) — User (mfa_totp_enabled, mfa_email_enabled, mfa_secret) + MFARecoveryCode + MFAEmailChallenge + UserSession
- [`src/ameli_web/accounts/services.py`](../src/ameli_web/accounts/services.py) — todo el dominio (auth, mfa stacked, password reset, audit, serialize)
- [`src/ameli_web/accounts/views.py`](../src/ameli_web/accounts/views.py) — login + profile + mfa stacked + reset views
- [`src/ameli_web/accounts/mfa.py`](../src/ameli_web/accounts/mfa.py) — helpers puros TOTP + QR + recovery codes + email codes
- [`src/ameli_web/accounts/urls.py`](../src/ameli_web/accounts/urls.py) — todas las rutas de accounts (per-method disable URLs nuevas)
- [`src/ameli_web/admin_views.py`](../src/ameli_web/admin_views.py) — admin endpoints
- [`src/ameli_web/templates/accounts/profile.html`](../src/ameli_web/templates/accounts/profile.html) — panel 2FA stacked
- [`src/ameli_web/templates/accounts/verify_mfa.html`](../src/ameli_web/templates/accounts/verify_mfa.html) — selector + input + swap
- [`src/ameli_web/templates/admin/panel.html`](../src/ameli_web/templates/admin/panel.html) — admin shell con badge granular
- [`tests/test_mfa_stacked_views.py`](../tests/test_mfa_stacked_views.py) — 18 tests E2E del cierre stacked
- [`tests/test_mfa_stacked.py`](../tests/test_mfa_stacked.py) — 12 tests service layer del refactor 2026-06-04

### Conversacion completa del 2026-06-05

En orden:

1. Retomada desde `9ffce31` con import del export de la sesion anterior
   en otra maquina para confirmar el plan no documentado.
2. Diagnostico del 500 en POST `/login/` del servidor → era el proceso
   uvicorn corriendo codigo viejo. Restart + `install.sh` lo arreglo.
3. Validacion end-to-end del email MFA contra el codigo real
   (login con admin, codigo `540595`, redireccion al dashboard).
4. Identificacion del bug del profile UI (mostraba TOTP cuando admin
   tenia email) + el panel completo no era stacked.
5. Lectura del export para confirmar diseno stacked (Google/GitHub/AWS
   standard) y plan de 3 commits documentado por la sesion anterior.
6. **Commit 1**: profile UI stacked + per-method disable views/URLs/JS.
7. **Commit 2**: login verify-mfa con selector + swap method.
8. **Commit 3**: 18 tests E2E nuevos.
9. Validacion visual: email vacio en card + badge estirado → fix
   `c21724d`.
10. Validacion visual: stacking de segundo metodo + recovery screen
    vacia → fix `93ad309`.
11. Validacion end-to-end completa: stacking, selector, swap, login
    final al dashboard, admin badge `2FA TOTP+Email`.
12. Promocion del bloque a `main`.
13. Este handoff.
