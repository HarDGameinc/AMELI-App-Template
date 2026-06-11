## AMELI App Template handoff (sesion Claude, 2026-06-12, Bloque 4)

Fecha: `2026-06-12`

Continuacion de
[`CLAUDE_HANDOFF_2026-06-12_SECURITY_BLOCKS_1_2_3.md`](CLAUDE_HANDOFF_2026-06-12_SECURITY_BLOCKS_1_2_3.md).

Despues de cerrar bloques 1-3 + H6 el usuario pidio "dejemos lo mejor
posible este template lo mas seguro confiable a pruebas de errores y/o
intervencion de algun atacante" — no para agregar features sino para
consolidar la base.

Esta sesion ataca esa peticion con dos sub-bloques:

- **4A — Defense in depth chico pero acumulativo** (M5, headers
  modernos, honeypot, SMTP boot guard, banner de alertas en perfil).
- **4B — Backlog del audit + ops de H6** (N3 lockout permanente,
  admin unlock endpoint, systemd timer + doc para `verify-audit`).

### Estado general al cierre

- Repo: `HarDGameinc/AMELI-App-Template`
- Rama estable: `main` (post-promocion del dia)
- Rama de trabajo: `dev` (sincronizada con `main`)
- **539 tests pasando** (`pytest -v`)
- **0 regresiones**
- Nuevos archivos de tests: `test_security_hardening_block4.py`

### Resumen ejecutivo

| Frente | Antes (bloque 1-3) | Despues (bloque 4) |
|---|---|---|
| `/django-admin/` | Solo password + MFA al login inicial | Sudo grant explicito requerido; via panel pasa por el modal sudo |
| Headers HTTP | CSP + X-Frame + X-Content-Type + Referrer-Policy | + `Permissions-Policy` + `Cross-Origin-Opener-Policy` + `Cross-Origin-Resource-Policy` |
| Login form | Sin proteccion contra bots automatizados | Honeypot field + audit `login_bot_detected` |
| Outbound email en prod | Operador podia arrancar con backend console (no-op) | Boot guard: refuse si backend no es smtp/file o smtp sin host |
| Perfil al cargar | Sin pista de items de seguridad pendientes | Banner que lista MFA off, sin email, password >90d con CTA por item |
| Lockout por user | Temporal, atacante espera y reintenta | Permanente tras N ventanas consecutivas; admin desbloquea |
| Audit chain | Verificacion manual via CLI | Systemd timer horario + alert hook documentado |

### Bloque 4A — Defense in depth (3 commits)

| Commit | Item |
|---|---|
| `21f3d20` | M5 + headers + honeypot + SMTP guard + alerts |
| `fadb043` | CSP relajado solo en `/django-admin/*` (fix de la UI rota) |

**Detalle por item**:

#### M5 — MFA gate explicito en `/django-admin/`

El framework admin es muy poderoso y bypasea cualquier check de
business logic. Una cookie superadmin robada antes daba acceso
directo. Ahora:

- `DjangoAdminSudoGateMiddleware` intercepta cualquier path bajo
  `/django-admin/`. Si el usuario es staff pero la sesion no tiene
  sudo activo: redirige a `/admin/` con flash warning y audit
  `django_admin_blocked_no_sudo`.
- Endpoint nuevo `POST /admin/django-admin/enter/` con
  `@sudo_required`. La UI del panel cambia el viejo `<a href=django-
  admin>` por un `<button>` que postea ahi — el wrapper `requestJson`
  ya maneja el 401 `need_sudo` y abre el modal. Al confirmar, el
  endpoint responde `{ok, redirect: /django-admin/}` y el JS navega.
- Audit `django_admin_entered` cada vez que un superadmin completa el
  flow.

#### Headers HTTP modernos

`SecurityHeadersMiddleware` agrega tres headers a toda response:

- `Permissions-Policy`: turn-off explicito de camera, microphone,
  geolocation, payment, USB, accelerometer, gyroscope, magnetometer,
  el viejo interest-cohort de FLoC.
- `Cross-Origin-Opener-Policy: same-origin`: bloquea que otra
  ventana de origen distinto pueda hablar con `window.opener` de la
  app.
- `Cross-Origin-Resource-Policy: same-origin`: bloquea que otra
  pagina cargue recursos nuestros como `<img>` o `<script>` (defensa
  contra Spectre-class side-channels que necesitan cross-origin
  loading).

`setdefault`-style: si un view ya seteo un valor especifico (ej.
`/docs`) no se sobrescribe.

#### CSP relajado para `/django-admin/*`

