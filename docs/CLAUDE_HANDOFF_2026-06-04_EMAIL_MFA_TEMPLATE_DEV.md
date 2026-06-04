## AMELI App Template handoff — Email MFA block en progreso (2026-06-04)

Fecha: `2026-06-04` (continuacion)

Tercer handoff del mismo dia. Sigue al
[`CLAUDE_HANDOFF_2026-06-04_TEMPLATE_DEV.md`](CLAUDE_HANDOFF_2026-06-04_TEMPLATE_DEV.md)
que cerro los 3 bloques originales del plan (E2E dashboard + MFA TOTP +
email password reset). Despues de ese cierre el usuario propuso un
bloque adicional: **MFA por email** (alternativa a TOTP para usuarios
que no quieran instalar una app de autenticacion). El commit 1/5 del
bloque ya esta en `dev` y verificado en el servidor.

### Estado general al cierre de esta sesion

- Repo: `HarDGameinc/AMELI-App-Template`
- Rama estable: `main` (`26fb007`, mismo del cierre anterior)
- Rama de trabajo: `dev` (`a4b4e54`, **NO promocionada todavia**)
- Servidor Debian: `/opt/ameli-app-template-dev`, en `a4b4e54` (post `install.sh`)
- **139 tests pasando** (`pytest -v`)
- **0 regresiones**
- Migracion `0004_mfa_email` aplicada limpio con backfill de
  `mfa_method='totp'` para usuarios que ya tenian MFA activo

### Decisiones tomadas (no re-discutirlas)

- **Coexistencia TOTP / email**: mutuamente exclusivos siguiendo
  estandar industrial. El user elige UN metodo al enrolarse.
  `User.mfa_method` enum `''` / `'totp'` / `'email'`.
- **TTL del code email**: 10 minutos
  (`mfa.EMAIL_CODE_TTL_SECONDS = 600`)
- **Rate limit**: 1 code por minuto + 5 por hora por user; pedir un
  code nuevo invalida los anteriores no usados
- **Recovery codes**: 10 codes generados al confirmar enrollment,
  funcionan con cualquier metodo
- **Mutual exclusivity**: ambos `start_mfa_enrollment` y
  `start_mfa_email_enrollment` rechazan si `mfa_enabled=True`, y
  cada uno limpia el state del otro metodo al arrancar

### Commit 1/5 ya en `dev` (`a4b4e54`)

`add email-based mfa model, helpers and service layer`

Cubre:

**Modelo y migracion**
- `User.mfa_method` con choices `(("totp", "App de autenticacion"), ("email", "Email"))`
- `MFAEmailChallenge(user FK, code_hash CharField(128), created_at, expires_at, used_at)`
- Migracion `0004_mfa_email.py` con `RunPython` que setea
  `mfa_method='totp'` para todo user con `mfa_enabled=True` previo

**Helpers en `accounts/mfa.py`**
- `generate_email_code()` -> 6 digitos zero-padded
- `hash_email_code(code)` -> SHA-256 hex de los digitos
- `email_codes_match(stored, candidate)` -> `hmac.compare_digest`
- Constantes: `EMAIL_CODE_LENGTH=6`, `EMAIL_CODE_TTL_SECONDS=600`,
  `EMAIL_CODE_RESEND_INTERVAL_SECONDS=60`,
  `EMAIL_CODE_HOURLY_LIMIT=5`

**Services en `accounts/services.py`**
- `_check_email_mfa_rate_limit(user)` -> raises si excede limites
- `_send_mfa_email_code(user, code)` -> reusa `_PasswordResetEmail`
  para 7bit safety
- `_create_and_send_email_challenge(user)` -> burns previos, crea uno
  nuevo, dispara email
- `consume_email_mfa_code(user, candidate)` -> match constant-time,
  marca used
- `start_mfa_email_enrollment(actor_username)` -> chequea email + no
  enabled, limpia TOTP pending, manda code
- `confirm_mfa_email_enrollment(actor_username, code)` -> set
  enabled + method='email' + 10 recovery codes
- `send_mfa_email_login_code(user)` -> emite durante login (require
  method='email')
- Updates a `start_mfa_enrollment` (TOTP) -> limpia email challenges
- Updates a `confirm_mfa_enrollment` (TOTP) -> set `mfa_method='totp'`
  y limpia challenges
- Updates a `disable_mfa_for_self` y `admin_disable_mfa_for_user` ->
  limpian `mfa_method` y challenges
