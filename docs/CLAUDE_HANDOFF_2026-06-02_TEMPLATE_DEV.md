## AMELI App Template handoff (sesion Claude)

Fecha: `2026-06-02`

Este documento continua la linea del handoff anterior
[`CODEX_HANDOFF_2026-06-02_TEMPLATE_DEV.md`](CODEX_HANDOFF_2026-06-02_TEMPLATE_DEV.md)
y resume el trabajo hecho en la sesion con Claude (Opus 4.7) sobre el
Template Django-first. Sirve de puente para que otra IA o equipo siga
sin perder contexto.

### Estado general

- Repo: `HarDGameinc/AMELI-App-Template`
- Rama estable: `main` (`9cab8b4`)
- Rama de trabajo: `dev` (`0164cee`)
- Servidor de prueba Debian sigue en `/opt/ameli-app-template-dev`
  - Puerto `18080`, host `0.0.0.0`
  - Base PostgreSQL `ameli_app_template_dev`
  - Servicio `ameli-app-template-dev-api.service`

### Cierre del handoff anterior

Los pendientes del handoff de Codex quedaron resueltos en esta sesion:

1. Tracking del clon Debian arreglado — `git remote set-branches origin main dev` y `git fetch origin` ya traen `dev`.
2. `/profile` verificado visualmente con la UX metro completa.
3. Warning de migraciones de `accounts` eliminado con
   [`0002_alter_user_managers_alter_user_username.py`](../src/ameli_web/accounts/migrations/0002_alter_user_managers_alter_user_username.py).
4. Promocion `dev → main` con cherry-pick lineal; ambas ramas quedaron
   alineadas en `9cab8b4`.
5. Limpieza de `origin/master` colgante.

### Trabajo nuevo de esta sesion

#### Bloque entregado: completar gestion de usuarios en el admin metro

Cuatro commits encadenados, todos en `dev`:

```
0164cee defer inline scripts until app.js is loaded
3e1a929 complete admin user management ui with metro password ux
fb6b1bf extract reusable password ux module and refactor profile
```

##### `fb6b1bf` extract reusable password ux module and refactor profile

- Movio el generador, evaluador de robustez, toggle global de
  visibilidad y politica de la contrasena desde el script inline de
  `profile.html` al modulo `window.AmeliPassword` en
  [`src/ameli_app/static/js/app.js`](../src/ameli_app/static/js/app.js).
- API por data-attributes: cualquier form con `data-password-form`,
  `data-password-new`, `data-password-confirm`, `data-password-generate`,
  `data-password-strength-bar`, `data-password-strength-label`,
  `data-password-strength-hint`, `data-password-match-hint`,
  `data-password-submit`, `data-password-feedback`, y los items con
  `data-policy-check="length|upper|lower|digit|symbol"` se auto-cablea
  con `window.AmeliPassword.setupForm(form)`.
- Retorna `{ sync(), isValid(), getValue(), elements }` para que el
  llamador valide antes de hacer fetch.
- `profile.html` se simplifico (-141 lineas netas).

##### `3e1a929` complete admin user management ui with metro password ux

- Form "Crear usuario" portado a la misma UX metro (generador, toggle,
  politica visible con marcadores live, barra de robustez, campo de
  confirmacion).
- Form "Cambiar mi contrasena" del admin idem.
- Cada tarjeta de usuario en la lista (excepto la propia del logueado)
  ahora tiene una fila `admin-user-actions` con 5 botones:
  - **Restablecer contrasena** → abre `#reset-password-modal`
    (UX metro + checkbox "exigir cambio en proximo ingreso")
  - **Habilitar / Deshabilitar** → PATCH directo a `/admin/users/<u>`
    con `{enabled: bool}`
  - **Cambiar rol** → abre `#change-role-modal` con select
    `public ↔ superadmin`
  - **Forzar cambio / Quitar cambio obligatorio** → PATCH directo con
    `{must_change_password: bool}`
  - **Eliminar** → abre `#delete-user-modal`; el boton rojo se mantiene
    `disabled` hasta que el operador tipea exactamente el username
- CSS nuevo en `app.css`: `.admin-user-actions`.
- Self-guard: las acciones se ocultan en la tarjeta del usuario logueado
  (Django template `{% if user_item.username != current_user.username %}`)
  para evitar autoborrarse o autodesactivarse.
- El admin nativo de Django sigue disponible como fallback en
  `/django-admin/`.

##### `0164cee` defer inline scripts until app.js is loaded

