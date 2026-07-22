# Primera instalación Django-first

## Objetivo

Este documento deja el flujo base para levantar por primera vez una app creada
desde `AMELI_APP_TEMPLATE`, tanto en desarrollo local como en un servidor
Debian con PostgreSQL y systemd.

La idea es que la primera instalación siempre deje disponibles estas rutas:

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
- Base oficial del estándar: `PostgreSQL`
- Fallback local de conveniencia: `SQLite`
- Entry point de gestión Django: `manage.py`
- Entry point CLI: `ameli-app`

## Política de base de datos

La plantilla mantiene soporte técnico para `SQLite`, pero solo para estos
casos:

- desarrollo local rápido
- demos
- validaciones sin infraestructura externa

Para cualquier instalación real de referencia, staging, QA o producción, el
camino oficial es `PostgreSQL`.

## Prerrequisitos

### Local

- Python `3.11+` (CI prueba 3.11 · 3.12 · 3.13 · 3.14)
- `pip`
- Git

### Debian

- Debian `12+` o `13`
- acceso `root`
- `git`
- `python3`, `python3-venv`, `python3-pip`
- `postgresql`
- `systemd`
- `caddy` (recomendado como reverse-proxy TLS; opcional para deploys internos)

## Quickstart — Debian con `install.sh` (RECOMENDADO)

