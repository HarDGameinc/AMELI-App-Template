## AMELI App Template handoff (sesion Claude, 2026-06-11)

Fecha: `2026-06-11`

Continuacion de
[`CLAUDE_HANDOFF_2026-06-10_TEMPLATE_DEV.md`](CLAUDE_HANDOFF_2026-06-10_TEMPLATE_DEV.md).

Auditoria de seguridad completa con remediacion de los 3 CRITICOS, los
5 ALTOS y la mayoria de MEDIOS/BAJOS identificados. Quedan algunos
items menores documentados como notas.

### Estado general al cierre

- Repo: `HarDGameinc/AMELI-App-Template`
- Rama estable: `main` (post-promocion del dia)
- Rama de trabajo: `dev` (sincronizada con `main`)
- **508 tests pasando** (`pytest -v`)
- **0 regresiones**

### Contexto al arrancar

Usuario pidio una revision completa de seguridad. Hice un audit de 12
areas (auth, tokens, CSRF, sesiones, webhooks, throttle, validacion,
configuracion, etc.) y entregue un informe con 17 hallazgos clasificados
por severidad (CRITICO/ALTO/MEDIO/BAJO + notas). Usuario aprobo el
parcheo y trabajamos los items en orden de impacto.

### Bloque del dia (9 commits)

| Commit | Items parchados | Severidad |
|---|---|---|
| `994dc71` | SECRET_KEY / ALLOWED_HOSTS / DEBUG guards al startup | C1, C2 (part), M1 |
| `e75c51f` | `public_url_base` requerido fuera de dev (password reset poisoning) | C2 |
| `1e53259` | `client_ip` con trusted proxies + throttle por JSON path exacto | C3, A1 |
| `085db65` | SSRF guard en webhooks (RFC1918, loopback, metadata, reserved) | A3 |
| `34a2f04` | API token scopes (read default, admin requerido para admin views) | A2 |
| `4232756` | Avatar validation (formato whitelist + dimensiones) | A5 |
| `d9d4803` | Media auth gate + static serve solo en dev | A4 |
| `0eadc6f` | Defaults seguros (Secure cookies, HttpOnly, SameSite, CSP, XFO) | M2, M3, B1-B4 |
| `1b4fcb2` | Force logout cuando user disabled regresa con sesion activa | N4 |

#### `994dc71` — Refuse insecure boot

Tres guards al import-time en `settings.py`, todos disparan `RuntimeError`
para que el deploy no arranque silenciosamente con configuracion peligrosa:

1. `SECRET_KEY` bundled (`ameli-app-dev-secret-key`) fuera de `dev` → refuse
2. `DEBUG=True` fuera de `dev` → refuse (leaks SECRET_KEY, env vars, traces)
3. `ALLOWED_HOSTS` vacio o con `*` fuera de `dev` → refuse

El environment `dev` mantiene la tolerancia: en local podemos seguir
arrancando con los defaults sin friccion. El default de `django_debug`
paso de `environment == "dev"` a `False` (explicit opt-in via env var).
**6 tests** en `test_settings_boot_guards.py`.

#### `e75c51f` — Password reset host injection

`_build_public_base_url(request)` hacia fallback a
`request.build_absolute_uri("/")` cuando `public_url_base` no estaba
configurado. El Host header es controlado por el cliente, asi que un
atacante podia poisonear el reset email para que apunte a su server.

Ahora: si no hay `public_url_base` y el environment no es `dev`,
levanta `RuntimeError` con mensaje claro. **4 tests**.

#### `1e53259` — IP trust + throttle JSON exact match

Dos issues en una sola superficie:

- `client_ip` confiaba ciegamente en `X-Forwarded-For`. Atacante podia
  rotar la IP del header en cada request y bypasear rate limit + envenenar
  audit logs. Fix: nueva setting `TRUSTED_PROXIES` (default
  `{"127.0.0.1", "::1"}`), solo se lee el header cuando `REMOTE_ADDR`
  esta en la whitelist.
