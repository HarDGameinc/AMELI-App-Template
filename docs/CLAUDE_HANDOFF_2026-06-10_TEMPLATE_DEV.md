## AMELI App Template handoff (sesion Claude, 2026-06-10)

Fecha: `2026-06-10`

Continuacion de
[`CLAUDE_HANDOFF_2026-06-09_TEMPLATE_DEV.md`](CLAUDE_HANDOFF_2026-06-09_TEMPLATE_DEV.md).

Cierra el bloque "seguir mejorando el Template" con UI HTML para API
tokens, sistema completo de webhooks (modelos + dispatcher HMAC + admin
UI), e infraestructura i18n con catalogos espanol e ingles.

### Estado general al cierre

- Repo: `HarDGameinc/AMELI-App-Template`
- Rama estable: `main` (post-promocion del dia)
- Rama de trabajo: `dev` (sincronizada con `main`)
- Servidor Debian: `/opt/ameli-app-template-dev`, puerto `18080`
- **451 tests pasando** (`pytest -v`)
- **0 regresiones**

### Contexto al arrancar

Cierre del 2026-06-09 dejo el backlog operativo con tres items abiertos
en el orden pedido: UI de tokens, webhooks, i18n. El usuario decidio
dedicar la sesion a estos tres frentes del Template.

### Bloque del dia (4 commits)

| Commit | Item |
|---|---|
| `2309816` | UI HTML para API tokens en `/profile/` |
| `b39bae5` | Webhooks app: modelos + dispatcher + signal |
| `c781024` | Admin UI para gestionar webhooks |
| `b484eba` | i18n con catalogos es + en |

#### `2309816` — UI tokens en perfil

Tab nuevo "API Tokens" en `/profile/`. Form de creacion (`name`) que
hace `POST /profile/tokens/` con CSRF. Si OK, el plaintext se muestra
en un bloque `warn-text` con copy-to-clipboard. Listado debajo con
cada token en estado activo/revocado/expirado, badge de estado, prefix
del token (no el plaintext), creado/ultimo uso, boton Revocar.

JS maneja el flow completo en cliente:

- `appendTokenRow(record)` actualiza el listado sin refresh
- Revoke con `confirm()` + transicion visual a estado `DEGRADADO`
- Empty state cuando no hay tokens

View `profile_view` enriquece el context con `api_tokens =
list_api_tokens(request.user)`. **6 tests**.

#### `b39bae5` — Webhooks app

App Django nueva `ameli_web.webhooks`. Dos modelos:

- `WebhookEndpoint(name, url, secret, events, enabled, created_by,
  last_triggered_at, last_success_at, last_failure_at,
  total_deliveries, total_failures)`
- `WebhookDelivery(endpoint, event_action, event_payload, status_code,
  response_excerpt, success, error, duration_ms, created_at)` — historico
  para el admin

Migracion `webhooks/0001_initial`. Registrada en `INSTALLED_APPS`.

Service `deliver_event(endpoint, action, payload)`:
- Body JSON `{event, payload, timestamp, endpoint_id}` con
  `sort_keys=True` (firmas reproducibles)
- HMAC-SHA256 del body con `endpoint.secret`
- Headers `X-Ameli-Event`, `X-Ameli-Timestamp`,
  `X-Ameli-Signature: sha256=...`, `User-Agent: AMELI-Webhook/1.0`
- Timeout 5 segundos via `urllib`
- Persiste `WebhookDelivery` row con resultado (status_code,
  response_excerpt 400 chars, success, error si lo hubo)
- Actualiza counters del endpoint

Signal `post_save` de `AuditEvent` dispara `dispatch_for_audit_event`
sincronicamente para los endpoints `enabled` y `subscribed_to(action)`.
Excepciones del dispatcher se swallowean para no romper la grabacion
del audit. **15 tests** (con HTTP mockeado).

Decisiones:

- Sin worker queue por ahora — sync con timeout corto cubre el caso de
  uso (audit events son low-volume)
- Sin retry automatico — el operador ve el delivery fallido en la UI y
  puede re-enviar manualmente despues
- HMAC en lugar de bearer auth — receptores como Slack/Discord no
  pueden mandar Authorization, pero todos pueden verificar firma HMAC
  con el secret compartido

#### `c781024` — Admin UI webhooks

Panel "_webhooks_panel.html" incluido en `/admin/` debajo del audit
panel. Form para crear (name + url + events comma-separated). Si OK,
modal "Guarda este secret ahora" con el value generado, listo para
copiar al receptor. Listado abajo con estado activo/deshabilitado,
URL truncada, contadores de entregas/fallos, ultimo intento, lista de
eventos suscritos (o "TODOS").

Endpoints `/admin/webhooks/`:

- `GET` lista (sin secret)
- `POST` crea (devuelve secret una vez)
- `POST /<id>/revoke/` deshabilita
- `GET /<id>/deliveries/` historico ultimas 30

JS handler igual patron que tokens UI. **8 tests**.

#### `b484eba` — i18n

Settings:

- `LANGUAGES = [("es", "..."), ("en", "...")]`
- `LOCALE_PATHS = [PROJECT_DIR / "locale"]`
- `LocaleMiddleware` agregado a `MIDDLEWARE` (entre `SessionMiddleware`
  y `CommonMiddleware`, posicion canonica)

Subset de strings marcados con `gettext as _`:

- Mensajes de `messages.success/error/warning` en login, logout,
  profile, avatar, password
- `LoginThrottled` y `AccountLocked` messages

Catalogos:

- `locale/es/LC_MESSAGES/django.po` + `.mo` (default, espanol como
  esta)
