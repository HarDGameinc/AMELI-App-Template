# Phase B security review (item #1) — modules auth-criticos

Fecha: 2026-06-24
Agente coordinador: claude-opus-4-7
Subagentes: 3 (`general-purpose`, uno por modulo) en paralelo, background
Inputs: `services.py` 3793 lineas + `views.py` 1185 lineas + `middleware.py` 411 lineas

Este documento consolida el output de los 3 subagentes lanzados para
el item #1 del plan B-D (ver `CLAUDE_HANDOFF_2026-06-24_TEMPLATE_DEV.md`
§7.1). NO duplica los reports completos — ver tasks/* logs si se
necesita el detalle largo. Aqui solo el triage + verificacion de
los HIGHs.

## Resumen ejecutivo

| Modulo | HIGH | MED | LOW | INFO |
|---|---|---|---|---|
| `accounts/services.py` | 0 | 4 | 2 | 1 |
| `accounts/views.py` | 2 | 3 | 3 | 0 |
| `accounts/middleware.py` | 2 (1 degrade) | 3 | 2 | 1 |
| **Total** | **3 + 1 dudoso** | **10** | **7** | **2** |

Tematica dominante: **cookie-thief threat under-defended**. Cookie
robada (XSS, equipo compartido, session-fixation) puede escalar a
takeover completo del segundo factor (`mfa_regenerate`, `mfa_start`,
`mfa_email_start`) sin necesidad de saber el password. Patron de fix
unico: requerir `current_password` en estos endpoints — `mfa_disable`
ya lo hace y es el modelo correcto.

Secundario: **brute-force surfaces post-password**. `verify_mfa_view`
no throttle ni incrementa contadores; un atacante con leaked password
puede hammer TOTP/email codes.

Terciario: **HIGH dudoso** en orden de middleware (cache-control).
Confirmacion del codigo demuestra que la branch solo se ejecuta para
authenticated requests, asi que el escenario "excepcion inner sin
user" no leakea data de user — degrade a MED.

## Triage de fixes pre-v1.0

### Bloque A — HIGH confirmados (CERRADO en `a1e2626`)

| ID | Modulo:linea | Patron | Fix aplicado | Status |
|---|---|---|---|---|
| **A1** | `services.py:2270` `regenerate_recovery_codes` + `views.py:705` | kwarg `current_password` requerido + view parsea JSON body | Hecho | ✓ |
| **A2** | `services.py:1569` `start_mfa_enrollment` + `services.py:2186` `start_mfa_email_enrollment` | Idem A1 | Hecho | ✓ |
| **A3** | `views.py:894-927` `verify_mfa_view` POST handler | `check_login_throttle` + `record_login_failure` con sliding-window de login | Hecho | ✓ |
| **A4** | `middleware.py:240-251` `MustChangePassword._ALLOWED_EXACT` | `/profile/` removido del allow-list, redirige a `/profile/password/` standalone (nuevo template `accounts/force_password_change.html` + GET branch en `change_password_view`) | Hecho | ✓ |

**Resultado**: 1017 tests pass (1004 anteriores + 13 nuevos de
regresion en `tests/test_cookie_thief_hardening.py`). Ruff clean.
Sin migracion. Sin schema change. Frontend actualizado:
`profile.html` ahora hace `window.prompt()` del password antes
de los 3 endpoints MFA mutating.

Cambios en JS UX: usa `window.prompt()` como MVP — un input
inline tipo `mfa_disable` quedaria mas profesional. Followup
opcional (no bloquea).

### Bloque B — MED relevantes (mismo sweep si presupuesto alcanza)

| ID | Modulo:linea | Patron | Fix | Costo |
|---|---|---|---|---|
| **B1** | `services.py:3666-3679` `verify_sudo_credentials` | sin throttle en sudo | Counter dedicado (`scope="sudo_fail_user"`, cap 5/60s) que revoca sudo + force re-login | 15 min |
| **B2** | `services.py:3493-3499` `_find_email_change_request` | `!=` en lugar de `compare_digest` | `hmac.compare_digest(record.token_hash, _hash_email_change_token(...))` | 2 min |
| **B3** | `services.py:1715-1754` `change_email_for_self` | dead code sin password ni doble-opt-in | Eliminar funcion completa (grep confirma 0 callers) | 5 min |
| **B4** | `views.py:303-319` `update_preferences` JSON branch | `display_name` sin length cap | Slice `[:80]` o `full_clean()` antes del `save` | 5 min |
| **B5** | `views.py:1130-1154` `email_change_confirm_view` | GET-driven mutation (mail-scanner auto-click) | Convertir a interstitial: GET muestra form, POST confirma | 20 min |
| **B6** | `middleware.py:382-387` `MaintenanceModeMiddleware._state` | `except Exception` fail-opens | Capturar solo `OperationalError`/`ProgrammingError` durante migracion; logging + audit en catch generico | 10 min |
| **B7** | `middleware.py:320-344` `DjangoAdminSudoGate` | skip si `is_staff=True` AND `role != SUPERADMIN` | Gate por `user.is_staff` (mas seguro) o documentar+assertear el invariante de `User.save` | 10 min |

**Subtotal Bloque B**: ~70 min.

### Bloque C — LOW / followups (cuando se quiera)

- `services.py:3447-3491` `request_email_change`: wrap en `transaction.atomic`, audit en confirmation send fail (F5 services). ~10 min.
- `services.py:609-614` `revoke_other_sessions`: envolver en `transaction.atomic`. ~5 min.
- `middleware.py:155-218` `UserSessionMiddleware`: cap path para skip `/static/` `/media/`. ~10 min.
- `views.py:1008-1011` `forgot_password_view`: truncar `identifier` a 256 chars antes de `record_audit`. ~3 min.
- `views.py:741-743` `_clear_pending_mfa`: audit del descarte de pending. ~5 min.
- `middleware.py:120-127` SecurityHeadersMiddleware: si se quiere, mover position 3 a despues de Auth para defense-in-depth en error responses (degradado de HIGH a MED en verificacion).

**Subtotal Bloque C**: ~45 min.

## Verificacion de los HIGHs

### A1 / A2 confirmados leyendo `views.py:611-720`

```python
# views.py:649 — mfa_disable_view (BIEN, requiere password)
@login_required
@require_POST
def mfa_disable_view(request: HttpRequest) -> JsonResponse:
    payload = _json_body(request)
    current_password = str(payload.get("current_password") or "").strip()
    result = disable_mfa_for_self(request.user.username, current_password=current_password)
    ...

# views.py:697 — mfa_regenerate_view (MAL, no requiere password)
@login_required
@require_POST
def mfa_regenerate_view(request: HttpRequest) -> JsonResponse:
    result = regenerate_recovery_codes(request.user.username)  # solo username
    ...

# views.py:611 — mfa_start_view (MAL, no requiere password)
def mfa_start_view(request: HttpRequest) -> JsonResponse:
    result = start_mfa_enrollment(request.user.username)
    ...

# views.py:708 — mfa_email_start_view (MAL, no requiere password)
@login_required
@require_POST
def mfa_email_start_view(request: HttpRequest) -> JsonResponse:
    result = start_mfa_email_enrollment(request.user.username)
    ...
```

Inconsistencia clara — el patron correcto existe en `mfa_disable_view`
y solo hace falta replicarlo en los 3 endpoints restantes.

### A3 confirmado leyendo `views.py:879-906`

El POST handler de `verify_mfa_view` lee `request.POST.get("code")`,
intenta TOTP/email/recovery, audita en falla pero NO incrementa
contadores ni llama a `check_login_throttle`. El throttle de
`verify_mfa_resend_view` (line 920) cubre solo el resend, no el verify.

### A4 confirmado leyendo `middleware.py:240-251`

```python
_ALLOWED_EXACT = {
    "/profile/",           # <-- LEE entero, incluye tabs MFA/sessions/audit
    "/profile",
    "/profile/password/",
    "/profile/password",
    ...
}
```

El comment en lineas 268-271 justifica diciendo que "el form vive
en la security tab", pero `profile.html` renderiza TODAS las tabs en
el mismo GET — el browser puede navegar entre ellas en JS sin
fetch adicional.

## Observaciones positivas confirmadas

De los 3 reports combinados, vale destacar:

1. **Audit chain HMAC + select_for_update + transaction.atomic**: el
   patron es consistente en `services.py:record_audit`,
   `rotate_audit_key`, `_prune_audit_with_anchor`. Re-verifica
   antes y despues de la rotacion.
2. **`hmac.compare_digest` en `mfa.py`**: comparaciones constantes en
   recovery / email codes. `secrets.choice` para generacion.
3. **Timing-pad anti-enumeration en `forgot_password_view`**
   (views:988-1025): equaliza tiempo de respuesta + jitter para no
   fingerprintear el padding. Modelo a copiar.
4. **`revoke_sudo` post-password-change** (views:487, 513): cambio
   de password rota sudo grants ademas del session_auth_hash.
5. **`request.session.cycle_key()` tras cada cambio MFA**
   (views:643, 659, 675, 691, 702, 737): defensa contra session
   fixation en privilege escalation.
6. **Honeypot + bland-error en login** (views:119-136): bot que
   llena `hp_company` recibe la misma respuesta que wrong-password,
   sin enseñar la trampa.
7. **Audit-before-delivery en throttled endpoints** (views:938-945,
   1005-1011): el counter incrementa aunque SMTP falle, cerrando
   el bypass.
8. **CSP base solida**: `frame-ancestors 'none'`, `base-uri 'self'`,
   `form-action 'self'`, `require-trusted-types-for 'script'`,
   `trusted-types ameli-template`.
9. **Nonce CSP regenerado por request** con `secrets.token_urlsafe(16)`.
10. **`__Host-` cookie prefix + boot guards en settings.py**.
11. **PII scrub post-send en `process_email_queue`** (services:2670-2676).
12. **Identical-response anti-enumeration en `request_password_reset`**.

## Recomendaciones para el operador

1. **Cerrar Bloque A en una sola sesion de fix (~60 min)**. Los 4
   findings comparten el patron "cookie-thief escala", se pueden
   verificar con un solo test `test_cookie_thief_threat_model.py`
   que documente el invariante de "current_password required para
   cambios de MFA / dispatch de codes".
2. **Considerar Bloque B en la misma o siguiente sesion**. B3
   (dead code) es delete-only; B2 y B4 son one-line; B5 y B6/B7
   son los mas costosos pero todavia <30 min cada uno.
3. **Bloque C como followups**. No bloquean v1.0; documentarlos en
   el roadmap como "polish de seguridad".

**Promote `dev → main` como "v1.0 production-ready" requiere**:
Bloque A cerrado + tests verdes + threat model actualizado (item
#2 del Plan B-D) + `BUILDING_NEW_APP.md` creado (item #5).
