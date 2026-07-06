# Changelog

## v0.4.11-django — 2026-07-06 (a11y: tema oscuro + teclado + tokens -fill)

Amplía el smoke de accesibilidad a **ambos temas** y agrega checks de
teclado. Validado en CI (axe con `emulate_media` claro+oscuro) y smoke
visual en servidor (tema oscuro impecable).

### a11y+ (commit `5a86106`)

- **Test** (`tests/e2e/test_accessibility.py`): cada página corre en
  claro **y oscuro** (`page.emulate_media`); se suma `/login/forgot/` y
  2 checks de teclado (skip-link es el primer Tab stop y apunta a
  `<main>`; el form de login es alcanzable). El mensaje de fallo muestra
  fg/bg/ratio de axe.
- **Fixes de contraste del tema oscuro** (el claro no los tenía): el
  palette oscuro reutilizaba colores brillantes como **fondos rellenos**
  con texto blanco, cayendo bajo 4.5:1 — botones primarios (3.16:1),
  pills de estado (2.83:1), botones danger. Se introdujeron tokens
  `--accent-fill` / `--ok-fill` / `--warn-fill` / `--bad-fill` (color de
  fondo relleno bajo texto blanco): claro = base; oscuro = variantes más
  oscuras que superan 4.5:1. `--bad` oscuro #e5564a → #ee6459 para el
  texto "fail" del checklist.