- Bug introducido por mi propia refactorizacion.
- `base.html` carga `app.js` al final del body. Los `<script>` inline
  dentro de `{% block content %}` se ejecutaban DURANTE el parseo, antes
  de que `app.js` se cargara, asi que `window.AmeliPassword` era
  `undefined` cuando el inline script lo llamaba. En profile, el throw
  rompia todo (tabs, submit). En panel el `?.` evitaba el throw pero
  dejaba el experience en `null`, los submit hacian return silencioso.
- Fix: envolver los inline scripts de `profile.html` y `panel.html` en
  `document.addEventListener("DOMContentLoaded", () => { ... })`. Ahora
  esperan a que `app.js` cargue y `AmeliPassword` exista.
- Alternativa equivalente y mas limpia para futuro: mover
  `<script src="app.js" defer>` al `<head>` y poner las llamadas
  DOM-dependientes de `app.js` (`refreshHealthBadge`, `setupUserMenu`)
  dentro de un `DOMContentLoaded` propio. No se hizo porque el wrap en
  los dos templates era el cambio minimo y de menor riesgo.

#### Verificacion visual en `http://10.100.100.16:18080/`

Confirmado con capturas del usuario:

- `/profile` General — alias visible, tema preferido. OK.
- `/profile` Seguridad — generador llenando ambos campos, marcadores
  de politica en verde, barra completa "Fuerte", confirmacion coincide.
  OK.
- `/profile` Sesiones — tabla con sesion actual + revocadas. OK.
- `/admin` Crear usuario — UX metro completa, generador funcional,
  confirmacion live. OK.
- `/admin` Cambiar mi contrasena — UX metro completa. OK.

Pendiente de prueba (no verificado porque el servidor solo tenia el
usuario `admin`, y el self-guard oculta las acciones para uno mismo):

- Botones por usuario en la lista — requieren crear un segundo usuario
  para que aparezcan.
- Modales `reset-password`, `change-role`, `delete-user`.
- Validacion del input de confirmacion en `delete-user-modal`.
- PATCH directos de `enabled` y `must_change_password`.

### Bug preexistente identificado (no resuelto)

El signal `user_login_failed` en
[`src/ameli_web/accounts/signals.py`](../src/ameli_web/accounts/signals.py)
llama a `record_audit("login_failed", actor=None, ...)`. La funcion
`record_audit` en
[`src/ameli_web/accounts/services.py`](../src/ameli_web/accounts/services.py)
hace:

```python
return AuditEvent.objects.create(
    actor_username=getattr(actor, "username", None),
    ...
)
```

Con `actor=None`, eso pasa `actor_username=None` a un `CharField` que
es `NOT NULL` en PostgreSQL → `IntegrityError` → 500 en la respuesta
de POST `/login/?next=` cuando el usuario tipea la clave incorrecta.

No introducido por esta sesion (vive desde commits previos al
`9cab8b4` estable). El usuario lo destapo al equivocarse de password
al probar el deploy nuevo.

Patch sugerido (1 linea, sin migracion):

```python
# services.py
return AuditEvent.objects.create(
    actor_username=(getattr(actor, "username", None) or ""),
    target_username=(target_username or ""),
    action=action,
    payload=payload or {},
)
```

Recomendado dejarlo como su propio commit (`fix: tolerate anonymous
actor in record_audit`) en una sesion separada, no mezclar con bloques
de features.

### Estado de tests

`tests/` tiene `test_api.py`, `test_cli.py`, `test_config.py`,
`test_security.py`. No se evaluo la cobertura ni se agregaron tests
para esta sesion. Las acciones nuevas del admin (modales, per-user
actions, JS module extraido) NO tienen tests todavia.

Pendiente recomendado: tests de view-level para
`/admin/users/<u>` PATCH/DELETE y `/admin/users/<u>/reset-password`
POST que validen los happy paths y el self-guard (un superadmin no
deberia poder borrarse a si mismo en backend, no solo en UI — esto
hay que verificar en `delete_user_account` en `services.py`).

### Estado real del servidor al cierre

```
git log --oneline -1
# 0164cee defer inline scripts until app.js is loaded
systemctl status ameli-app-template-dev-api.service
# active (running)
/health  → ok
/api/health  → ok
acceso web externo http://10.100.100.16:18080/ → ok
```

`install.sh` ultima corrida: `OK=19 WARN=0 FAIL=0` sin warnings de
migraciones.

### Orden recomendado para continuar