- `serialize_mfa_status` ahora retorna `{enabled, pending_enrollment,
  required_by_admin, recovery_codes_remaining, method, has_email}`

**Template**
- `accounts/mfa_email_code.txt` — body plain text ASCII

**Tests** (22 en `tests/test_mfa_email_service.py`):
- helpers puros
- enrollment lifecycle (con / sin email, ya enabled, burn previos, clear TOTP secret)
- confirm con / sin valid code
- consume (used / expired / wrong format)
- rate limit (1 min + 5/hora)
- send durante login require method
- disable self / admin limpian method y challenges
- serialize_mfa_status expone method correctamente

### Lo que falta (4 commits)

#### Commit 2/5: profile method choice + email enrollment UI

**Backend (views.py)**
Agregar 2 nuevas views ademas del existente `mfa_start_view`:
```python
@login_required
@require_POST
def mfa_email_start_view(request: HttpRequest) -> JsonResponse:
    try:
        result = start_mfa_email_enrollment(request.user.username)
    except ValueError as exc:
        return _json_error(str(exc))
    return JsonResponse(result)


@login_required
@require_POST
def mfa_email_confirm_view(request: HttpRequest) -> JsonResponse:
    try:
        payload = _json_body(request)
    except ValueError as exc:
        return _json_error(str(exc))
    code = str(payload.get("code") or "").strip()
    try:
        result = confirm_mfa_email_enrollment(request.user.username, code)
    except ValueError as exc:
        record_audit(
            "mfa_email_enrollment_failed",
            actor=request.user,
            target_username=request.user.username,
            payload={"reason": str(exc)},
        )
        return _json_error(str(exc))
    return JsonResponse(result)
```

**URLs (accounts/urls.py)**
```python
path("profile/mfa/email/start/", views.mfa_email_start_view, name="profile-mfa-email-start"),
path("profile/mfa/email/start", views.mfa_email_start_view),
path("profile/mfa/email/confirm/", views.mfa_email_confirm_view, name="profile-mfa-email-confirm"),
path("profile/mfa/email/confirm", views.mfa_email_confirm_view),
```

**Template (`accounts/profile.html`)**
El panel actual de 2FA tiene 4 secciones (disabled/pending/recovery/enabled). 
Reemplazar la seccion `disabled` con una que elija metodo:

```html
<div id="profile-mfa-disabled" class="form-card"{% if mfa_status.enabled %} hidden{% endif %}>
  <div class="profile-card">
    <div class="profile-row">
      <span class="metric-label">Estado actual</span>
      <span class="profile-note warn-text">Inactivo</span>
    </div>
    {% if mfa_status.required_by_admin %}
    <div class="profile-row">
      <span class="metric-label">Politica</span>
      <span class="profile-note warn-text">Requerido por el administrador</span>
    </div>
    {% endif %}
  </div>
  <p class="muted panel-copy" style="margin-top:12px;">Elegi el metodo de verificacion en segundo paso del ingreso:</p>
  <div class="form-grid-split" style="margin-top:8px;">
    <article class="form-card">
      <div class="form-card-head">
        <h3 class="form-card-title">App de autenticacion</h3>
        <p class="muted panel-copy">Google Authenticator, Authy, 1Password u otra. Codigo de 6 digitos cada 30s.</p>
      </div>
      <div class="modal-actions-row">
        <button class="primary" id="profile-mfa-activate" type="button">
          <span class="material-symbols-rounded icon-glyph" aria-hidden="true">smartphone</span>
          <span>Activar con app</span>
        </button>
      </div>
    </article>
    <article class="form-card">
      <div class="form-card-head">
        <h3 class="form-card-title">Email</h3>
        <p class="muted panel-copy">Te mandamos un codigo de 6 digitos a {% if mfa_status.has_email %}<strong>{{ request.user.email }}</strong>{% else %}<span class="warn-text">tu email registrado</span>{% endif %} cada vez que inicies sesion.</p>
      </div>
      <div class="modal-actions-row">
        <button class="primary" id="profile-mfa-email-activate" type="button"{% if not mfa_status.has_email %} disabled{% endif %}>
          <span class="material-symbols-rounded icon-glyph" aria-hidden="true">mail</span>
          <span>Activar con email</span>
        </button>
      </div>
      {% if not mfa_status.has_email %}
      <p class="muted" style="margin-top:8px;">Sin email registrado. Pedile al administrador que te asigne uno antes de activar.</p>
      {% endif %}
    </article>
  </div>
  <p class="muted" id="profile-mfa-activate-feedback"></p>
</div>
```