- Throttle contaba `login_failed` matcheando substring en JSON
  (`"ip": "1.2.3"`). Vulnerable a false positives cuando un payload
  legitimo contenia esa string. Fix: JSON path lookup exacto
  (`payload__ip` / `payload__ip_address`).

**6 tests** en `test_client_ip_trusted_proxies.py`.

#### `085db65` — SSRF en webhooks

Antes: el unico check era que la URL arrancara con `http(s)://`. Un
superadmin (o admin comprometido) podia setear
`http://169.254.169.254/` (AWS metadata) o `http://127.0.0.1:5432/`
(port scan interno), recibir la response en el panel admin, y
exfiltrar credenciales o pivotear.

Fix nuevo helper `_assert_target_is_safe(url)` que:

1. Resuelve el host con `socket.getaddrinfo`
2. Para cada IP retornada chequea: loopback, link-local, multicast,
   reserved, private, unspecified — rechaza si alguna falla
3. Maneja IPv4-mapped-IPv6 (`::ffff:10.0.0.1`)

Se aplica al `create_webhook_endpoint` (early) y al `deliver_event`
(defensa contra DNS rebinding entre create y delivery). **14 tests** en
`test_webhook_ssrf.py`.

#### `34a2f04` — API token scopes

Antes: un token heredaba TODOS los permisos del user dueño. Si el user
era superadmin, el token podia hacer cualquier accion admin sin pasar
por MFA. Si el token filtraba, atacante tenia control total.

Ahora:

- Campo `scopes JSONField` en `ApiToken` (`["read", "write", "admin"]`)
- Migracion `0007_apitoken_scopes` con backfill: tokens preexistentes
  reciben `["read"]` (least-privilege, no escalada silenciosa)
- `create_api_token(scopes=...)` valida el set conocido; default `["read"]`
- `superadmin_required` decorator chequea `request.api_token.has_scope("admin")`
  — un token sin admin scope que tenta acceder a `/admin/*` recibe 403
- Sesiones de cookie NO son tokens, asi que el check no las afecta
- CLI `ameli-app create-token --scope read --scope write`
- HTTP `POST /profile/tokens/` acepta `{"scopes": [...]}`

**8 tests** en `test_api_token_scopes.py`.

#### `4232756` — Avatar hardening

`ImageField` valida via Pillow, pero quedaban gaps:

- Format whitelist: solo JPEG/PNG/WebP/GIF (cierra SVG con JS embebido)
- Pixel cap: maximo 4096 px por lado (defeats decompression bombs:
  un PNG 50kx50k pasa el byte check pero explota RAM al renderizar)
- Byte cap pre-existente: 3MB

**7 tests** en `test_avatar_validation.py`.

#### `d9d4803` — Static/media gates

`django.views.static.serve` es dev-only segun la doc oficial.

Ahora:

- `/static/` solo wireado cuando `DEBUG=True`; en non-dev Caddy lo sirve
- `/media/` siempre wireado pero detras del nuevo `_authenticated_media`
  que retorna 403 si no hay sesion. Defensa en profundidad: incluso si
  Caddy se rompe, los avatares no son publicos.

**3 tests** en `test_media_auth_gate.py`.

#### `0eadc6f` — Defaults seguros + CSP

Cambios en `settings.py`:

- `SESSION_COOKIE_SECURE` default `True` fuera de dev (opt-out, no
  opt-in)
- `SESSION_COOKIE_HTTPONLY = True` (JS no puede leer)
- `SESSION_COOKIE_SAMESITE = "Lax"`
- `CSRF_COOKIE_HTTPONLY = True`
- `CSRF_COOKIE_SAMESITE = "Lax"`
- `SECURE_REFERRER_POLICY = "same-origin"`
- `CONTENT_SECURITY_POLICY` configurada (script-src self con
  unsafe-inline para el JS inline existente, font-src para Google
  Fonts, frame-ancestors none, etc.)