Instalación estándar en un servidor Debian orientado a producción. El
resto de la guía (secciones "Quick start local", "Primera instalación
Debian" manual, "Fallback con SQLite") queda como referencia y
troubleshooting; el flujo canónico para un despliegue nuevo es este:

> **Todo esto corre como `root`, sin `sudo`.** El servidor de referencia no
> tiene el binario instalado: un comando con `sudo` falla con
> `sudo: orden no encontrada`. Ver `AGENTS.md` → "Operating conventions".

```bash
# 1. Provisionar el host
apt update
apt install -y postgresql caddy git

# 2. Clonar el repo en el ULTIMO TAG PROMOVIDO -- no en `main` pelado.
#    Una feature recien mergeada a `dev` puede no estar en `main` todavia,
#    y un clone de `main` te deja con un installer viejo sin aviso.
git clone https://github.com/HarDGameinc/AMELI-App-Template.git \
    /opt/ameli-app-template-prod
cd /opt/ameli-app-template-prod
git checkout "$(git tag --sort=-v:refname | head -1)"
git describe --tags   # confirma que instalas lo que crees

# 3. Crear la base
su - postgres -c "createuser --pwprompt ameli_app_prod"
su - postgres -c "createdb -O ameli_app_prod ameli_app_prod"

# 4. Instalar. Auto-genera las 3 keys crypto y siembra ALLOWED_HOSTS /
#    TRUSTED_PROXIES con valores conservadores, renderiza app.yaml para
#    esta instancia, monta systemd, corre migrate, valida el layout y
#    hace smoke a /health.
APP_ENV=prod bash scripts/install.sh

# 5. Apuntar la DATABASE_URL (el install la dejo vacia)
sed -i "s|^DATABASE_URL=.*|DATABASE_URL=postgresql+psycopg://ameli_app_prod:PASSWORD@127.0.0.1:5432/ameli_app_prod|" \
    /etc/ameli-app-template-prod/app.env
APP_ENV=prod bash scripts/install.sh   # idempotente: re-corre migrate

# 6. Afinar lo que no se puede generar: acotar hosts/proxies al dominio
#    real, SMTP y superadmin. Wizard interactivo:
/opt/ameli-app-template-prod/.venv/bin/ameli-app \
    --env-file /etc/ameli-app-template-prod/app.env \
    configure

# 7. TLS: copiar el snippet de Caddy y reemplazar el hostname
cp /opt/ameli-app-template-prod/deploy/caddy/Caddyfile.example \
    /etc/caddy/Caddyfile
$EDITOR /etc/caddy/Caddyfile   # reemplaza __HOSTNAME__ por el real
systemctl reload caddy

# 8. Cerrar el circuito TLS del lado app (indica a Django que hay proxy TLS)
echo "AMELI_APP_SECURE_PROXY_SSL_HEADER=X-Forwarded-Proto=https" \
    >> /etc/ameli-app-template-prod/app.env
systemctl restart ameli-app-template-prod-api.service

# 9. Verificar
curl -sf https://APP_HOSTNAME/health | jq .
APP_ENV=prod bash scripts/validate_installation.sh
```

> **Instalando junto a otras apps AMELI en el mismo host?** Los defaults
> (`APP_SLUG=ameli-app`, puertos 8080/8081) colisionan. Revisá `ss -tlnp`
> y forzá `APP_SLUG=` y `AMELI_APP_API_PORT=` / `AMELI_APP_WEB_PORT=`
> antes de correr `install.sh`.

### Qué hace `install.sh` por vos (no manual)

- Instala paquetes Debian del build (`python3-venv`, `build-essential`,
  `libpq-dev`, `libjpeg-dev`).
- Crea el usuario del sistema `ameli-app-template-prod` (uid dedicado).
- Layouta `/opt`, `/etc`, `/var/lib`, `/var/log` y `/var/backups`.
- Copia el árbol del proyecto (excluye `.git`, `.venv`, `__pycache__`).
- Crea `.env` desde `.env.example` **y auto-genera idempotente las tres
  keys criptográficas** que los guards de prod requieren
  (`AMELI_APP_DJANGO_SECRET_KEY`, `AMELI_APP_AUDIT_HMAC_KEY`,
  `AMELI_APP_MFA_ENCRYPTION_KEY`) — nunca sobrescribe si ya están.
  Ver [`DECISIONS.md`](DECISIONS.md) #10 para la justificación.
- Crea el venv desde `requirements.lock` con `--require-hashes` (ASVS
  V14.2.3).
- Corre `migrate` + `manage.py check`.
- Renderiza y habilita los units systemd según `APP_SYSTEMD_PROFILE`.
- **Smoke post-install**: `validate_installation.sh` + `curl /health`;
  sale distinto de cero si algo falla (no queda instalación silenciosa
  a medias).

### Qué sigue siendo decisión del operador (`ameli-app configure`)

- **`ALLOWED_HOSTS`** — comma-separated de hostnames que responde este
  deploy. Con auto-sugerencia basada en `socket.gethostname()`.
- **`TRUSTED_PROXIES`** — REMOTE_ADDR del reverse-proxy. Default sano:
  `127.0.0.1` si Caddy corre en el mismo host.
- **SMTP** (opcional) — host/puerto/user/password/from. Si dejás
  `EMAIL_HOST` vacío, se mantiene el backend `console` (útil en internal
  deploys que no mandan mails externos).
- **Superadmin bootstrap** — usuario + password inicial. `configure`
  llama internamente al mismo `bootstrap_superadmin` que
  `bootstrap-admin`.

### Non-interactive (CI / provisioning automatizado)

`ameli-app configure --yes` lee los mismos valores desde
`AMELI_APP_CONFIGURE_*` env vars (`ALLOWED_HOSTS`, `TRUSTED_PROXIES`,
`ADMIN_USER`, `ADMIN_PASSWORD`, opcionalmente los `EMAIL_*`). Si falta
alguno de los requeridos, exit code `2` con la lista exacta de qué
setear — nunca deja el deploy medio-configurado.

```bash
AMELI_APP_CONFIGURE_ALLOWED_HOSTS=app.example.com \
AMELI_APP_CONFIGURE_TRUSTED_PROXIES=127.0.0.1 \
AMELI_APP_CONFIGURE_ADMIN_USER=admin \
AMELI_APP_CONFIGURE_ADMIN_PASSWORD='ChangeThisNow!1?' \
/opt/ameli-app-template-prod/.venv/bin/ameli-app \
    --env-file /etc/ameli-app-template-prod/app.env configure --yes
```

Exit codes: `0` todo aplicado; `2` faltan variables requeridas (nada se
escribe); `1` el env file **sí** se escribió pero Django todavía no puede
bootear, así que el superadmin quedó pendiente — el JSON de salida trae
`bootstrap_admin_error` con la causa y `hint` con el comando exacto para
terminar. Ese caso es casi siempre la base de datos inalcanzable.

## Variables importantes

Las variables mínimas para una primera instalación son estas:

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

## Quick start local oficial con PostgreSQL

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
DATABASE_URL=postgresql+psycopg://ameli_app:secret@127.0.0.1:5432/ameli_app
```

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

## Fallback local con SQLite

Si todavía no tienes PostgreSQL disponible, puedes levantar la plantilla en
local con SQLite de forma temporal:

```env
APP_ENV=dev
APP_CONFIG=config/app.yaml.example
AMELI_APP_DJANGO_SECRET_KEY=local-dev-secret
DATABASE_URL=
AMELI_APP_SQLITE_PATH=/ruta/absoluta/django-dev.sqlite3
```

Y luego:

```bash
python manage.py migrate --noinput
python manage.py check
python -m ameli_app.api
```

Este modo no reemplaza el camino oficial con PostgreSQL; solo acelera el
arranque local.

## Primera instalación Debian

> **Nota**: la sección "Quickstart — Debian con `install.sh`" arriba
> supersede este walkthrough. Los pasos manuales de abajo quedan como
> **referencia** para troubleshooting o para adaptar el flujo a
> escenarios especiales (deploy sin `install.sh`, host sin systemd, etc.).
> Para una instalación nueva estándar, seguí el Quickstart.

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
su - postgres -c psql
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

Copiar `config/app.yaml.example` hacia la ruta esperada por la instalación si
el proyecto final usa una ruta dedicada, por ejemplo:

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
- habilita unidades según `APP_SYSTEMD_PROFILE`

En este flujo, `DATABASE_URL` debe apuntar a PostgreSQL. SQLite no se considera
la base esperada para una instalación Debian real.

### 6. Validar instalación

`validate_installation.sh` **defaultea a `APP_ENV=prod`**. En una
instalación `dev` hay que pasarle `APP_ENV=dev`, si no chequea la
instancia prod (paths y units `*-prod-*` que no existen) y reporta FAIL
espurios:

```bash
cd /opt/ameli-app-dev
APP_ENV=dev bash scripts/validate_installation.sh
```

Revisión manual recomendada:

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

## Primera actualización

Para una actualización normal:

```bash
cd /opt/ameli-app-dev
bash scripts/update.sh
```

Eso vuelve a:

- respaldar
- copiar código
- reinstalar dependencias
- correr migraciones
- ejecutar `manage.py check`
- reiniciar los servicios habilitados

## Checklist de aceptación

La primera instalación se considera sana si:

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

Usar SQLite temporal solo como fallback con:

```env
AMELI_APP_SQLITE_PATH=/ruta/absoluta/django-dev.sqlite3
DATABASE_URL=
```

## Documento canónico para continuidad

Para arquitectura, reglas y continuidad entre equipos o IAs, usar:

- `AGENTS.md`
