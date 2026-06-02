# Primera instalacion Django-first

## Objetivo

Este documento deja el flujo base para levantar por primera vez una app creada
desde `AMELI_APP_TEMPLATE`, tanto en desarrollo local como en un servidor
Debian con PostgreSQL y systemd.

La idea es que la primera instalacion siempre deje disponibles estas rutas:

- `/`
- `/login`
- `/profile`
- `/admin`
- `/health`
- `/api/health`
- `/docs`
- `/redoc`

## Resumen de arquitectura

- Runtime web oficial: `python -m ameli_app.api`
- Capa web oficial: `Django ASGI`
- Base recomendada para servidor: `PostgreSQL`
- Base minima para desarrollo local: `SQLite`
- Entry point de gestion Django: `manage.py`
- Entry point CLI: `ameli-app`

## Prerrequisitos

### Local

- Python `3.11+`
- `pip`
- Git

### Debian

- Debian `12+` o `13`
- acceso `root`
- `git`
- `python3`, `python3-venv`, `python3-pip`
- `postgresql`
- `systemd`

## Variables importantes

Las variables minimas para una primera instalacion son estas:

```env
APP_ENV=dev
APP_SYSTEMD_PROFILE=api-worker-maintenance
AMELI_APP_DJANGO_SECRET_KEY=change-this-django-secret
AMELI_APP_AUTH_ENABLED=true
AMELI_APP_DOCS_ENABLED=true
AMELI_APP_REDOC_ENABLED=true
AMELI_APP_ADMIN_ENABLED=true
DATABASE_URL=postgresql+psycopg://ameli_app:secret@127.0.0.1:5432/ameli_app
```

Opcionales pero recomendadas para dejar el acceso listo desde el principio:

```env
AMELI_APP_BOOTSTRAP_ADMIN_USER=admin
AMELI_APP_BOOTSTRAP_ADMIN_PASSWORD=ChangeThisNow!1?
```

## Quick start local

### 1. Crear entorno e instalar dependencias

```bash
python -m venv .venv
. .venv/bin/activate
pip install -r requirements.txt -r requirements-dev.txt
pip install -e .
```

### 2. Preparar `.env`

Tomar `.env.example` como base y definir al menos:

```env
APP_ENV=dev
APP_CONFIG=config/app.yaml.example
AMELI_APP_DJANGO_SECRET_KEY=local-dev-secret
AMELI_APP_SQLITE_PATH=/ruta/absoluta/django-dev.sqlite3
DATABASE_URL=
```

Para local, `AMELI_APP_SQLITE_PATH` permite correr sin PostgreSQL.

### 3. Migrar y validar

```bash
python manage.py migrate --noinput
python manage.py check
ameli-app version
ameli-app config-check --config config/app.yaml.example
ameli-app db-status --config config/app.yaml.example
```

### 4. Crear superadmin inicial

```bash
ameli-app bootstrap-admin \
  --config config/app.yaml.example \
  --username admin \
  --password 'ChangeThisNow!1?' \
  --must-change-password
```

### 5. Levantar la app

```bash
python -m ameli_app.api
```

### 6. Verificar

- `http://127.0.0.1:18080/`
- `http://127.0.0.1:18080/login`
- `http://127.0.0.1:18080/admin`
- `http://127.0.0.1:18080/docs`
- `http://127.0.0.1:18080/redoc`
- `http://127.0.0.1:18080/api/health`

## Primera instalacion Debian

Este ejemplo asume:

- repo clonado en `/opt/ameli-app-dev`
- entorno `dev`
- app final corriendo con systemd
- PostgreSQL local

### 1. Clonar el repo

```bash
git clone <repo> /opt/ameli-app-dev
cd /opt/ameli-app-dev
```

### 2. Crear base y usuario PostgreSQL

```bash
sudo -u postgres psql
```

Dentro de `psql`:

```sql
CREATE USER ameli_app_dev WITH PASSWORD 'change-this-db-password';
CREATE DATABASE ameli_app_dev OWNER ameli_app_dev;
\q
```