- Hint comentado para `SECURE_PROXY_SSL_HEADER` cuando Caddy esta
  adelante
- `SECURE_HSTS_SECONDS = 0` (operador lo activa cuando TLS esta estable)
- `XFrameOptionsMiddleware` agregado a la cadena
- Nuevo `SecurityHeadersMiddleware` propio que setea CSP

Removi `SECURE_BROWSER_XSS_FILTER` (deprecated, lo reemplaza CSP).

**7 tests** en `test_security_headers.py`.

#### `1b4fcb2` — Disabled user logout

`UserSessionMiddleware` ahora chequea `request.user.is_active`. Si un
admin deshabilita a un user mientras este tiene sesion activa, el
proximo request fuerza logout + redirect a `/login/`. **2 tests**.

### Items NO parchados (decision)

Algunos items del informe quedaron documentados como notas para
proximas sesiones:

| Item | Razon |
|---|---|
| **M5**: MFA explicita para `/django-admin/` | Tema avanzado; sesion ya valida MFA al login. Defense in depth pendiente. |
| **N1**: Rotacion in-place de tokens | Patron actual (revoke + create) cubre el caso. UX mejora pendiente. |
| **N2**: Anti-replay en webhooks del lado receptor | Responsabilidad del receptor (estandar de la industria: Stripe igual). Documentar en `docs/`. |
| **N3**: Lockout permanente tras N ventanas consecutivas | Trade-off contra UX. No critico para uso interno. |

### Snapshot al cierre — superficie de seguridad

| Frente | Cobertura |
|---|---|
| Boot | Refuse en non-dev sin SECRET_KEY/ALLOWED_HOSTS/DEBUG safe |
| URLs publicas | `public_url_base` requerido, no Host header trust |
| Auth | MFA + password policy + forgot password (preexistente) |
| **API tokens** | **Scopes con default read, admin scope requerido para admin** |
| **Sesiones** | **HttpOnly + Secure + SameSite + idle renewal + disabled-user kick** |
| Rate limiting | IP throttle con trusted proxies + account lockout |
| Audit | Login fail + throttle + lockout registrados con IP real |
| **Webhooks** | **HMAC SHA256 + SSRF guard con RFC1918/loopback/metadata reject** |
| Avatares | Format whitelist + pixel cap + byte cap |
| Static/media | DEBUG-gated + media auth gate |
| Headers | CSP + XFO + Referrer-Policy + cookies seguros |
| Config | Boot guards + summary expone configuracion |

### Numeros del dia

- 9 commits promocionados a `main`
- **508 tests pasando** (451 al inicio → 508, +57 tests)
- 1 migracion (`accounts/0007_apitoken_scopes`)
- 0 deps Python nuevas
- ~1400 lineas netas agregadas

### Decisiones tomadas (no re-discutirlas)

- **Boot guards refuse hard**: mejor un deploy que no arranca que uno
  que arranca con SECRET_KEY default. Operador necesita saber.
- **`TRUSTED_PROXIES` default solo loopback**: opt-in explicito para
  cualquier otra IP. Mas seguro que defaults laxos.
- **API token scopes empieza en `["read"]`**: backfill de tokens
  pre-existentes con read-only para que la migracion no abra superficie.
- **CSP usa `'unsafe-inline'` en script-src**: necesario para el JS
  inline actual. Plan futuro: nonces o mover JS a archivos externos.
- **SSRF guard valida en create y deliver**: deliver-time check evita
  DNS rebinding.
- **`SECURE_HSTS_SECONDS = 0`**: el operador lo activa cuando TLS esta
  estable. Encenderlo antes lockea contra HTTPS.
- **Disabled user kick instantaneo**: el rendimiento extra (un campo
  mas en el query) es despreciable y la garantia operativa vale.

