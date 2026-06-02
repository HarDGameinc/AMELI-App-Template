# Project Structure Standard

Donde debe vivir cada cosa en un proyecto AMELI nuevo o migrado.

## Estructura Objetivo

```text
project/
  src/ameli_<app>/
  config/
  migrations/
  scripts/
  deploy/systemd/
  tests/
  docs/
```

## Ubicacion Por Responsabilidad

### `src/ameli_<app>/`

Codigo Python reutilizable y ejecutable.

- `api.py`
  crea la app FastAPI y expone rutas HTTP.
- `web.py`
  runner o wrapper para servir la app.
- `cli.py`
  comandos operacionales comunes y de dominio.
- `config.py`
  carga `.env`, YAML y defaults.
- `database.py`
  engine, status DB y helpers de persistencia comunes.
- `security.py`
  token/auth base, utilidades de proteccion de rutas.
- `logging_utils.py`
  formato de logs y setup.
- `version.py`
  lectura de `VERSION`.

### `src/ameli_<app>/workers/`

Todo trabajo agendado o de background.

- `capture.py`
  captura, ingesta, polling o fetch principal.
- `maintenance.py`
  purga, backups, compaction, housekeeping.
- `notify.py`
  despacho de alertas, outbox, heartbeat o reintentos.
- futuros modulos:
  `sync.py`, `reindex.py`

### `src/ameli_<app>/templates/`

HTML base del proyecto.

- `dashboard.html`
  vista principal.
- `admin.html`
  shell administrativa comun.
- futuros:
  `reports.html`, `login.html`, `catalog.html`

### `src/ameli_<app>/static/`

Assets locales.

- `css/`
- `js/`

Si el proyecto necesita componentes mas complejos, mantenerlos aqui y no
embebidos dentro de strings Python.

### `config/`

Configuracion versionada de ejemplo.

- `app.yaml.example`
- CSV o YAML de catalogos
- reglas iniciales

No guardar secretos reales aqui.

### `migrations/`

Migraciones Alembic.

- `env.py`
- `versions/`

### `scripts/`

Ciclo de vida operativo.

- `install.sh`
- `update.sh`
- `uninstall.sh`
- `backup.sh`
- `validate_installation.sh`
- `_common.sh`

Todo script nuevo debe entrar aqui, no en la raiz.

### `deploy/systemd/`

Templates de units.

- `<app>-api.service`
- `<app>-worker.service`
- `<app>-worker.timer`
- `<app>-maintenance.service`
- `<app>-maintenance.timer`

Si el proyecto requiere workers especializados, se permiten estas variantes:

- `<app>-capture.service`
- `<app>-capture.timer`
- `<app>-notifier.service`
- `<app>-capture@.service`

Nombres reales finales se renderizan desde scripts segun `APP_ENV`.

### `tests/`

Minimo obligatorio:

- `test_config.py`
- `test_api.py`
- `test_cli.py`
- `test_security.py`
- `conftest.py`

### `docs/`

Documentacion viva del proyecto.

- arquitectura
- operacion
- notas de dominio
- estandarizacion/migracion

## Reglas De Ubicacion

- Nada de logica grande en un unico archivo tipo `app.py` de miles de lineas.
- Nada de HTML grande embebido en strings Python.
- Nada de scripts operacionales en la raiz del repo.
- Nada de systemd final generado a mano fuera de `deploy/systemd/`.
- Nada de secretos reales en repo.