Agregar nueva seccion `profile-mfa-email-pending` con form:
```html
<div id="profile-mfa-email-pending" class="form-card" hidden>
  <p class="muted panel-copy">Te enviamos un codigo de 6 digitos a tu email. Tipealo abajo para confirmar la activacion.</p>
  <div class="modal-form-row">
    <label class="modal-form-label" for="profile-mfa-email-code">Codigo de la app</label>
    <input id="profile-mfa-email-code" class="modal-input" type="text" inputmode="numeric" autocomplete="one-time-code" maxlength="7" placeholder="123 456">
  </div>
  <div class="modal-actions-row">
    <button type="button" class="icon-action" id="profile-mfa-email-cancel">Cancelar</button>
    <button class="primary" type="button" id="profile-mfa-email-verify">Verificar y activar</button>
  </div>
  <p class="muted" id="profile-mfa-email-verify-feedback"></p>
</div>
```

Y al script agregarle:
```js
const emailActivateBtn = document.getElementById("profile-mfa-email-activate");
const emailVerifyBtn = document.getElementById("profile-mfa-email-verify");
const emailCancelBtn = document.getElementById("profile-mfa-email-cancel");
const emailCodeInput = document.getElementById("profile-mfa-email-code");
const emailVerifyFeedback = document.getElementById("profile-mfa-email-verify-feedback");

emailActivateBtn?.addEventListener("click", async () => {
  emailActivateBtn.disabled = true;
  if (activateFeedback) activateFeedback.textContent = "Enviando codigo...";
  try {
    await postJson("{% url 'accounts:profile-mfa-email-start' %}");
    showMfaSection("emailPending");  // need to add to mfaSections map
    emailCodeInput?.focus();
  } catch (error) {
    if (activateFeedback) activateFeedback.textContent = error instanceof Error ? error.message : "Error inesperado.";
  } finally {
    emailActivateBtn.disabled = false;
  }
});

emailVerifyBtn?.addEventListener("click", async () => {
  const code = String(emailCodeInput?.value || "").trim();
  if (!code) { ... }
  try {
    const data = await postJson("{% url 'accounts:profile-mfa-email-confirm' %}", { code });
    // Show recovery codes (same UX as TOTP)
    if (recoveryList && Array.isArray(data.recovery_codes)) {
      recoveryList.innerHTML = "";
      data.recovery_codes.forEach((c) => {
        const li = document.createElement("li");
        li.textContent = c;
        recoveryList.appendChild(li);
      });
    }
    showMfaSection("recovery");
  } catch (error) { ... }
});

emailCancelBtn?.addEventListener("click", () => window.location.reload());
```

Y agregar `emailPending: document.getElementById("profile-mfa-email-pending")` al `mfaSections` map.

Tambien para el estado `enabled`, mostrar el metodo activo:
```html
<div class="profile-row">
  <span class="metric-label">Metodo</span>
  <span class="profile-note">{% if mfa_status.method == "email" %}Email ({{ request.user.email }}){% else %}App de autenticacion{% endif %}</span>
</div>
```

#### Commit 3/5: login verify-mfa adapts to method + resend

**View update (`verify_mfa_view` en `accounts/views.py`)**

Cuando el user esta enrolado con email, en GET autogenerar code (si no hay uno reciente) y pasar el metodo al contexto. En POST aceptar code email O recovery code:

```python
@require_http_methods(["GET", "POST"])
def verify_mfa_view(request: HttpRequest) -> HttpResponse:
    if request.user.is_authenticated:
        _clear_pending_mfa(request)
        return redirect("/profile/")

    user = _pending_mfa_user(request)
    if user is None:
        _clear_pending_mfa(request)
        messages.error(request, "La sesion de ingreso expiro. Vuelve a tipear usuario y contrasena.")
        return redirect("accounts:login")

    next_url = request.session.get(PENDING_MFA_NEXT_KEY) or "/profile/"
    method = user.mfa_method or "totp"
    context = {
        "version": __version__,
        "next_url": next_url,
        "pending_username": user.username,
        "method": method,
        "email_hint": user.email if method == "email" else "",
    }

    if request.method == "GET":
        # For email method, ensure there is a pending challenge.
        if method == "email":
            has_pending = MFAEmailChallenge.objects.filter(
                user=user, used_at__isnull=True, expires_at__gt=timezone.now()
            ).exists()
            if not has_pending:
                try:
                    send_mfa_email_login_code(user)
                except ValueError:
                    pass  # rate limit; user can hit "Reenviar" later
        return render(request, "accounts/verify_mfa.html", context)

    candidate = str(request.POST.get("code") or "").strip()
    if not candidate:
        context["form_error"] = "Tipea el codigo o un codigo de recuperacion."
        return render(request, "accounts/verify_mfa.html", context, status=400)

    digits_only = candidate.replace(" ", "")
    success = False
    auth_mode = method

    if method == "totp" and digits_only.isdigit() and len(digits_only) == 6:
        success = mfa_lib.verify_totp(user.mfa_secret, digits_only)
    elif method == "email" and digits_only.isdigit() and len(digits_only) == 6:
        success = consume_email_mfa_code(user, digits_only)

    if not success:
        if consume_recovery_code(user, candidate):
            success = True
            auth_mode = "recovery"

    if not success:
        record_audit(
            "login_mfa_failed",
            actor=user,
            target_username=user.username,
            payload={"reason": "invalid-code", "method": method},
        )
        context["form_error"] = "Codigo invalido. Intenta de nuevo."
        return render(request, "accounts/verify_mfa.html", context, status=400)

    _clear_pending_mfa(request)
    auth_login(request, user, backend="django.contrib.auth.backends.ModelBackend")
    record_audit("login_mfa_success", actor=user, target_username=user.username,
                 payload={"auth_mode": auth_mode})
    return redirect(next_url)
```

**Nueva view: resend**
```python
@require_POST
def verify_mfa_resend_view(request: HttpRequest) -> HttpResponse:
    user = _pending_mfa_user(request)
    if user is None:
        return _json_error("session expired", status=401)
    if user.mfa_method != "email":
        return _json_error("resend only available for email mfa")
    try:
        result = send_mfa_email_login_code(user)
    except ValueError as exc:
        return _json_error(str(exc))
    return JsonResponse(result)
```

**URL:**
```python
path("login/verify-mfa/resend/", views.verify_mfa_resend_view, name="verify-mfa-resend"),
path("login/verify-mfa/resend", views.verify_mfa_resend_view),
```

**Template (`verify_mfa.html`)**
Adaptar segun `method`:
- Si `method == 'email'`: copy menciona "te enviamos un codigo a tu email", agrega boton "Reenviar codigo" que hace POST via fetch
- Si `method == 'totp'`: copy actual

#### Commit 4/5: admin badge muestra metodo

En `admin/panel.html` cambiar el badge de 2FA:
```html
{% if user_item.mfa_enabled %}
{% if user_item.mfa_method == "email" %}
<span class="session-state-badge active">2FA Email</span>
{% else %}
<span class="session-state-badge active">2FA TOTP</span>
{% endif %}
{% elif user_item.mfa_required %}
<span class="session-state-badge warning">2FA requerido</span>
{% else %}
<span class="session-state-badge neutral">2FA off</span>
{% endif %}
```

Y `serialize_user` en `services.py` ya expone `mfa_enabled` y `mfa_required` — agregar `mfa_method`:
```python
"mfa_method": user.mfa_method or ("totp" if user.mfa_enabled else ""),
```

#### Commit 5/5: E2E tests

Crear `tests/test_mfa_email_views.py`:
- POST /profile/mfa/email/start con email enrolado actualiza pending + envia email
- POST /profile/mfa/email/start sin email rechaza
- POST /profile/mfa/email/confirm con code OK habilita + retorna recovery codes
- POST /login/ con user email-enrolled redirige a verify-mfa
- GET /login/verify-mfa/ con email user dispara email
- POST /login/verify-mfa/ con code OK loguea
- POST /login/verify-mfa/resend/ con email user manda nuevo code
- POST /login/verify-mfa/resend/ rate limited devuelve 400

Y agregar test al `test_admin_mfa.py` que confirma el badge.

### Promocion del bloque

Cuando termine commit 5, mismo flujo de siempre:

```bash
git checkout main
git pull --ff-only origin main
git cherry-pick a4b4e54 <commits-2-3-4-5>
git push origin main
git checkout dev
git reset --hard main
git push --force-with-lease origin dev
```

### Snapshot acumulativo del Template al cierre

**Total commits hoy**: 16 en `main` (sin contar este checkpoint en dev)
- Empezamos el dia con 39 tests
- Cierre `main`: 117 tests
- Cierre `dev` (con commit 1 email MFA): 139 tests

Nuevos archivos creados hoy:
- `tests/test_dashboard.py`
- `tests/test_account_guards.py`
- `tests/test_mfa_helpers.py`, `tests/test_mfa_service.py`,
  `tests/test_login_mfa.py`, `tests/test_admin_mfa.py`
