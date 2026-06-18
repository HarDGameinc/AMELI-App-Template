## AMELI App Template handoff (sesion Claude, 2026-06-12)

> **Drift note (added 2026-06-18, roadmap #16)**: this handoff
> describes features around **API tokens** and **webhooks**
> (modelo, services, middleware, admin UI, CLI, signal
> dispatcher, HMAC dispatcher) that were **removed from the
> template baseline in commit `641ece1` (2026-06-09)**. Treat
> those sections as historical record — code references no
> longer resolve in the current `dev`/`main` tree.


Fecha: `2026-06-12`

Continuacion de
[`CLAUDE_HANDOFF_2026-06-11_TEMPLATE_DEV.md`](CLAUDE_HANDOFF_2026-06-11_TEMPLATE_DEV.md).

Tres bloques de hardening de seguridad sobre la base del 11-jun. Cierra
1 CRITICO, los 5 ALTOS pendientes, 9 MEDIOS y 5 mejoras proactivas que
quedaron documentadas en la auditoria del dia anterior. La postura de
seguridad cambia de "buena base" a "lista para apps internas/intranet
con un nivel de hardening serio".

### Estado general al cierre

- Repo: `HarDGameinc/AMELI-App-Template`
- Rama estable: `main` (post-promocion del dia)
- Rama de trabajo: `dev` (sincronizada con `main`)
- **519 tests pasando** (`pytest -v`)
- **0 regresiones**
- Nuevos archivos de tests: 3 grandes (`block1`, `block2`, `block3`)

### Contexto al arrancar

El cierre del 11-jun dejo un informe completo de auditoria con
clasificacion por severidad. El usuario aprobo trabajarlos en 3
sub-bloques, primero los criticos y quick wins, luego los ALTOS
estructurales, finalmente los refactors mayores.

Sub-bloques:
1. **Bloque 1**: CRITICO + quick wins (defensa en profundidad inmediata)
2. **Bloque 2**: ALTOS estructurales (sudo-mode, throttles, double-opt-in)
3. **Bloque 3**: refactors mayores (CSP nonces, throttle atomico, SRI)

Adicionalmente al arrancar el usuario decidio eliminar dos features que
ya no se usaban en el baseline:

- **API Tokens** + middleware + CLI + UI (commit `641ece1`)
- **Webhooks** app entera (commit `641ece1` mismo, ambas removidas
  juntas)

Tambien limpie referencias a la app heredada "Starlink" en los handoff
docs (commit `abdaf90`).

### Resumen ejecutivo

| Frente | Antes (11-jun) | Despues (12-jun) |
|---|---|---|
| `must_change_password` | Flag decorativo, sin enforcement | Middleware + modal bloqueante + redirect post-login |
| Admin write actions | Solo session auth, vulnerables a session theft | Sudo-mode con re-auth (password + MFA) y grace de 5 min |
| Cambio de email | Inmediato, vulnerable a session theft + password reset takeover | Double-opt-in con confirmacion del nuevo + alerta al viejo |
| Throttle login/forgot/MFA | COUNT(*) sobre AuditEvent, TOCTOU | Tabla counter atomica con `select_for_update` |
| Forgot-password + MFA resend | Sin throttle por IP | Throttle atomico por IP con auditoria |
| Admin disable MFA target | Sin notificacion al titular | Email de aviso + audit con actor |
| `/health` `/metrics` | Publicos sin auth | Allowlist IP opcional |
| Swagger/ReDoc CDN | URL flotante `@5` `@next`, sin SRI | Pin version exacto + SRI opcional con auto-prefix |
| `script-src 'unsafe-inline'` | Cualquier inline script ejecutaba | Nonce per-request, XSS bloqueada por browser |
| HIBP password check | No existia | Toggle opcional con k-anonymity |
| Audit log de actions criticas | Algunas sin actor consistente | Actor uniforme en todas las acciones de admin |
| Audit log tamper detection | No habia | HMAC chain opcional + `verify-audit` CLI |

### Bloque 1 — Critico + quick wins (8 commits)

| Commit | Item | Severidad |
|---|---|---|
| `5e7d25d` | Block 1 master: must-change-password middleware, sudo nonce setup, csv injection escape, sha384 password hashing | C1 + H8, H9, H11, H13 |
| `5bb842f` | Fix must-change-password redirect target (POST-only 405) | bug del propio bloque |
| `4b144a9` | GET /profile/password/ redirects to Security tab | bug del flow |
| `7a65931` | Blocking modal for must_change_password | UX upgrade del C1 |
| `18a0db6` | Fix django comment syntax in partial | cosmetico |
| `353edd0` | Logout in modal via POST not GET | bug del flow |
| `974de95` | Remove stale test-email handler | limpieza JS |
| `87ce4f7` | Fix duplicate const emailCancelBtn breaking tabs | bug critico de JS |

**Hallazgos cerrados**:

- **CRITICO #1**: `must_change_password` ahora se enforce via
  `MustChangePasswordMiddleware`. Modal bloqueante en `/profile/` con
  el form de cambio + boton de logout via POST + CSRF. El login
  redirecta directo al tab Seguridad cuando el flag esta puesto.
- **H8**: `request.session.cycle_key()` despues de cada cambio de MFA
  (enrollment, disable totp/email, regen recovery codes) — invalida una
  cookie robada que el atacante todavia este usando.
- **H9**: Argon2 como hasher principal. PBKDF2 queda como fallback
  para hashes existentes; Django reencodea silenciosamente al primer
  login post-deploy.
- **H11**: `AMELI_APP_TRUSTED_PROXIES` ahora es **obligatorio** fuera
  de `dev`. Sin esa setting el deploy se niega a arrancar — evita que
  un operador olvide configurarlo y deje el throttle aplicado sobre la
  IP del proxy.
- **H13**: CSV injection escape (`'=+-@\\t\\r` => prefijo `'`) en
  exports de audit y users. Excel ya no ejecuta formulas inyectadas.

### Bloque 2 — Altos estructurales (7 commits)

| Commit | Item |
|---|---|
| `fa1e5ee` | `@require_http_methods` en `admin_users` + `admin_update_user` (#2) |
| `23a329b` | IP throttle forgot/MFA + email al disable MFA (H2 + #7) |
| `24d7cfc` | Actor consistente en audit del MFA disable notify |
| `a8c01ee` | Sudo-mode admin (H5) |
| `e35b83d` | Sudo modal: accept email MFA + auto-detect methods |
| `8cd29e0` | Traduccion al espanol del rate-limit email MFA |
| `f27b73d` | Double-opt-in cambio de email (#5) |

**Hallazgos cerrados**:

- **#2** `admin_users` y `admin_update_user` ahora con
  `@require_http_methods` declarativo. Verbs no soportados se rechazan
  antes de entrar a la vista (capa extra de seguridad).
- **H2** Throttle por IP en `/login/forgot/` y `/login/verify-mfa/resend/`
  con `LoginThrottled` reusada. Mensajes de error traducidos al espanol.
  Audit ANTES del SMTP send para que el rate limit no se pueda burlar
  rompiendo el SMTP.
- **#7** Email al titular cuando admin deshabilita su MFA. Template
  nuevo (`mfa_disabled_by_admin.txt`) con nombre del actor. Audit row
  `mfa_disabled_notify_sent`/`_failed` con actor consistente.
- **H5 (Sudo-mode)**: nueva pieza grande de seguridad.
  - Sesion stampada con `sudo_until` (default 5 min, configurable
    `AMELI_APP_SUDO_GRACE_SECONDS`).
  - `@sudo_required` decorator en `admin_users` POST,
    `admin_update_user` (todos los metodos), `admin_disable_user_mfa`,
    `admin_reset_user_password`, `admin_revoke_session`,
    `admin_change_password`.
  - Endpoint `POST /admin/sudo/` con `verify_sudo_credentials` que
    acepta password + (TOTP, email MFA code, o recovery code).
  - Endpoint `GET /admin/sudo/status/` reporta metodos enrolados para
    que el modal renderice el campo correcto.
  - Endpoint `POST /admin/sudo/email-code/` dispara codigo por email
    si el admin tiene email MFA.
  - Modal en `admin/panel.html` con detection automatica de metodo
    (TOTP/email/ambos), `requestJson()` wrapper que retry-tea
    transparentemente despues de un OK.
  - Revoke automatico al logout y al password change (un atacante con
    sesion robada pierde el sudo el momento que la victima rota
    credenciales).
- **#5 (Double-opt-in email)**: cambio de email ahora pasa por:
  1. POST en `/profile/email-change/` con password actual.
  2. Email al NUEVO address con link de confirmacion.
  3. Email al VIEJO address con link de cancelacion + aviso.
  4. El cambio se aplica solo al clickear el link del nuevo address.
  5. Si tiene MFA email enrolado, se desactiva al confirmar
     (el nuevo address no esta enrolado).
  - Modelo `EmailChangeRequest` + migration `0006`.
  - Templates `email_change_confirm.txt`, `email_change_alert.txt`,
    `email_change_outcome.html`.
  - El form de preferencias ya NO tiene campo email (esta en una
    tarjeta dedicada del tab Seguridad).

### Bloque 3 — Refactors mayores (7 commits)

| Commit | Item |
|---|---|
| `db91dd3` | Allowlist IP /health /metrics (H12) |
| `ac903a1` | Pin version + SRI Swagger/ReDoc (H10) |
| `188dee8` | HIBP k-anonymity opcional (H7) |
| `80a198a` | Auto-prefix sha384- en SRI hashes |
| `c6cb5ca` | CSP per-page /docs y /redoc para jsdelivr |
| `23585f6` | Throttle atomico con counter table (#4) |
| `1e53220` | CSP nonces (H3) |

**Hallazgos cerrados**:

- **H12**: nueva setting `AMELI_APP_HEALTH_METRICS_ALLOWLIST`. Si esta
  configurada y la IP del cliente no esta → 403. Default off (compat con
  Prometheus scrapers).
- **H10**: Swagger UI y ReDoc pinneados a versiones exactas
  (`5.20.0` y `2.1.5`). 4 settings `AMELI_APP_SRI_*` para los hashes.
  Helper `_sri()` auto-prefixea `sha384-` si el operador pega solo el
  base64 (output natural de `openssl dgst -sha384 -binary | openssl
  base64 -A`). Sin hash configurado, se omite el `integrity=` y el
  pin de version sigue siendo la defensa.
- **CSP per-page /docs y /redoc**: la policy estricta del resto del
  sitio bloqueaba el CDN. Sin esta fix las pruebas mostraban CSP
  violations. Solo `/docs` y `/redoc` permiten `cdn.jsdelivr.net`.
- **H7**: `HIBPPasswordValidator` opcional en
  `AUTH_PASSWORD_VALIDATORS`. Toggle `AMELI_APP_HIBP_PASSWORD_CHECK`.
  Implementacion k-anonymity sin dependencias externas (urllib). Falla
  abierto en errores de red (la policy validator es la gate estricta;
  HIBP es defensa en profundidad).
- **#4 (Throttle atomico)**: la gran refactor del bloque.
  - Modelo nuevo `ThrottleCounter(scope, key, window_start, count)`
    con `unique_together` para acceso atomico.
  - Migration `0007_throttlecounter`.
  - Helpers `_bump_throttle_counter` (uses `select_for_update` +
    `F("count") + 1` dentro de `transaction.atomic`).
  - `record_login_failure(username, ip)` llamado desde el signal
    `user_login_failed` — bumpea los counters antes del audit row.
  - `check_login_throttle` ahora lee del counter atomico, no del
    `COUNT(*)` sobre AuditEvent.
  - `check_forgot_password_throttle` y `check_mfa_resend_throttle`
    hacen bump-and-check atomico (un atacante no puede colar attempts
    rompiendo el SMTP — el counter se bumpea antes).
  - El audit log SIGUE escribiendose para consultas historicas en el
    admin; ya no es la source of truth para el gating.
- **H3 (CSP nonces)**: la otra gran refactor.
  - `SecurityHeadersMiddleware` ahora genera 16 random bytes per request
    (`request.csp_nonce`).
  - Build de la CSP via `build_csp(nonce)` — sin `'unsafe-inline'` en
    script-src.
  - Context processor expone `csp_nonce` a todos los templates.
  - Cada inline `<script>` en `panel.html`, `profile.html`,
    `_force_password_modal.html`, `verify_mfa.html`, `reset_password.html`
    tiene `nonce="{{ csp_nonce }}"`.
  - `/docs` y `/redoc` threadean el nonce a la CSP custom + al boot
    script de SwaggerUIBundle.
  - `style-src` mantiene `'unsafe-inline'` (todos los layouts usan
    `style=""` inline; refactor no compensa, riesgo cosmetico).

### Numeros del dia

- **23 commits promocionados a `main`** (22 del plan + 1 de H6 bonus)
- **512 tests pasando** (508 al inicio del dia → +120 nuevos tests y
  -116 obsoletos = neto +4 por refactors que consolidan)
- 13 archivos de tests nuevos o muy modificados
- 3 migraciones nuevas:
  - `accounts/0006_emailchangerequest` (Bloque 2)
  - `accounts/0007_throttlecounter` (Bloque 3)
  - (eliminada 0006 antigua del bloque previo, renumerada)
- 1 dep Python nueva: `argon2-cffi>=23.1.0`
- 0 deps Python eliminadas
- ~4500 lineas netas agregadas, ~2200 lineas eliminadas
- 0 regresiones funcionales

### Decisiones tomadas (no re-discutirlas)

- **API Tokens y Webhooks eliminados**: no estaban en el baseline
  minimo del Template (`AGENTS.md`) y no tenian consumidores reales.
  Se eliminan completamente, se reintroducen cuando aparezca un caso
  de uso concreto en una app heredada.
- **`must_change_password` con modal full-screen** en lugar de banner:
  defensa en profundidad UX, el atacante con sesion robada no puede
  silenciosamente saltar el flag.
- **Sudo-mode con grace de 5 min** en lugar de re-auth en cada accion:
  trade-off UX. Operador no escribe password 30 veces durante un audit
  pero cada accion sensible esta gated por re-auth recientes.
- **Double-opt-in email cambia el invariante de MFA email**: al confirmar
  el nuevo address, MFA email se desactiva. La nueva inbox no esta
  enrolada y dejarlo activo seria un free 2FA para el nuevo owner.
- **HIBP fail-open**: si la red esta caida, dejamos pasar el password.
  La policy validator es la gate estricta; bloquear cambios de password
  porque HIBP esta caido es peor trade-off que dejar entrar un password
  potencialmente leakeado.
- **Style-src mantiene `'unsafe-inline'`**: 50+ `style=""` inline en
  los templates de layout. Refactorearlos todos no compensa el riesgo
  (style no ejecuta JS). Script-src es donde el riesgo es alto y donde
  los nonces hacen la diferencia.
- **Throttle atomico con counter dedicado**: la idea de leer
  AuditEvent rows es elegante pero tiene TOCTOU. El counter dedicado
  con `select_for_update` es la solucion estandar y barata. AuditEvent
  sigue siendo source para consultas historicas.

### Items NO parchados (decision)

| Item | Razon |
|---|---|
| **N3**: Lockout permanente despues de N ventanas consecutivas | Trade-off UX vs seguridad. Para uso interno mejor el lockout temporal actual. |
| **M5 del 11-jun**: MFA explicito para `/django-admin/` | Sesion ya valida MFA al login. Defense in depth pendiente. |

### Bloque 3-bonus — H6 (audit HMAC chain)

Despues del handoff inicial el usuario pidio cerrar el ultimo item
del audit del 11-jun. Se agrego en el commit `76c2e8f` (continuacion
fuera del bloque 3 principal).

**Cambios**:

- `AuditEvent` gana dos campos: `prev_hmac` y `hmac` (ambos
  `CharField`, blank por default para no romper rows legacy).
- Migration `audit/0002_auditevent_hmac_auditevent_prev_hmac`.
- `record_audit` ahora hace lookup-and-lock de la ultima fila con
  `select_for_update` dentro de `transaction.atomic`, computa HMAC
  SHA-256 sobre `(prev_hmac, action, actor, target, payload_json,
  created_at)` con la key del operador, y escribe ambos campos. Cuando
  no hay key (default) escribe sin chain (compat).
- `verify_audit_chain(start_id, stop_id)` recorre la chain y reporta
  el primer break con `{ok, checked, broken_id, broken_reason,
  expected, found}`. Las filas legacy (`hmac=""`) se skipean — pre-
  chain history no es tampering.
- Setting `AUDIT_HMAC_KEY` leida desde `AMELI_APP_AUDIT_HMAC_KEY`.
  Default vacio.
- Comando CLI `ameli-app verify-audit --from-id N --to-id M` con exit
  code 1 cuando hay tampering (utilizable desde cron/systemd).

**Verificado en server dev**:

- Genero key, restart, primer audit row con HMAC valido (id=482).
- `verify-audit` con chain limpia retorna `{"ok": true, "checked": 1}`.
- Modificacion directa de payload (`AuditEvent.objects.filter(id=482)
  .update(payload={'tampered': True})`) detectada como `{"ok": false,
  "broken_id": 482, "broken_reason": "hmac mismatch", "expected":
  "67c1...", "found": "c65c..."}` con exit code 1.

7 tests cubren: no-key (rows escriben sin stamp), chain-on,
verificacion limpia, tampering de payload, fila eliminada, mezcla
legacy + chained, refuse sin key.

**Setup operativo**:

```bash
# Generar key
.venv/bin/python -c "import secrets; print(secrets.token_urlsafe(48))"

# En /etc/<slug>-<env>/app.env
AMELI_APP_AUDIT_HMAC_KEY=<la-key>

systemctl restart <service>

# Verificacion periodica
.venv/bin/ameli-app verify-audit
```

IMPORTANTE: una vez configurada la key, NO rotarla sin re-anchorar
(toda la chain post-rotacion fallaria contra la key vieja). Si hay
que rotar, exportar la chain anterior, archivar, y empezar una nueva
con la key nueva.

### Snapshot al cierre — superficie de seguridad

| Frente | Cobertura |
|---|---|
| Auth / login | Argon2 + throttle atomico por IP + lockout atomico por user |
| Force change password | **Middleware + modal bloqueante + redirect post-login** |
| Sesion | HttpOnly + Secure + SameSite + idle renewal + cycle_key on MFA + disabled-user kick + revoke on password change |
| **Sudo-mode admin** | **Re-auth con password + MFA, grace 5 min, revoke en logout/pw-change** |
| MFA | TOTP + email + recovery codes, throttle atomico, notif al titular en admin disable |
| Password change forgot | Throttle atomico por IP, mensaje en espanol, audit pre-SMTP |
| **Cambio de email** | **Double-opt-in con confirm + alert + cancel link** |
| HIBP password check | Opcional via toggle, k-anonymity |
| Audit log | Actor consistente + **HMAC chain opcional + `verify-audit` CLI con tamper detection** |
| Webhooks | Removidos del Template |
| API tokens | Removidos del Template |
| Avatares | Format whitelist + pixel cap + byte cap |
| Static/media | DEBUG-gated + media auth gate |
| Headers / CSP | **Nonces per-request en script-src, sin `'unsafe-inline'`** |
| /docs /redoc | Pin version + SRI opcional + CSP per-page con nonce + jsdelivr |
| /health /metrics | Allowlist IP opcional |
| Config | Boot guards (SECRET_KEY, ALLOWED_HOSTS, DEBUG, TRUSTED_PROXIES) |

### Proximos bloques abiertos

| # | Item | Tipo | Tamaño |
|---|---|---|---|
| 1 | Selector de idioma en header (i18n loop) | UX | Chico |
| 2 | Retry + queue para emails fallidos | Operativo | Medio |
| 3 | Banner en `/profile/` cuando MFA no esta enrolado | UX | Chico |
| 4 | Soporte para Argon2id parameter tuning via env | Seguridad | Chico |
| 5 | Rotacion de `AUDIT_HMAC_KEY` con re-anchor | Seguridad operativa | Medio |
| 6 | MFA explicito para `/django-admin/` (M5 del 11-jun) | Seguridad | Chico |

### Orden recomendado para retomar

1. Resync local + servidor al hash `1e53220`
2. Aplicar migraciones:
   ```bash
   .venv/bin/ameli-app shell -c "from django.core.management import call_command; call_command('migrate')"
   ```
3. **Importante** post-deploy:
   - Verificar que `AMELI_APP_TRUSTED_PROXIES` este seteado en
     `/etc/<slug>-<env>/app.env` (obligatorio fuera de `dev` desde
     Bloque 1).
   - Si tiene salida a internet y quieren activar HIBP: agregar
     `AMELI_APP_HIBP_PASSWORD_CHECK=true`.
   - Si quieren cerrar `/health`/`/metrics`: configurar
     `AMELI_APP_HEALTH_METRICS_ALLOWLIST=...`.
   - Calcular hashes SRI una vez (desde una maquina con internet) y
     pegarlos en `AMELI_APP_SRI_*` — opcional pero recomendado.
4. Si seguimos con Template: H6 (audit HMAC).

### Comandos utiles de continuidad

Server resync con migracion:

```bash
cd /opt/ameli-app-template-dev
git fetch origin && git reset --hard origin/dev
.venv/bin/ameli-app shell -c "from django.core.management import call_command; call_command('migrate')"
systemctl restart ameli-app-template-dev-api.service
```

Verificar CSP en respuestas:

```bash
# La global con nonce per-request (sin 'unsafe-inline' en script-src)
curl -sD - http://10.100.100.16:18080/ -o /dev/null | grep -i content-security

# La per-page de /docs (jsdelivr permitido + nonce)
curl -sD - http://10.100.100.16:18080/docs -o /dev/null | grep -i content-security

# Nonces rotando per request
for i in 1 2 3; do
  curl -sD - http://10.100.100.16:18080/ -o /dev/null | grep -oP "'nonce-\K[^']+"
done
```

Verificar XSS bloqueada en browser (DevTools Console):

```js
const s = document.createElement('script');
s.textContent = "alert('xss')";
document.body.appendChild(s);
// Esperado: violacion CSP en console, no se ejecuta el alert
```

Inspeccionar throttle counters:

```bash
.venv/bin/ameli-app shell -c "
from ameli_web.accounts.models import ThrottleCounter
print(list(ThrottleCounter.objects.all().values('scope', 'key', 'count', 'window_start')))
"
```

Calcular hashes SRI desde otra maquina:

```bash
for f in swagger-ui.css swagger-ui-bundle.js swagger-ui-standalone-preset.js; do
  hash=$(curl -sL "https://cdn.jsdelivr.net/npm/swagger-ui-dist@5.20.0/$f" \
         | openssl dgst -sha384 -binary | openssl base64 -A)
  echo "AMELI_APP_SRI_${f^^}=$hash" | tr '-' '_' | tr '.' '_'
done
curl -sL https://cdn.jsdelivr.net/npm/redoc@2.1.5/bundles/redoc.standalone.js \
     | openssl dgst -sha384 -binary | openssl base64 -A \
     | sed 's/^/AMELI_APP_SRI_REDOC_BUNDLE=/'
```

Activar HIBP cuando el server tenga salida a internet:

```bash
# En /etc/<slug>-<env>/app.env
AMELI_APP_HIBP_PASSWORD_CHECK=true
systemctl restart <service>
```

Tests:

```bash
DATABASE_URL= APP_ENV=dev .venv/bin/pytest -v
```

### Archivos clave del cierre

- [`src/ameli_web/accounts/middleware.py`](../src/ameli_web/accounts/middleware.py) — `MustChangePasswordMiddleware`, `SecurityHeadersMiddleware` con nonce
- [`src/ameli_web/accounts/services.py`](../src/ameli_web/accounts/services.py) — sudo helpers, throttle atomico, email change, HIBP no aplica aca
- [`src/ameli_web/accounts/validators.py`](../src/ameli_web/accounts/validators.py) — `HIBPPasswordValidator`
- [`src/ameli_web/accounts/models.py`](../src/ameli_web/accounts/models.py) — `EmailChangeRequest`, `ThrottleCounter`
- [`src/ameli_web/accounts/views.py`](../src/ameli_web/accounts/views.py) — email change views, sudo flow, cycle_key en MFA
- [`src/ameli_web/admin_views.py`](../src/ameli_web/admin_views.py) — `@sudo_required`, `admin_sudo`, `admin_sudo_status`, `admin_sudo_email_code`
- [`src/ameli_web/dashboard/views.py`](../src/ameli_web/dashboard/views.py) — `_sri()`, `_docs_csp(nonce)`, `_operational_allowlist_block`
- [`src/ameli_web/settings.py`](../src/ameli_web/settings.py) — CDN_SRI_HASHES, HEALTH_METRICS_ALLOWLIST, HIBP toggle, Argon2 hashers, sin CONTENT_SECURITY_POLICY (ahora dinamica)
- [`src/ameli_web/templates/`](../src/ameli_web/templates/) — todos los inline `<script>` con `nonce="{{ csp_nonce }}"`, modal sudo en `admin/panel.html`, modal force-password en `accounts/_force_password_modal.html`, form de cambio de email en `accounts/profile.html` tab Seguridad
- Tests: 3 archivos grandes (`test_security_hardening_block1.py`, `_block2.py`, `_block3.py`) mas tests dedicados de email change y email change tokens