- `locale/en/LC_MESSAGES/django.po` + `.mo` (ingles traducido para los
  strings marcados)

Doc `docs/I18N.md` con instrucciones para:
- Como Django elige el idioma del request
- Como marcar strings nuevos (Python + templates)
- Como regenerar y compilar catalogos
- Como agregar un idioma nuevo

**5 tests** (config check, throttle traducido en cada locale, logout
respeta `Accept-Language`).

Decisiones:

- **No traducir TODO**: cubrimos auth + throttle + acciones comunes.
  Apps heredadas marcan sus strings con `_()` y regeneran. Evita un
  commit gigante que envejece rapido.
- **`.mo` committeados** al repo: production no siempre tiene `msgfmt`
  y queremos despliegues idempotentes.
- **`gettext`** (eager) en views, **`gettext_lazy`** en modelos/forms.
  Docs documenta cuando usar cual.

### Snapshot al cierre

| Frente | Cobertura |
|---|---|
| API tokens | Backend + CLI + **UI HTML completa** en profile |
| Webhooks | Modelos + dispatcher HMAC + signal + **admin UI** completa |
| i18n | Catalogos es + en, **`Accept-Language` respetado**, doc para extender |
| Resto | Sin cambios respecto al 2026-06-09 |

### Numeros del dia

- 4 commits promocionados a `main`
- **451 tests pasando** (417 al inicio → 451, +34 tests)
- 1 migracion (`webhooks/0001_initial`)
- 0 deps Python nuevas
- 1 dep apt nueva en dev: `gettext` (necesario solo para regenerar
  catalogos, no para correr la app)
- ~1700 lineas netas agregadas

### Decisiones tomadas (no re-discutirlas)

- **Webhooks sync + timeout corto** en lugar de queue async. Audit
  events son low-volume; si se vuelven hotspot, migramos a worker
  reusando la misma firma de `deliver_event`.
- **HMAC en lugar de bearer** para webhooks. Compatible con Slack,
  Discord, scripts internos que no soportan Authorization header.
- **i18n parcial**: marca solo strings de alta visibilidad. No
  pretendemos traducir UI completa en este commit; el patron queda
  documentado para que las apps heredadas lo extiendan.
- **`.mo` committeados**: produccion no necesita `gettext` instalado,
  redespliegue es reproducible bit a bit.

### Proximos bloques abiertos

| # | Item | Tipo | Tamaño |
|---|---|---|---|
| 1 | Reintento + queue para webhooks (si el sync timeout se vuelve cuello) | Medio | Medio |
| 2 | Selector de idioma manual (cookie + dropdown en header) | UX | Chico |
| 3 | Traducciones EN completas para toda la UI (no solo backend) | i18n | Medio-grande |
| 4 | Retry policy + dead-letter para webhooks fallidos | Medio | Medio |

### Orden recomendado para retomar

1. Resync local + servidor al hash de `main` post-promocion
2. **Migrar webhooks**: `.venv/bin/ameli-app shell -c "from django.core.management import call_command; call_command('migrate')"`
3. Si seguis con Template: probable orden = retry para webhooks +
   selector de idioma en header

### Comandos utiles de continuidad

Server resync con migracion:

```bash
cd /opt/ameli-app-template-dev
git fetch origin && git reset --hard origin/dev
.venv/bin/ameli-app shell -c "from django.core.management import call_command; call_command('migrate')"
systemctl restart ameli-app-template-dev-api.service
```

Probar webhook end-to-end (necesitas un receptor HTTP):

```bash
# 1. Crear endpoint via admin UI o curl con session cookie + CSRF
# 2. Verificar que llegan eventos haciendo cualquier accion que genere
#    audit (ej: login fallido)
# 3. Revisar deliveries en /admin/webhooks/<id>/deliveries/
```

Probar i18n:

```bash
curl http://10.100.100.16:18080/login/ -H "Accept-Language: en" | grep -o "Signed out\|Sesion cerrada"
```

Regenerar catalogos despues de marcar strings nuevos:

```bash
.venv/bin/django-admin makemessages -l es -l en --ignore=tests --no-location
# Editar locale/<lang>/LC_MESSAGES/django.po
.venv/bin/django-admin compilemessages
```

Tests:

```bash
DATABASE_URL= .venv/bin/pytest -v
```

### Archivos clave del cierre

- [`src/ameli_web/webhooks/`](../src/ameli_web/webhooks/) — app completa (models, services, signals)
- [`src/ameli_web/templates/admin/_webhooks_panel.html`](../src/ameli_web/templates/admin/_webhooks_panel.html) — UI admin
- [`src/ameli_web/templates/accounts/profile.html`](../src/ameli_web/templates/accounts/profile.html) — tab "API Tokens" + JS
- [`src/ameli_web/admin_views.py`](../src/ameli_web/admin_views.py) — endpoints webhook admin
- [`src/ameli_web/settings.py`](../src/ameli_web/settings.py) — `LANGUAGES`, `LOCALE_PATHS`, `LocaleMiddleware`
- [`locale/es/LC_MESSAGES/django.po`](../locale/es/LC_MESSAGES/django.po) y [`en/...`](../locale/en/LC_MESSAGES/django.po) — catalogos
- [`docs/I18N.md`](I18N.md) — guia para marcar y traducir strings
- [`tests/test_profile_tokens_ui.py`](../tests/test_profile_tokens_ui.py)
- [`tests/test_webhooks.py`](../tests/test_webhooks.py)
- [`tests/test_admin_webhooks_ui.py`](../tests/test_admin_webhooks_ui.py)
- [`tests/test_i18n.py`](../tests/test_i18n.py)