- `tests/test_password_reset_service.py`,
  `tests/test_password_reset_views.py`
- `tests/test_mfa_email_service.py` (commit 1 email MFA)
- `src/ameli_web/accounts/mfa.py`
- `src/ameli_web/accounts/migrations/0003_mfa.py`
- `src/ameli_web/accounts/migrations/0004_mfa_email.py`
- `src/ameli_web/templates/accounts/verify_mfa.html`
- `src/ameli_web/templates/accounts/forgot_password.html`
- `src/ameli_web/templates/accounts/reset_password.html`
- `src/ameli_web/templates/accounts/password_reset_email.txt`
- `src/ameli_web/templates/accounts/mfa_email_code.txt`

### Orden recomendado para retomar

1. **Resync local + servidor** al hash `a4b4e54` (en dev).
2. **Commit 2/5 email MFA**: profile UI con method choice. Verificacion
   visual: enrolar admin (que ya tiene email seteado) con metodo email,
   confirmar que llega el code, completar enrollment.
3. **Commit 3/5 email MFA**: login flow. Verificacion: logout, login
   con admin email-enrolled, ver verify-mfa con copy adaptado y
   boton "Reenviar codigo".
4. **Commit 4/5 email MFA**: admin badge.
5. **Commit 5/5 email MFA**: E2E tests.
6. **Promocion del bloque** a main.
7. **Pulir Sesiones tab del profile** (chico, alta cosmetic).
8. **Primera app real heredada** (estrategico).

### Comandos utiles de continuidad

Local:

```bash
git log --oneline --decorate -10
git status --short --branch
```

Servidor (cambios de Python + migraciones):

```bash
cd /opt/ameli-app-template-dev
git fetch origin
git reset --hard origin/dev
APP_ENV=dev APP_SLUG=ameli-app-template APP_PACKAGE=ameli_app bash scripts/install.sh
```

Servidor (templates / JS / CSS solamente):

```bash
cd /opt/ameli-app-template-dev
git fetch origin
git reset --hard origin/dev
systemctl restart ameli-app-template-dev-api.service
```

Tests con DB en SQLite:

```bash
DATABASE_URL= .venv/bin/pytest -v
```

Smoke test directo a Django (env file con caracteres especiales,
usa nuestro propio loader que tolera parens / hashes):

```bash
AMELI_APP_ENV_FILE=/etc/ameli-app-template-dev/app.env \
DJANGO_SETTINGS_MODULE=ameli_web.settings \
.venv/bin/python -c "
import django; django.setup()
from django.contrib.auth import get_user_model
U = get_user_model()
for u in U.objects.all():
    print(u.username, u.email, u.mfa_enabled, u.mfa_method)
"
```

### Archivos clave para el commit 2 en adelante

- [`src/ameli_web/accounts/services.py`](../src/ameli_web/accounts/services.py)
  — tiene todo el dominio incluyendo las nuevas funciones email
- [`src/ameli_web/accounts/views.py`](../src/ameli_web/accounts/views.py)
  — donde agregar `mfa_email_start_view`, `mfa_email_confirm_view`,
  `verify_mfa_resend_view` y actualizar `verify_mfa_view`
- [`src/ameli_web/accounts/urls.py`](../src/ameli_web/accounts/urls.py)
  — agregar 3 URLs nuevas
- [`src/ameli_web/templates/accounts/profile.html`](../src/ameli_web/templates/accounts/profile.html)
  — panel 2FA con method choice (commit 2)
- [`src/ameli_web/templates/accounts/verify_mfa.html`](../src/ameli_web/templates/accounts/verify_mfa.html)
  — adaptar segun method (commit 3)
- [`src/ameli_web/templates/admin/panel.html`](../src/ameli_web/templates/admin/panel.html)
  — badge segun metodo (commit 4)

### Conversacion completa de los 3 handoffs del 2026-06-04

En orden:

1. **Manana**: cierre del bloque MFA TOTP (4/6, 5/6, 6/6) +
   promocion. Tests E2E del dashboard ya estaban cerrados desde
   la sesion anterior.
2. **Mediodia**: bloque entero de email password reset
   (5 commits, 28 tests, fix doble QP wrapping).
3. **Tarde**: handoff doc final del cierre de 3 bloques originales.
4. **Despues**: bloque email MFA arrancado. Commit 1/5
   funcional + verificado (22 tests + suite 139). Los 4 commits
   restantes documentados aqui con snippets de codigo concretos.