1. **Cerrar la verificacion del bloque actual**. Crear un usuario
   `tester` desde el form "Crear usuario", recargar y probar los 5
   botones de la tarjeta de `tester`. Confirmar que el modal de delete
   bloquea hasta tipear el username exacto.
2. **Arreglar el bug de `record_audit`** descrito arriba. Commit
   separado.
3. **Decidir si verificar self-guard en backend**. Revisar
   `delete_user_account`, `update_user_account` y `reset_user_password`
   en `services.py` para confirmar que un superadmin no pueda
   borrarse/deshabilitarse a si mismo via API directa (no solo UI).
4. **Promocionar `dev → main`** si el bloque queda OK. Mismo flow que
   se uso antes en esta sesion:
   ```
   git checkout main
   git pull --ff-only origin main
   git cherry-pick fb6b1bf 3e1a929 0164cee
   git push origin main
   git checkout dev
   git reset --hard main
   git push --force-with-lease origin dev
   ```
5. **Bloque siguiente sugerido**: pulir Sesiones tab del profile
   (botones planos vs metro), o ir a la primera app real heredada del
   Template para validar el flujo de copia/renombre.

### Archivos clave para continuar

- [`src/ameli_app/static/js/app.js`](../src/ameli_app/static/js/app.js) (modulo `window.AmeliPassword`)
- [`src/ameli_app/static/css/app.css`](../src/ameli_app/static/css/app.css) (estilos `.admin-user-actions`, password-policy, etc.)
- [`src/ameli_web/templates/accounts/profile.html`](../src/ameli_web/templates/accounts/profile.html)
- [`src/ameli_web/templates/admin/panel.html`](../src/ameli_web/templates/admin/panel.html)
- [`src/ameli_web/templates/base.html`](../src/ameli_web/templates/base.html)
- [`src/ameli_web/accounts/services.py`](../src/ameli_web/accounts/services.py)
- [`src/ameli_web/accounts/signals.py`](../src/ameli_web/accounts/signals.py)
- [`src/ameli_web/admin_views.py`](../src/ameli_web/admin_views.py)
- [`AGENTS.md`](../AGENTS.md)
- [`docs/CODEX_HANDOFF_2026-06-02_TEMPLATE_DEV.md`](CODEX_HANDOFF_2026-06-02_TEMPLATE_DEV.md)

### Comandos utiles de continuidad

Local:

```bash
git log --oneline --decorate -5
git status --short --branch
```

Servidor (despues de cambios solo en templates / JS / CSS, no hace
falta correr `install.sh`):

```bash
cd /opt/ameli-app-template-dev
git fetch origin
git reset --hard origin/dev
systemctl restart ameli-app-template-dev-api.service
journalctl -u ameli-app-template-dev-api.service -n 50 --no-pager
```

Cuando hay cambios de modelos o migraciones, sigue siendo:

```bash
APP_ENV=dev APP_SLUG=ameli-app-template APP_PACKAGE=ameli_app bash scripts/install.sh
```

### Convenciones que vale recordar para la proxima IA

- Rama `dev` para pruebas, `main` para estable; usar cherry-pick lineal
  al promocionar.
- Static + templates no requieren reinstalar — solo `systemctl restart`.
- `CSRF_HEADER_NAME = "HTTP_X_CSRF_TOKEN"`: clientes JS deben enviar
  `x-csrf-token` (case-insensitive).
- Los inline `<script>` dentro de `{% block content %}` corren ANTES
  que el `<script src="app.js">` del final de `base.html`. Cualquier
  uso de `window.AmeliPassword` u otro global del modulo requiere
  envolver en `DOMContentLoaded` o re-arquitectar la carga de scripts.
- El admin nativo de Django sigue en `/django-admin/` como fallback
  cuando algo del shell propio falla.
- Postgres es la base oficial. SQLite solo para desarrollo trivial.

### Conversacion completa

La sesion incluyo, en orden:

1. Lectura del handoff de Codex y diagnostico del clon Debian.
2. Reset del servidor a `ba27f29` y verificacion de `/profile`.
3. Generacion de la migracion `0002` y aplicacion limpia.
4. Promocion `dev → main` con cherry-pick + sync.
5. Limpieza de `origin/master`.
6. Bloque "completar gestion de usuarios en el admin metro" con sus
   tres commits.
7. Debug en vivo del 500 de login (descubierto preexistente) y del
   500 inicial post-deploy (corregido con DOMContentLoaded).
8. Verificacion visual final.
9. Este handoff.