Bug que aparecio al verificar M5: la CSP estricta sin `'unsafe-
inline'` rompe los inline scripts del admin nativo (theme switcher,
autocompletes, sortables). Como `/django-admin/` ya esta gated por
sudo + MFA + audit, la relajacion controlada es el trade-off correcto.

- `_django_admin_csp()` retorna una CSP con `'unsafe-inline'` solo en
  esa path.
- El middleware elige policy por prefix; el resto del sitio sigue con
  nonces.

#### Login honeypot

- Template inyecta un input `name="hp_company"` off-screen via inline
  style + `aria-hidden="true"` + `tabindex="-1"` + `autocomplete="off"`.
- `TemplateLoginView.post()` si recibe valor no-vacio: responde con el
  mismo mensaje generico de wrong-credentials (no revela que detectamos
  el bot) y audita `login_bot_detected` con `ip` + `user_agent`.

#### SMTP boot guard

Antes el deploy podia arrancar fuera de dev con `email.backend =
console` y los flows de password reset + MFA email fallaban
silenciosamente. Ahora `settings.py` refuse:

```python
if not _IS_DEV_ENV:
    if email_backend not in {"smtp", "file"}:
        raise RuntimeError("email.backend must be 'smtp' or 'file'...")
    if email_backend == "smtp" and not EMAIL_HOST:
        raise RuntimeError("email.backend is 'smtp' but email.host is empty...")
```

#### Banner de seguridad en `/profile/`

`profile_view` ahora pasa `security_alerts: list[dict]` al template.
La lista se computa por `_security_alerts_for(user)`:

- **2FA no activado**: si `not user.mfa_enabled`.
- **Sin email registrado**: si `not user.email` (sin email no hay path
  de recovery de password).
- **Tu contrasena tiene N dias**: si la edad excede
  `PROFILE_PASSWORD_MAX_AGE_DAYS` (default 90, configurable).

Cada item tiene `icon`, `title`, `detail` y un boton que dispara
`data-tab-trigger="profile-tab-security"` para llevar al user al fix.

### Bloque 4B — N3 + ops H6 (1 commit)

| Commit | Item |
|---|---|
| `5286ed1` | N3 lockout permanente + admin unlock + verify-audit timer |

#### N3 — Lockout permanente

`User` gana dos campos:

- `locked_at: DateTimeField(null=True)` — marca de cuando se aplico el
  lock duro.
- `locked_reason: CharField(64)` — texto operativo
  (`"throttle:3_consecutive_lockouts"`).

Migration `accounts/0008_user_locked_at_user_locked_reason`.

Logica:

- `_consecutive_lockouts_for(username, window)` consulta el audit log
  (no el throttle counter, que se resetea) y cuenta los
  `login_locked_out` con timestamp en ventanas distintas dentro de un
  rango. Una ventana = `>= window * 0.5` de gap entre eventos.
- `maybe_permanently_lock(username)` se llama desde la login view
  justo despues de recordear `login_locked_out`. Si los consecutivos
  >= `LOCKOUT_PERMANENT_CONSECUTIVE` (default 3), set `locked_at = now()`
  y audita `user_locked_permanently`.
- `check_login_throttle` ahora chequea PRIMERO si el usuario tiene
  `locked_at` set y raise `AccountLocked` con mensaje hard-lock
  (`retry_after=0` — no es temporal).
- `admin_unlock_user(actor_username, username)`: clear `locked_at`,
  audit `user_unlocked_by_admin`. Endpoint
  `POST /admin/users/<username>/unlock` sudo-gated.

#### Systemd timer para `verify-audit`

Dos templates nuevos en `deploy/systemd/`:

- `ameli-app-verify-audit.service`: oneshot que corre
  `ameli-app verify-audit`. Hardening estandar (`NoNewPrivileges`,
  `ProtectSystem=full`, `ReadOnlyPaths=APP_DIR`).
- `ameli-app-verify-audit.timer`: `OnCalendar=*-*-* *:07:00` (horario,
  minuto 7 para no chocar con otros timers).

`scripts/install.sh` ya renderiza todos los .service/.timer del
directorio asi que la nueva pareja se instala automaticamente en el
proximo deploy.

#### Doc en `OPERATIONS.md`

Nueva seccion "Audit chain verification (H6)" con:

- Como activar (`AMELI_APP_AUDIT_HMAC_KEY`).
- Comando manual + flags de range.
- Como agendar el timer + hook de alerta (`OnFailure=`).
- Recipe (con caveats) para rotar la key.

### Bloque 4C — Bug fix de static + backlog post-bloque (5 commits)