### 3. Preparar `app.env`

Crear o editar `/etc/ameli-app-dev/app.env` con algo como:

```env
APP_ENV=dev
APP_SYSTEMD_PROFILE=api-worker-maintenance
AMELI_APP_DJANGO_SECRET_KEY=replace-with-long-random-secret
AMELI_APP_AUTH_ENABLED=true
AMELI_APP_DOCS_ENABLED=true
AMELI_APP_REDOC_ENABLED=true
AMELI_APP_ADMIN_ENABLED=true
AMELI_APP_SESSION_COOKIE_SECURE=false
AMELI_APP_BOOTSTRAP_ADMIN_USER=admin
AMELI_APP_BOOTSTRAP_ADMIN_PASSWORD=ChangeThisNow!1?
DATABASE_URL=postgresql+psycopg://ameli_app_dev:change-this-db-password@127.0.0.1:5432/ameli_app_dev
```

### 4. Preparar `app.yaml`

Copiar `config/app.yaml.example` hacia la ruta esperada por la instalacion
si el proyecto final usa una ruta dedicada, por ejemplo:

```bash
mkdir -p /etc/ameli-app-dev
cp config/app.yaml.example /etc/ameli-app-dev/app.yaml
```

### 5. Instalar

Como `root`:

```bash
cd /opt/ameli-app-dev
APP_ENV=dev bash scripts/install.sh
```

El instalador:

- crea venv
- instala dependencias
- ejecuta `manage.py migrate`
- ejecuta `manage.py check`
- bootstrapea el superadmin si las variables existen
- renderiza units systemd
- habilita unidades segun `APP_SYSTEMD_PROFILE`

### 6. Validar instalacion

```bash
cd /opt/ameli-app-dev
bash scripts/validate_installation.sh
```

Revision manual recomendada:

```bash
systemctl status ameli-app-dev-api.service --no-pager -l
curl -s http://127.0.0.1:18080/health
curl -s http://127.0.0.1:18080/api/health
```

Y luego abrir:

- `http://<host>:18080/`
- `http://<host>:18080/login`
- `http://<host>:18080/docs`
- `http://<host>:18080/redoc`

## Primera actualizacion

Para una actualizacion normal:

```bash
cd /opt/ameli-app-dev
bash scripts/update.sh
```

Eso vuelve a:

- respaldar
- copiar codigo
- reinstalar dependencias
- correr migraciones
- ejecutar `manage.py check`
- reiniciar los servicios habilitados

## Checklist de aceptacion

La primera instalacion se considera sana si:

- `manage.py check` pasa
- `ameli-app version` responde
- `ameli-app config-check` responde
- `ameli-app db-status` responde
- existe login funcional
- el superadmin puede entrar a `/profile`
- el superadmin puede entrar a `/admin`
- `/docs` y `/redoc` cargan
- `/api/health` responde `ok`

## Problemas comunes

### `/admin` o `/profile` no cargan

Revisar:

- que `manage.py migrate --noinput` haya corrido
- que `AMELI_APP_DJANGO_SECRET_KEY` exista
- que la base indicada en `DATABASE_URL` sea accesible

### No existe superadmin

Ejecutar manualmente:

```bash
ameli-app bootstrap-admin \
  --config /etc/ameli-app-dev/app.yaml \
  --env-file /etc/ameli-app-dev/app.env \
  --username admin \
  --password 'ChangeThisNow!1?' \
  --must-change-password
```

### `/docs` o `/redoc` no aparecen

Revisar:

- `AMELI_APP_DOCS_ENABLED=true`
- `AMELI_APP_REDOC_ENABLED=true`

### En local no hay PostgreSQL

Usar SQLite temporal con:

```env
AMELI_APP_SQLITE_PATH=/ruta/absoluta/django-dev.sqlite3
DATABASE_URL=
```

## Documento canonico para continuidad

Para arquitectura, reglas y continuidad entre equipos o IAs, usar:

- `AGENTS.md`
