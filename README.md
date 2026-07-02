# AMELI App Template

Plantilla base Django-first para crear aplicaciones AMELI con usuarios reales,
sesiones web, perfil, administración, auditoría, documentación OpenAPI y
operación estándar con scripts y systemd.

La plantilla está pensada para copiarse y renombrarse. No contiene lógica de
dominio; entrega una base de plataforma reusable para apps públicas o internas
que necesiten autenticación, panel administrativo y documentación API desde el
día 1.

## Política de base de datos

- `PostgreSQL` es la base oficial del estándar AMELI.
- `SQLite` se mantiene solo como fallback local para desarrollo rápido o demos
  sin infraestructura externa.
- Para staging, QA y producción, los ejemplos y el flujo principal asumen
  `DATABASE_URL` apuntando a PostgreSQL.

## Stack incluido

- Python 3.11+ (CI prueba 3.11 · 3.12 · 3.13 · 3.14)
- Layout `src/`
- Django ASGI + Uvicorn
- PostgreSQL como base oficial + SQLite local opcional
- Configuración híbrida: `.env` para secretos/runtime y YAML para defaults
- CLI operacional
- Bootstrap de superadmin inicial
- `/docs`, `/redoc` y `/openapi.json`
- Login/logout, profile, admin, auditoría y política estándar de contraseña
- Worker/capturador y mantenimiento base
- Templates systemd para `api`, `web`, `worker`, `capture`, `notifier` y `maintenance`
- Scripts `install`, `update`, `uninstall`, `backup` y `validate_installation`
- Helper `scripts/_common.sh` para multientorno y render de units
- Pytest + Ruff

## Uso rápido

1. Copiar esta carpeta para una app nueva.
2. Renombrar:

   ```text
   AMELI_APP_TEMPLATE -> AMELI Nueva App
   src/ameli_app -> src/ameli_nueva_app
   ameli-app -> ameli-nueva-app
   ameli_app -> ameli_nueva_app
   ```

3. Actualizar `pyproject.toml`, `README.md`, `VERSION`, `.env.example` y
   `config/app.yaml.example`.
4. Elegir el perfil `APP_SYSTEMD_PROFILE` según la topología de la app:

   ```text
   api-worker-maintenance
   api-web
   api-web-worker-maintenance
   web-worker
   web-capture
   api-web-capture
   api-capture-notifier-maintenance
   ```

5. Instalar dependencias:

   ```bash
   python -m venv .venv
   . .venv/bin/activate
   pip install -r requirements.txt -r requirements-dev.txt
   pip install -e .
   ```

6. Validar:

   ```bash
   ameli-app version
   ameli-app config-check --config config/app.yaml.example
   ameli-app db-status --config config/app.yaml.example
   pytest
   ruff check .
   ruff format --check .
   ```

7. Aplicar migraciones y validar Django con PostgreSQL:

   ```bash
   export DATABASE_URL="postgresql+psycopg://ameli_app:secret@127.0.0.1:5432/ameli_app"
   python manage.py migrate
   python manage.py check
   ```

8. Si no tienes PostgreSQL local, usa el fallback SQLite solo para desarrollo:

   ```bash
   export DATABASE_URL=
   export AMELI_APP_SQLITE_PATH="${PWD}/django-dev.sqlite3"
   python manage.py migrate
   python manage.py check
   ```

9. Levantar el servicio web oficial:

   ```bash
   python -m ameli_app.api
   ```

10. Bootstrapear el superadmin inicial:

   ```bash
   ameli-app bootstrap-admin --config config/app.yaml.example --username admin --password 'ChangeThisNow!1?' --must-change-password
   ```

## Primera instalación guiada

Para un recorrido completo de primera instalación, incluyendo:

- quick start oficial con PostgreSQL
- fallback local con SQLite
- primera instalación Debian con PostgreSQL y systemd
- bootstrap inicial del superadmin
- validación post-instalación
- update inicial y problemas comunes

usar:

- `docs/FIRST_INSTALL_DJANGO.md`

## Rutas base

- `GET /health`: health público liviano.
- `GET /api/health`: health API detallado.
- `GET /`: dashboard base.
- `GET /login`: acceso web.
- `POST /logout`: cierre de sesión.
- `GET /profile`: autoservicio de cuenta.
- `GET /admin`: panel admin base.
- `GET /docs`: Swagger UI.
- `GET /redoc`: ReDoc.
- `GET /openapi.json`: esquema OpenAPI.

## CLI base

```bash
ameli-app version
ameli-app config-check --config config/app.yaml.example
ameli-app db-status --config config/app.yaml.example
ameli-app worker-once --config config/app.yaml.example
ameli-app notify-once --config config/app.yaml.example
ameli-app maintenance --config config/app.yaml.example
ameli-app bootstrap-admin --config config/app.yaml.example --username admin --password 'ChangeThisNow!1?' --must-change-password
ameli-app create-user --config config/app.yaml.example --username viewer --password 'ViewerPass!1?' --role public
ameli-app list-users --config config/app.yaml.example
```

## Convenciones AMELI

- La rama `dev` es para pruebas y staging.
- La rama `main` es estable/productiva.
- `APP_ENV=prod|dev` separa rutas, puertos, base de datos y unidades systemd.
- `APP_SYSTEMD_PROFILE` define qué roles systemd se habilitan por instancia.
- Los secretos no se versionan.
- Los scripts deben ser idempotentes y preservar configuración existente.
- Los endpoints mutables o administrativos deben requerir sesión.
- Si la app expone dashboard público con cuentas, el primer superadmin se crea
  por script y luego administra usuarios desde `/admin`.

## Documento canónico

- `AGENTS.md`