Despues del 4B aparecieron tres situaciones a resolver: un bug visual
en el django admin nativo, y cuatro items del backlog que el usuario
pidio cerrar para "dejar el template lo mas solido posible".

| Commit | Item |
|---|---|
| `ce55160` | Bug fix: `/static/` ahora usa el finder pipeline (admin assets cargan) |
| `144792d` | Backlog #1: UI unlock en `/admin/` |
| `34a972d` | Backlog #5 + #7: Argon2 tuning + timing pad forgot-password |
| `f6a601a` | Backlog #4: Suite e2e de seguridad (14 tests) |

#### Bug fix `/static/` finder pipeline

Verificacion del fix CSP de django-admin destapo un segundo problema:
los assets del admin nativo (`/static/admin/css/*.css`, `/static/admin/
js/*.js`) devolvian 404 HTML, y `X-Content-Type-Options: nosniff`
bloqueaba el render porque el MIME no matcheaba. La pagina del django
admin se veia "rota" — sin estilos, sin theme switcher.

Causa: `django.views.static.serve` solo mira `STATICFILES_DIRS[0]`. El
admin nativo trae sus assets en `django/contrib/admin/static/admin/`,
que ese serve no consulta.

Fix: `_serve_static` ahora usa `staticfiles.finders.find(path)` que
recorre tanto `STATICFILES_DIRS` como cada app instalada. Asi el admin
resuelve sin necesidad de `collectstatic`. Production con Caddy/nginx
delante no toca este handler.

3 tests pinean el bug-fix: admin css resuelve, app.css del proyecto
sigue, paths inexistentes 404.

#### Backlog #1 — UI unlock en `/admin/`

El backend de N3 ya estaba (`POST /admin/users/<username>/unlock`),
pero faltaba la UI. Cambios:

- `serialize_user` ahora expone `locked`, `locked_at`,
  `display_locked_at`, `locked_reason`.
- `_users_panel.html` muestra badge **"Bloqueado"** (rojo) junto a los
  otros badges del user, con `title=` apuntando al `locked_reason`.
- Boton **"Desbloquear"** condicional, solo aparece cuando
  `user_item.locked` es true. Reusa el `requestJson` wrapper asi que
  abre el modal sudo automaticamente si el grace expiro.
- 4 tests pinean: serializer, render del badge, render del boton solo
  en locked, endpoint clearing the flag.

#### Backlog #5 — Argon2 tuning configurable

`ConfigurableArgon2Hasher` subclasses el bundled de Django y lee
`time_cost` / `memory_cost` / `parallelism` desde settings, alimentados
desde env vars `AMELI_APP_ARGON2_*`. Defaults igualan los de Django
(no cambia nada para deploys actuales).

El operador puede bumpear cualquier factor en hardware mas potente
sin tocar codigo; Django re-encodea cada hash en el siguiente login
exitoso (`UPDATE_LAST_LOGIN_ENCODING`), asi el bump aplica
opportunisticamente sin downtime.

3 tests: settings propagate, defaults fallback, password hash sigue
saliendo argon2.

#### Backlog #7 — Timing pad forgot-password

Antes el response body era identico para found vs not-found pero el
flow de SMTP tomaba mas tiempo en el found case, dejando un canal de
enumeracion via wall-clock.

`forgot_password_view` ahora mide el tiempo total y holda hasta
`FORGOT_PASSWORD_MIN_RESPONSE_MS` (default 1000) + jitter `~80ms`.
Verificado en server dev: tanto `identifier=admin` como
`identifier=nada` retornan en ~1.03s con la diferencia bien por
debajo del umbral medible offsite.

`FORGOT_PASSWORD_MIN_RESPONSE_MS=0` desactiva el pad (para tests que
necesitan medir velocidad).

2 tests: pad enforces the floor, pad respeta el disable a 0.

#### Backlog #4 — Suite e2e de seguridad (14 tests)

Donde los tests por-bloque pinean una feature aislada, esta suite
camina escenarios de atacante completos y pinea invariantes
observables — sobrevive a refactors porque no esta atada a la
implementacion.

Tests del archivo `tests/test_security_e2e.py`:

1. **Headers**: CSP + X-Frame + nosniff + Referrer + Permissions +
   COOP + CORP en toda response.
2. **CSP nonce**: script-src tiene nonce-, no tiene 'unsafe-inline'.
3. **Session cookie**: HttpOnly + SameSite=Lax post-login.
4. **CSRF cookie**: HttpOnly + SameSite=Lax.
5. **CSRF middleware**: POST sin token = 403.
6. **Session rotation**: session_key cambia post-login (anti-fixation).
7. **Honeypot**: bot con hp_company filled = wrong-credentials +
   audit `login_bot_detected`.
