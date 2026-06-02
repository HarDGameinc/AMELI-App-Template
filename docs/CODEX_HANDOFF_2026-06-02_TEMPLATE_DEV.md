## AMELI App Template handoff

Fecha: `2026-06-02`

Este documento resume el estado real del Template Django-first, el despliegue
de prueba en Debian y el punto exacto donde debe continuar otra IA o equipo.

### Estado general

- Repo: `HarDGameinc/AMELI-App-Template`
- Rama estable: `main`
- Rama de trabajo actual: `dev`
- Commit actual esperado en `dev`: `ba27f29`
  - `finish metro-style profile forms in template`

### Arquitectura vigente

- Web oficial: `Django ASGI`
- Entry point oficial:
  - `python -m ameli_app.api`
- Paquete de dominio/CLI:
  - `src/ameli_app`
- Capa web oficial:
  - `src/ameli_web`
- Base oficial del estándar:
  - `PostgreSQL`
- Fallback local de conveniencia:
  - `SQLite`

### Qué ya quedó funcionando

- `/`
- `/login`
- `/logout`
- `/profile`
- `/admin`
- `/health`
- `/api/health`
- `/docs`
- `/redoc`
- `/openapi.json`
- bootstrap de superadmin
- sesiones persistentes
- auditoría
- perfil con tabs
- admin base con shell visual tipo Metro

### Commits relevantes recientes

- `11d9a56`
  - bootstrap inicial del Template Django-first y guía de instalación
- `0204e06`
  - limpieza de baseline y normalización PostgreSQL
- `4e1fd90`
  - soporte en Django para `DATABASE_URL=postgresql+psycopg://...`
- `8b491f8`
  - port visual de Metro a `login` y `admin`
- `ba27f29`
  - cierre visual de `profile` con formularios estilo Metro, generación de contraseña, validación visual y política visible

### Estado local esperado

En este workspace local:

- rama actual: `dev`
- `origin/dev` apunta a `ba27f29`

Archivos clave del último cambio:

- `src/ameli_web/accounts/forms.py`
- `src/ameli_web/templates/accounts/profile.html`

Indicadores del cambio nuevo en `profile.html`:

- `profile-password-generate`
- `password-policy-card`
- `data-password-toggle`
- inputs con clase `modal-input`

### Despliegue Debian de prueba

Servidor usado:

- Debian 13
- usuario `root`
- UFW activo
- DeployKey configurada

Ruta del clon:

- `/opt/ameli-app-template-dev`

Config:

- `/etc/ameli-app-template-dev/app.env`
- `/etc/ameli-app-template-dev/app.yaml`

Servicio:

- `ameli-app-template-dev-api.service`

Puerto:

- `18080`

Host expuesto:

- `0.0.0.0`

Base PostgreSQL de prueba:

- base: `ameli_app_template_dev`
- usuario: `ameli_app_template_dev`

### Estado real del servidor al cierre de esta conversación

La instalación en Debian está sana:

- `install.sh`: OK
- `validate_installation.sh` con contexto `APP_ENV=dev ...`: OK
- `systemctl status ameli-app-template-dev-api.service`: activo
- `/health`: OK
- `/api/health`: OK
- acceso web externo por `http://10.100.100.16:18080/`: OK

### Problema pendiente exacto

El servidor todavía está mostrando la versión antigua de `profile`, aunque el
repo local ya tiene el cambio nuevo.

Diagnóstico confirmado:

- En el servidor, `git log --oneline -1` devolvió:
  - `8b491f8 (HEAD -> dev, origin/dev) port metro visual system to template admin and login`
- `grep -n "profile-password-generate" src/ameli_web/templates/accounts/profile.html`
  - sin resultados
- `grep -n "password-policy-card" src/ameli_web/templates/accounts/profile.html`
  - sin resultados

Esto confirma que el clon del servidor no ha recibido todavía `ba27f29`.

### Causa del problema

El clon inicial del servidor se hizo con:

```bash
git clone --branch main --single-branch ...
```

Eso dejó al remoto configurado para seguir solo `main`. Después, aunque se creó
una rama local `dev`, `git fetch origin` siguió trayendo solo `main`. Por eso
`origin/dev` en el servidor quedó congelado en `8b491f8`.

### Cómo debe retomarse en el servidor

Desde `/opt/ameli-app-template-dev`:

```bash
git remote set-branches origin main dev
git fetch origin
git log --oneline origin/dev -1
git reset --hard origin/dev
```

El resultado correcto esperado debe ser:

```text
ba27f29 finish metro-style profile forms in template
```

Luego reinstalar/reiniciar:

```bash
APP_ENV=dev APP_SLUG=ameli-app-template APP_PACKAGE=ameli_app bash scripts/install.sh
systemctl restart ameli-app-template-dev-api.service
```

Y verificar:

```bash
git log --oneline -1
grep -n "profile-password-generate" src/ameli_web/templates/accounts/profile.html
grep -n "password-policy-card" src/ameli_web/templates/accounts/profile.html
```

### Qué debería verse después del fix

En `/profile`:

- pestaña `General` con inputs estilizados tipo Metro
- pestaña `Seguridad` con:
  - mostrar/ocultar contraseña
  - generación automática
  - confirmación
  - política visible
  - barra de robustez
- tarjetas y formularios consistentes con `login` y `admin`

### Warning conocido no resuelto todavía

Durante `manage.py migrate` aparece:

```text
Your models in app(s): 'accounts' have changes that are not yet reflected in a migration
```

No bloquea instalación ni runtime, pero debe revisarse después.

Pendiente recomendado:

- inspeccionar `accounts` y generar migración real si corresponde

### Orden recomendado para continuar

1. Corregir el tracking/fetch del clon Debian para que traiga `ba27f29`
2. Verificar visualmente el nuevo `profile`
3. Revisar el warning de migraciones de `accounts`
4. Si todo queda bien en `dev`, decidir promoción a `main`

### Archivos clave para continuar

- `AGENTS.md`
- `README.md`
- `docs/FIRST_INSTALL_DJANGO.md`
- `src/ameli_web/templates/accounts/profile.html`
- `src/ameli_web/accounts/forms.py`
- `src/ameli_web/templates/admin/panel.html`
- `src/ameli_web/templates/accounts/login.html`
- `src/ameli_app/static/css/app.css`
- `src/ameli_app/static/js/app.js`

### Comandos útiles de continuidad

Local:

```bash
git log --oneline --decorate -5
git status --short --branch
```

Servidor:

```bash
cd /opt/ameli-app-template-dev
git remote show origin
git branch -a
git log --oneline -3
systemctl status ameli-app-template-dev-api.service --no-pager -l
curl -s http://127.0.0.1:18080/api/health
```