### Proximos bloques abiertos

| # | Item | Tipo | Tamaño |
|---|---|---|---|
| 1 | UI HTML para mostrar/editar scopes de tokens | UX | Chico |
| 2 | MFA defense in depth para `/django-admin/` | Seguridad | Medio |
| 3 | Selector de idioma en header (i18n loop) | UX | Chico |
| 4 | Retry + queue para webhooks fallidos | Operativo | Medio |
| 5 | Doc receptor webhook con verificacion de timestamp | Doc | Chico |

### Orden recomendado para retomar

1. Resync local + servidor al hash `1b4fcb2`
2. Aplicar migracion: `.venv/bin/ameli-app shell -c "from django.core.management import call_command; call_command('migrate')"`
3. **Importante** post-deploy: actualizar el `app.env` del server para
   setear `AMELI_APP_DJANGO_SECRET_KEY` real (si todavia esta el default)
4. Configurar `TRUSTED_PROXIES` cuando Caddy este adelante:
   ```python
   # via env: AMELI_APP_TRUSTED_PROXIES=127.0.0.1,::1
   ```
5. Si seguis con Template: UI de scopes en `/profile/` + retry para
   webhooks.

### Comandos utiles de continuidad

Server resync con migracion:

```bash
cd /opt/ameli-app-template-dev
git fetch origin && git reset --hard origin/dev
.venv/bin/ameli-app shell -c "from django.core.management import call_command; call_command('migrate')"
systemctl restart ameli-app-template-dev-api.service
```

Crear un token admin (necesario para curl contra endpoints `/admin/*`):

```bash
.venv/bin/ameli-app create-token --user admin --name "admin-bot" --scope read --scope admin
# Sin --scope admin, el token NO puede tocar /admin/*
```

Verificar que el panel admin rechaza tokens sin admin scope:

```bash
TOKEN_READ=ameli_...  # token con default scopes (read only)
curl -i http://10.100.100.16:18080/admin/users -H "Authorization: Bearer $TOKEN_READ"
# Esperado: 403 con mensaje "token lacks admin scope"
```

Probar SSRF guard:

```bash
# Crear webhook con URL privada — debe fallar:
curl -X POST http://10.100.100.16:18080/admin/webhooks/ \
    -H "Authorization: Bearer $TOKEN_ADMIN" \
    -H "Content-Type: application/json" \
    -d '{"name":"evil","url":"http://127.0.0.1:5432/"}'
# Esperado: 400 con "SSRF"
```

Tests:

```bash
DATABASE_URL= .venv/bin/pytest -v
```

### Archivos clave del cierre

- [`src/ameli_web/settings.py`](../src/ameli_web/settings.py) — boot guards + cookies + CSP
- [`src/ameli_app/config.py`](../src/ameli_app/config.py) — `django_debug` default
- [`src/ameli_web/accounts/models.py`](../src/ameli_web/accounts/models.py) — `ApiToken.scopes` + `has_scope`
- [`src/ameli_web/accounts/services.py`](../src/ameli_web/accounts/services.py) — `client_ip` + throttle JSON path + token scopes
- [`src/ameli_web/accounts/middleware.py`](../src/ameli_web/accounts/middleware.py) — `SecurityHeadersMiddleware` + token record + disabled-user kick
- [`src/ameli_web/accounts/views.py`](../src/ameli_web/accounts/views.py) — `_build_public_base_url` hardening
- [`src/ameli_web/accounts/forms.py`](../src/ameli_web/accounts/forms.py) — avatar validation
- [`src/ameli_web/admin_views.py`](../src/ameli_web/admin_views.py) — admin scope enforcement
- [`src/ameli_web/webhooks/services.py`](../src/ameli_web/webhooks/services.py) — SSRF guard
- [`src/ameli_web/urls.py`](../src/ameli_web/urls.py) — media auth gate
- Tests: 9 archivos nuevos cubren cada parche