Nota: el tema **Auto** delega correctamente en `prefers-color-scheme`
(sin `data-theme`); si el navegador (p.ej. Firefox "Apariencia del sitio
web") fuerza oscuro, Auto se ve oscuro — es esperado, no un bug.

Bump tras smoke visual en `ha-report2` (tema oscuro: botones/pills/checklist
legibles, nada lavado).

## v0.4.10-django — 2026-07-06 (accesibilidad: smoke axe-core + fixes)

Cierra el gap "no accessibility tests". Nuevo smoke axe-core (WCAG 2.1
A/AA) sobre login/dashboard/profile/admin vía Playwright, gateando
critical + serious. Validado en CI (Linux) y smoke visual en servidor.

### a11y (commit `254948e`)

- **Test** (`tests/e2e/test_accessibility.py`): axe-core 4.10.2 vendoreado
  (`tests/e2e/vendor/axe.min.js`, MPL-2.0, test-only, sin dep pip ni
  cambio de lock) inyectado vía `page.evaluate` (sortea la CSP por CDP).
- **Fixes que el test encontró**:
  - `select-name` (critical): los 4 `<select>` de filtro admin sin nombre
    accesible → `aria-label` (`users_role`, `users_status`,
    `audit_outcome`, `admin_sessions_status`).
  - `color-contrast` (serious): `--muted` (#687385) y `--warn` (#b46a00)
    del tema claro caían apenas bajo 4.5:1 → #5b6472 / #a15e00.
  - `.password-policy-item.fail` usaba un durazno claro (#ffcfbf) pensado
    para fondo oscuro (~1.3:1 en blanco) → `var(--bad)`, por-tema
    (#b42318 claro / #e5564a oscuro), legible en ambos.
- Atribución axe-core en `THIRD_PARTY_LICENSES.md`.

Bump aplicado tras smoke visual en `ha-report2` (checklist de contraseña
rojo/legible, filtros OK, nada roto por el cambio de contraste).

## v0.4.9-django — 2026-07-03 (refactor: split del JS inline a estáticos)

Cierra el ítem de deuda frontend **"split inline JS"** del roadmap. Los
dos `<script>` inline grandes de las plantillas pasan a archivos
estáticos externos, protegidos con SRI y servidos desde `'self'` bajo el
`script-src` de la CSP (sin nonce). Refactor **sin cambio de
comportamiento**, validado en `ha-report2` (ambas páginas responden
igual, sin errores en DevTools).

### Fase 1 — `profile.js` (commit `1dcb8ff`)

`accounts/profile.html` adelgaza ~530 líneas: el JS (tabs, cambio de
contraseña, MFA activar/desactivar app+email, tools de recuperación,
cambio de email) se movió a `static/js/profile.js`. Los 9 `{% url %}`
server-rendered viajan por `data-*` en un `#profile-js-config` oculto; el
CSRF se sigue leyendo del input oculto del form. Include gateado por
`not must_change_password` (misma condición que tenía el inline).

### Fase 2 — `admin-panel.js` (commit `8e1e5e6`)

`admin/panel.html` adelgaza ~600 líneas: el JS (toggle de mantenimiento,
widget de cola de email, sudo grant/status, CRUD de usuarios +
rol/password/MFA) se movió a `static/js/admin-panel.js`. Las URLs ya
eran literales `/admin/*`, así que el único valor inyectado es el CSRF,
vía `data-csrf-token` en `#admin-js-config`.

### Infra

- `base.html`: nuevo `{% block extra_scripts %}` tras `app.js` (antes de
  `</body>`, para que un listener `DOMContentLoaded` siga disparando).
- Sin `collectstatic`: `_serve_static` (urls.py) resuelve `/static/*`
  con `finders.find()` directo desde `STATICFILES_DIRS`.
- Tests: la aserción de wiring de recovery-tools se movió al archivo
  `profile.js`; +1 test que fija el include externo con SRI en `/admin/`.

## v0.4.8-django — 2026-07-03 (D-2: re-auth MFA inline + tools de recuperación)

Cierra **D-2** del roadmap: la re-autenticación por contraseña en el
panel MFA de `/profile` dejó de usar los diálogos nativos del navegador
(`window.prompt` / `confirm` / `alert`) y ahora usa **campos de
contraseña inline**, igual que el flujo de desactivación que ya existía.
Validado en `ha-report2` (smoke navegador): activar app, activar email y
regenerar códigos, los tres sin popups nativos.

### D-2 — re-auth inline (commit `fb8e9e1`)

Tres acciones endurecidas contra robo de sesión (PHASE_B A1/A2) pasan a
input inline con toggle de visibilidad:

- **Activar 2FA (app)**: `#profile-mfa-totp-activate-password`.
- **Activar 2FA (email)**: input inline, solo cuando hay email
  registrado (si no, el botón queda deshabilitado como antes).
- **Regenerar códigos**: input inline + leyenda de advertencia +
  feedback `aria-live`, reemplazando el trío `confirm()`+`prompt()`+
  `alert()`.

Cada campo se limpia al éxito, valida vacío con foco y muestra errores
en línea. Los IDs de botón se preservaron, así que los tests de render
apilado siguen verdes. +3 tests que fijan los campos inline y la
ausencia de `window.prompt` en el body servido.

### Fix — tools de recuperación tras regenerar (commit `9a9d7d8`)

El handler de regenerar pintaba los códigos pero **nunca cableaba**
`setupRecoveryTools()`, así que Copiar / Descargar / Imprimir quedaban
muertos tras un regenerado (bug pre-existente, aflorado en el smoke de
D-2). Ahora reusa `showRecoveryOrReload()` — el mismo helper que ya
usan los flujos de enrolamiento app/email — para cablearlos consistente.

### Fallback de copia en HTTP (commit `3889fbd`)

El botón Copiar usaba solo `navigator.clipboard`, gateado a contexto
seguro (HTTPS / localhost). En un deploy HTTP (dev o red interna sin
TLS) degradaba a "copia manual". Se añade un fallback legacy
(`<textarea>` temporal + `document.execCommand('copy')`) que corre
**solo** cuando `window.isSecureContext` es `false`: un deploy
HTTPS/Caddy toma la rama de la Clipboard API moderna y nunca ejecuta
`execCommand`, así el path viejo se auto-desactiva en producción sin
flag. Descargar / Imprimir ya eran independientes del contexto seguro.

Validado en `ha-report2` (HTTP): copiar, descargar e imprimir OK.

## v0.4.7-django — 2026-07-02 (fix: cropper submit síncrono)

Fix del cropper de avatar (v0.4.6): el submit hacía `preventDefault` +
`canvas.toBlob` **async** + `form.submit()` diferido. En un navegador
manual funciona (S-09 pasó), pero rompía el e2e Playwright
`test_avatar_upload_renders_image_in_hero`: el `.click()` retornaba
antes de que arrancara la navegación diferida, `wait_for_url` matcheaba
la URL `/profile/` actual de forma trivial y la aserción corría sobre la
página vieja → 0 imágenes. El CI e2e venía rojo desde el commit del
cropper (`618b451`).

**Fix**: el submit ahora es **síncrono** — se arma el archivo recortado
con `canvas.toDataURL` (síncrono, no `toBlob`) y se hace el swap al
`<input type=file>` vía `DataTransfer` **sin** `preventDefault`, así el
submit nativo serializa el archivo recortado en el mismo tick y la
cadena click→redirect queda síncrona (lo que espera el navegador y el
auto-wait de Playwright). Además simplifica el código (sin callback
async ni re-submit).

Verificado: los 4 tests e2e Playwright verdes en local (chromium).

## v0.4.6-django — 2026-07-02 (cropper de avatar)

Capa de recorte/encuadre en el cliente para el avatar: el usuario elige
**qué mostrar** (pan + zoom) antes de subir, en vez del recorte-al-centro
implícito. Validado en navegador (S-09 en `ha-report2`): el cropper
aparece, drag+zoom responden, el avatar guardado refleja el encuadre
elegido y el archivo en disco es `WEBP (512, 512) EXIF: {}`.

### Cropper de avatar (commit `618b451`)

`setupAvatarCropper()` en `static/js/app.js` revela un canvas cuadrado
al elegir una imagen; pan (pointer + flechas) y zoom (slider). En submit
renderiza el cuadro visible a un canvas 512, lo exporta a Blob y lo mete
al `<input type=file>` vía `DataTransfer` → el submit **nativo** lo sube
y el pipeline D-5 (resize + WebP + strip EXIF) lo procesa.

- **Seguridad/CSP**: la imagen se lee con `FileReader.readAsDataURL`
  (`data:` URL), NO `URL.createObjectURL` (`blob:`), para respetar la CSP
  `img-src 'self' data:` sin relajarla. Sin sinks de Trusted Types
  (solo canvas + `createElement`).
- **Progressive enhancement**: feature-gated
  (canvas/FileReader/DataTransfer). Sin JS, el `<input>` nativo sube el
  archivo crudo y el pipeline lo procesa. El input plano se preserva.
- `templates/accounts/profile.html`: scaffold del cropper dentro de
  `#avatar-form`, oculto por defecto.
- `static/css/app.css`: estilos del cropper (reusa las clases
  `.avatar-crop-*` antes huérfanas).
- `tests/test_profile_avatar_ui.py`: test de presencia del scaffold +
  fallback no-JS intacto.

Sin cambios de dependencias ni migraciones.

## v0.4.5-django — 2026-07-02 (D-5)

Pipeline de transformación de avatar (resize + WebP + strip EXIF).
Validado en servidor (S-08 en `ha-report2`): un avatar subido en wire
queda como `WEBP (512, 512) EXIF: {}` y `verify-audit` → `ok: true`.

### D-5 (commit `da239cd`)

`services/user.py:replace_avatar` ahora pasa cada upload por el nuevo
`services/images.py:transform_avatar` **después del AV scan, antes del
`.save()`**:

- `ImageOps.exif_transpose` — hornea la orientación EXIF en los píxeles.
- `img.thumbnail((MAX, MAX))` — reduce a un cuadrado configurable
  (solo achica, nunca agranda).
- Strip explícito de `exif`/`xmp`/`icc_profile` + re-encode a WebP —
  **este strip es lo que realmente elimina el bloque GPS/PII** (el
  encoder WebP de Pillow re-incrusta `img.info['exif']` si no se limpia).

Un PNG grande de celular (3 MB / 4000px) → WebP ~30 KB / ≤512px sin
EXIF. Transparente para templates (`avatar_url` ya apunta al archivo).

- **Settings** (`settings/media.py`, nuevo): `AVATAR_FORMAT`
  (`webp`/`keep`), `AVATAR_MAX_DIMENSION` (512, clamp 64-2048),
  `AVATAR_WEBP_QUALITY` (82, clamp 1-100). Env `AMELI_APP_AVATAR_*` con
  clamp defensivo — un valor basura no rompe un upload. Registrado en el
  orquestador `settings/__init__.py` (paso 6b).
- **Fallback**: `transform_avatar` devuelve `None` (→ guardar verbatim)
  si el operador puso `keep` o si el transform falla, para que un avatar
  nunca se pierda por un edge case de Pillow.
- **Tests** (`tests/test_avatar_transform.py`, nuevo, 8): resize ≤ MAX +
  WebP, strip EXIF/GPS (con guard anti-vacuo), orientación aplicada,
  `keep` → None, no-upscale, alpha preservado, `.webp` + `avatar_url`
  resuelve, `keep` preserva extensión.

Sin cambios de dependencias ni migraciones.

## v0.4.4-django — 2026-07-01 (PC-4)

Cierre del split de `settings.py`. API pública intacta — Django sigue
leyendo `settings.<NAME>` sin ningún cambio en `urls.py`, middleware o
código externo.

### PC-4 (commit `911aea6`)

`ameli_web/settings.py` (746 líneas) convertido a paquete
`ameli_web/settings/` con 10 módulos:

- `base.py` — `BASE_DIR`, `PROJECT_DIR`, `CFG`, `ENV_NAME`,
  `SECRET_KEY`, `DEBUG`, `ALLOWED_HOSTS`, `TRUSTED_PROXIES`,
  `_int_env`, boot guards secret + debug + hosts + proxies.
- `integrations.py` — CDN SRI, `HEALTH_METRICS_ALLOWLIST`,
  `HIBP_PASSWORD_CHECK`, `AV_ENDPOINT` (+ scheme guard),
  `OTEL_EXPORTER_OTLP_ENDPOINT` (+ scheme guard), `SILK_ENABLED`
  (+ prod second-flag guard).
- `auth.py` — `PASSWORD_HASHERS`, `ARGON2_*`,
  `AUTH_PASSWORD_VALIDATORS`, `AUDIT_HMAC_KEY` (+ prod guard),
  `MFA_ENCRYPTION_KEY` (+ prod guard), `AUTH_USER_MODEL`,
  `LOGIN_URL`, `LOGIN_REDIRECT_URL`, `LOGOUT_REDIRECT_URL`.
- `cookies.py` — SESSION_COOKIE_* (con política `__Host-` +
  guards para Secure y Domain), CSRF_COOKIE_*.
- `security_headers.py` — HSTS, `X_FRAME_OPTIONS`,
  `SECURE_PROXY_SSL_HEADER`, `MESSAGE_STORAGE` (+ allow-list guard).
- `i18n_static.py` — `LANGUAGE_CODE`, `TIME_ZONE`, `LANGUAGES`,
  `STATIC_URL`, `MEDIA_ROOT` + path-inside-checkout guard.
- `database.py` — `_default_sqlite_path`, `_db_pool_options`,
  `_database_settings`, `DATABASES`. Ver "Late-binding de CFG" abajo.
- `applications.py` — `INSTALLED_APPS`, `MIDDLEWARE`, `TEMPLATES`,
  `ROOT_URLCONF`, WSGI/ASGI. Silk apps + middleware condicionales.
- `email.py` — `EMAIL_BACKEND`, SMTP config, `PASSWORD_RESET_TIMEOUT`,
  prod-only email backend guard.
- `__init__.py` — orquestador con orden crítico de imports +
  `# ruff: noqa: I001` para que ruff no reordene (rompería la
  cadena de guards).

### Fixes descubiertos durante la extracción

- **Orden crítico de imports**: ruff `--fix` reordena alfabéticamente
  y rompe la cadena de dependencias (`applications` lee `SILK_ENABLED`
  de `integrations`; `applications` debe cargarse después). Fix:
  `# ruff: noqa: I001` en `__init__.py`.
- **Test helpers `_reload_settings`** en 3 archivos
  (`test_settings_boot_guards.py`, `test_host_cookie_prefix.py`,
  `test_message_storage_guard.py`) solo poppeaban `ameli_web.settings`
  de `sys.modules`. Con package, los submódulos quedaban cacheados y
  los guards no re-corrían. Extendido a wipe de todos los
  `ameli_web.settings*`.
- **Late-binding de `CFG`** en `database.py`: 6 tests hacen
  `monkeypatch.setattr(settings, "CFG", ...)` y luego llaman
  `settings._database_settings()`. En el monolito el helper resolvía
  `CFG` en el mismo módulo → el patch tomaba efecto. En el package,
  `database.py` importaba `CFG` de `.base` al import time → referencia
  frozen. Fix: `_cfg()` que lee `settings.CFG` en cada llamada
  (late-binding a través del package).
- **Helpers privados** (`_database_settings`, `_db_pool_options`,
  `_default_sqlite_path`, `_int_env`, `_IS_DEV_ENV`) no propagados por
  `from .X import *` (drop de underscore names). Re-importados
  explícitamente en `__init__.py`.

### Verificación

- **Suite local Windows**: 1060 pass / 0 fail / 18 skip.
- **Ruff / Mypy**: 0 errores.
- **S-07 aprobado en `ha-report2`**: boot limpio, `manage.py check`
  0 issues, 15 settings symbols importables, valores derivados
  coherentes (INSTALLED_APPS=9, MIDDLEWARE=15,
  SESSION_COOKIE_NAME=`ameli_app_session` en dev,
  EMAIL_BACKEND=console en dev).

## v0.4.3-django — 2026-07-01 (PC-3 + Windows CI cleanup)

Cierre del split de `admin_views.py` + higiene de la suite local en
Windows. API publica intacta — `from ameli_web import admin_views` +
`admin_views.<name>` sigue funcionando sin cambios en `urls.py`.

### PC-3 (commit `a5e37fc`)

`ameli_web/admin_views.py` (745 lineas) convertido a paquete
`ameli_web/admin_views/` con 10 modulos:

- `_common.py` — decoradores (`superadmin_required`, `sudo_required`),
  constantes `*_PER_PAGE_COOKIE`, helpers.
- `panel.py` — `admin_panel` (HTML dashboard).
- `users.py` — 6 endpoints de users (list, update, MFA disable,
  password reset, unlock, admin change_password).
- `audit.py` — `admin_audit`.
- `exports.py` — `_csv_safe`, CSV/JSON export helpers,
  `admin_audit_export`, `admin_users_export`.
- `maintenance.py` — `admin_maintenance_toggle`, `admin_maintenance_status`.
- `metrics.py` — `admin_email_queue_metrics`.
- `sessions.py` — `admin_sessions`, `admin_revoke_session`.
- `sudo.py` — 4 endpoints de sudo (grant, email code, status,
  django-admin gate).

`_csv_safe` re-exportado desde `__init__.py` para preservar el
import directo de `tests/test_security_hardening_block1.py`.

**Fix de regresion durante la verificacion**: mi primera version
hand-written del decorador `sudo_required` devolvia `403 "sudo
required"` — el original devuelve `401 {"need_sudo": true,
"sudo_url": "/admin/sudo/"}` para que la UI prompt-and-retry
transparente. Restaurado antes del push.

### CI cleanup (commits `604ffe2`, `bc55df8`, `d607269`, `2556d74`, `35c8785`)

- 11 tests pre-existentes que fallaban en Windows marcados con
  `pytest.mark.skipif(sys.platform == "win32", ...)` (AF_UNIX, bash
  `sed`, symlink privilegio elevado, `st_dev/st_ino` POSIX inode).
  En CI Linux siguen corriendo sin cambios.
- 1 test corregido para ser cross-platform (`test_autodetect_prefers_
  config_yaml_over_example` usaba `"/config/app.yaml"` en lugar de
  `os.sep`-joined).
- Coverage de `views/` (post-PC-2) subio de ~78% a **96%** con nuevos
  tests para JSON malformado, form-POST invalido, `?partial=` fetch,
  wrong-password branches, `_csv_safe` export edge cases, y las 3
  ramas "generic Exception" (SMTP failure → 502).

### Verificacion

- **Suite local Windows**: 1060 pass / 0 fail / 18 skip (14 nuevos
  skipif Windows + 4 e2e opt-in).
- **CI Linux (bandit + pytest)**: 1031 pass / 0 fail / 6 skip.
- **Ruff / Mypy**: 0 errores.
- **S-06 aprobado en `ha-report2`**: boot limpio con la nueva
  version, 25 admin_views symbols importables, 7 URLs `/admin/*`
  responden 302 sin cookie, browser smoke manual OK (reset password,
  requerir 2FA, cambio obligatorio) — todas las acciones de admin
  panel pasan por `superadmin_required` + `sudo_required` correctos.

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