8. **N3 lockout**: user locked no autentica.
9. **Sudo escape**: cambio de password evapora el sudo de la sesion
   (joya de la corona del diseño sudo).
10. **`/django-admin/` gate**: staff sin sudo = redirect a `/admin/`.
11. **`must_change_password` trap**: flag intercepta `/admin/`,
    preferences, MFA start, session revoke.
12. **Anti-enumeration**: forgot-password body identico para found vs
    not-found (descontando el identifier echo).
13. **Audit chain**: trafico normal = OK, tampering = falla con
    `broken_id` correcto.
14. **Health/metrics allowlist**: off-list = 403, forwarded-for
    correcta = 200.

La suite corre en ~2 segundos y queda como **smoke test de seguridad
post-deploy** — green = invariantes preservadas.

### Numeros del bloque

- **8 commits promocionados a `main`** (3 del 4A/4B + 5 del 4C)
- **565 tests pasando** (525 al inicio del bloque -> +40 nuevos
  tests netos)
- 2 archivos de tests nuevos
  (`test_security_hardening_block4.py` + `test_security_e2e.py`)
- 1 migracion nueva: `accounts/0008_user_locked_at_user_locked_reason`
- 0 deps Python nuevas
- 2 systemd units nuevas
- 1 modulo nuevo: `accounts/hashers.py`
- ~1500 lineas netas agregadas

### Decisiones tomadas (no re-discutirlas)

- **CSP relajada solo en `/django-admin/*`**: el admin nativo usa
  inline scripts del framework que no podemos nonce-stamp. Como ya
  esta gated por sudo + MFA + audit y solo lo usa el operador, la
  relajacion ahi es el trade-off correcto.
- **Locked-at NO es time-based**: una vez puesto, solo un admin lo
  saca. Un sustained brute-force no puede esperar a que pase y
  reintentar.
- **Threshold default 3 ventanas consecutivas**: un user real que
  realmente olvido su pass corre contra una o dos ventanas como
  maximo; tres seguidas es senial fuerte de ataque sostenido.
- **Honeypot field name `hp_company`**: lo bastante banal para que
  un bot lo intente llenar sin sospechar. No esta en la lista de
  campos comunes de password manager.
- **SMTP boot guard incluye `file` como valido**: algunos deploys
  internos quieren un outbox local en disco para review. No es
  console (que descarta a stdout) y permite el flow.
- **Permissions-Policy con `interest-cohort=()`**: el header anti-
  FLoC ya esta deprecated en Chrome pero el cost de incluirlo es
  cero y protege contra implementaciones legacy.

### Snapshot al cierre — superficie de seguridad consolidada

| Frente | Cobertura |
|---|---|
| Auth / login | Argon2 + throttle atomico por IP/user + lockout temporal + **honeypot anti-bot** |
| **Lockout** | Temporal por throttle + **permanente tras 3 ventanas; admin unlock** |
| `/django-admin/` | **Gate sudo via middleware + CSP relajada solo ahi** |
| Force change password | Middleware + modal bloqueante + redirect post-login |
| Sesion | HttpOnly + Secure + SameSite + idle renewal + cycle_key on MFA + disabled-user kick + revoke on password change |
| Sudo-mode admin | Re-auth password + MFA, grace 5 min, revoke en logout/pw-change |
| MFA | TOTP + email + recovery codes, throttle atomico, notif al titular en admin disable |
| Password change forgot | Throttle atomico por IP, mensaje en espanol, audit pre-SMTP |
| Cambio de email | Double-opt-in con confirm + alert + cancel link |
| HIBP password check | Opcional via toggle, k-anonymity |
| Audit log | Actor consistente + HMAC chain + **systemd timer horario con alert hook** |
| **Profile UX** | **Banner de alertas para MFA off, sin email, password viejo** |
| Webhooks | Removidos del Template |
| API tokens | Removidos del Template |
| Avatares | Format whitelist + pixel cap + byte cap |
| Static/media | DEBUG-gated + media auth gate |
| Headers / CSP | Nonces per-request en script-src (+ relax en `/django-admin/*`) |
| **Browser features off** | **Permissions-Policy + COOP/CORP** |
| /docs /redoc | Pin version + SRI opcional + CSP per-page con nonce + jsdelivr |
| /health /metrics | Allowlist IP opcional |
| Config | Boot guards (SECRET_KEY, ALLOWED_HOSTS, DEBUG, TRUSTED_PROXIES, **email.backend**) |

### Proximos bloques abiertos

Items 1, 4, 5 y 7 quedaron resueltos en el 4C (ver arriba). Lo que
queda:

| # | Item | Tipo | Tamaño |
|---|---|---|---|
| 6 | Rotacion de `AUDIT_HMAC_KEY` con re-anchor (CLI `rotate-audit-key`) | Seguridad operativa | Medio |
| 3 | Retry + queue para emails fallidos | Operativo | Medio |
| 2 | Selector de idioma en header (i18n loop) | UX | Chico |

### Orden recomendado para retomar

1. Resync local + servidor al hash `5286ed1`
2. Aplicar migracion:
   ```bash
   .venv/bin/ameli-app shell -c "from django.core.management import call_command; call_command('migrate')"
   ```
3. Si vas a deploy de prod, verificar que el env tenga:
   - `AMELI_APP_EMAIL_BACKEND=smtp`
   - `AMELI_APP_EMAIL_HOST=<server>`
   - `AMELI_APP_AUDIT_HMAC_KEY=<secret>` (opcional pero recomendado)
   - `AMELI_APP_TRUSTED_PROXIES=...` (ya obligatorio desde bloque 1)
4. Activar el timer de verify-audit:
   ```bash
   systemctl daemon-reload
   systemctl enable --now ameli-app-template-prod-verify-audit.timer
   ```
5. Si seguis: UI para desbloquear users en `/admin/` (boton en cada user
   con `locked_at`). El endpoint ya existe.

### Comandos utiles de continuidad

Verificar la chain manualmente:

```bash
.venv/bin/ameli-app verify-audit
.venv/bin/ameli-app verify-audit --from-id 1000 --to-id 2000
```

Probar el lockout permanente (cuidado, es destructivo):

```bash
# Forzar el flag
.venv/bin/ameli-app shell -c "
from ameli_web.accounts.models import User
from django.utils import timezone
u = User.objects.get(username='tester')
u.locked_at = timezone.now()
u.locked_reason = 'manual_test'
u.save()
"
# Intentar login (debe fallar con el mensaje hard-lock)
curl -i http://10.100.100.16:18080/login/ -d 'username=tester&password=Whatever12!?'
# Desbloquear
.venv/bin/ameli-app shell -c "
from ameli_web.accounts.services import admin_unlock_user
print(admin_unlock_user(actor_username='admin', username='tester'))
"
```

Probar el honeypot:

```bash
curl -i http://10.100.100.16:18080/login/ \
  -H 'Cookie: csrftoken=<token>' \
  -d 'csrfmiddlewaretoken=<token>&username=admin&password=AdminPass!12?Secure&hp_company=AcmeCorp'
# Esperado: misma respuesta que con password mal + audit row login_bot_detected
```

Tests:

```bash
DATABASE_URL= APP_ENV=dev .venv/bin/pytest tests/test_security_hardening_block4.py -v
```

### Archivos clave del cierre

- [`src/ameli_web/accounts/middleware.py`](../src/ameli_web/accounts/middleware.py) — `DjangoAdminSudoGateMiddleware`, headers modernos, CSP por-path
- [`src/ameli_web/accounts/services.py`](../src/ameli_web/accounts/services.py) — `maybe_permanently_lock`, `admin_unlock_user`, `check_login_throttle` chequea `locked_at`
- [`src/ameli_web/accounts/views.py`](../src/ameli_web/accounts/views.py) — `_security_alerts_for`, honeypot en `TemplateLoginView.post`, `maybe_permanently_lock` despues del lockout
- [`src/ameli_web/accounts/models.py`](../src/ameli_web/accounts/models.py) — `User.locked_at`, `User.locked_reason`
- [`src/ameli_web/admin_views.py`](../src/ameli_web/admin_views.py) — `admin_django_admin_enter`, `admin_unlock_user`
- [`src/ameli_web/settings.py`](../src/ameli_web/settings.py) — boot guard de SMTP, registro del middleware
- [`src/ameli_web/templates/accounts/login.html`](../src/ameli_web/templates/accounts/login.html) — honeypot field
- [`src/ameli_web/templates/accounts/profile.html`](../src/ameli_web/templates/accounts/profile.html) — banner `Alertas de seguridad`
- [`src/ameli_web/templates/admin/panel.html`](../src/ameli_web/templates/admin/panel.html) — boton `Admin nativo Django` con sudo flow
- [`deploy/systemd/ameli-app-verify-audit.service`](../deploy/systemd/ameli-app-verify-audit.service) + `.timer`
- [`docs/OPERATIONS.md`](OPERATIONS.md) — seccion "Audit chain verification (H6)"
- [`tests/test_security_hardening_block4.py`](../tests/test_security_hardening_block4.py) — 18 tests
