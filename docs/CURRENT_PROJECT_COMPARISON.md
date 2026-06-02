# Current Project Comparison

Comparativa del estado actual de los proyectos AMELI revisados en rama `dev`.

## Tabla Comparativa

| Proyecto | Estructura actual | Web / API | Persistencia | Configuracion | Packaging / Tooling | Operacion | Tests | Estandarizable |
|---|---|---|---|---|---|---|---|---|
| `AMELI Bandwidth` | `app/`, `config/`, `scripts/`, `systemd/` | `http.server` propio en un solo archivo grande | `sqlite3` + JSON cache local | `.env` tipo key/value | sin `pyproject`, sin `src/`, sin CI visible | units estaticas, scripts `prod/dev`, utilidades HA/UFW | sin suite `tests/` | alta en scripts/systemd/config; media-baja en runtime web |
| `AMELI Metro Status` | `src/ameli_metro/`, `config/`, `deploy/systemd/`, `scripts/`, `docs/`, `tests/` | `FastAPI` + `Uvicorn` + `Jinja2` | `PostgreSQL` via `psycopg` + `schema.sql` | `.env` runtime + YAML ejemplo | `pyproject`, `requirements-dev`, `ruff`, `pytest`, CI | units versionadas por entorno, CLI comun, wrappers `workers/` | 7 archivos de test | muy alta; hoy es la mejor base del estandar |
| `AMELI Notifier` | `src/`, `config/`, `scripts/`, `systemd/`, `docs/` + scripts en raiz | dashboard/API propio del paquete, sin FastAPI detectada | `SQLite` + `PostgreSQL` runtime/staging | YAML fuerte (`config.yaml`, `rules.yaml`, `routes.yaml`) + secretos por archivo | `pyproject` simple, sin suite de tests local visible | worker timer, dashboard service, instalacion DEV aislada, backups | sin suite `tests/` | muy alta en config, CLI y operacion; media en web |
| `AMELI Omega Receiver` | `app/`, `scripts/`, `docs/`, `tests/` | `FastAPI` + `Uvicorn` separados en `main.py` y `web.py` + `Jinja2` | `PostgreSQL` via `psycopg2` | YAML (`receiver.yaml`) | sin `pyproject`, `requirements-dev` minimo | units generadas inline desde scripts, API y WEB separadas | 9 tests | alta en stack API/web y seguridad; media en operacion por units inline |
| `AMELI Report Starlink` | `app/`, `config/`, `migrations/`, `scripts/`, `sql/`, `tests/` | `FastAPI` + `Uvicorn`, Web separada con proxy interno | `PostgreSQL` via `psycopg2` + `SQLAlchemy` + `Alembic` | YAML + `.env` + usuarios web en YAML | sin `pyproject`, pero con `pytest.ini`, Alembic, tests | scripts ricos, units generadas desde helpers, auth/roles/auditoria | 2 tests visibles de auth + fixture suite | muy alta en seguridad/admin/migraciones; media-alta en estructura |

## Stack Tecnologico Real

| Capa | Bandwidth | Metro | Notifier | Omega | Starlink | Decision de estandarizacion |
|---|---|---|---|---|---|---|
| Lenguaje | Python | Python | Python | Python | Python | estandarizar en Python 3.11+ |
| Layout repo | `app/` | `src/` | `src/` | `app/` | `app/` | converger a `src/` |
| API/web | `http.server` custom | `FastAPI` | runtime web propio | `FastAPI` | `FastAPI` | converger a `FastAPI` |
| Runner | `python archivo.py` | `uvicorn` / `python -m` | CLI instalable | `uvicorn` | `uvicorn` | converger a CLI + `uvicorn` |
| Templates | HTML embebido / archivo mixto | `Jinja2` + `templates/static` | dashboard propio | `Jinja2` | HTML/admin separados | converger a `templates/` + `static/` |
| DB principal | SQLite | PostgreSQL | SQLite/PostgreSQL mixto | PostgreSQL | PostgreSQL | estandar principal PostgreSQL; SQLite solo excepcion |
| Driver DB | `sqlite3` | `psycopg` v3 | `sqlite3` + `psycopg2` | `psycopg2` | `psycopg2` + SQLAlchemy | converger a PostgreSQL y idealmente un solo driver |
| Migraciones | no | `schema.sql` | propias / init | no formal | Alembic | converger a Alembic |
| Config runtime | env | env | YAML | YAML | YAML + env | converger a `.env` + YAML |
| Auth | token API | basic auth opcional | token/sesion/dashboard auth | token header | token + users/roles | converger a capa comun de auth y RBAC opcional |
| Notificaciones | no | Telegram/Teams/webhook | Teams/Telegram/SMTP | no | no de alertas externas | hacer modulo reutilizable, opcional |
| systemd | estatico | templates versionados | estatico | inline en scripts | inline desde helper | converger a templates versionados |
| QA | validaciones bash | pytest + ruff + CI | validacion bash fuerte | pytest | pytest parcial | converger a `pytest + ruff + validate_installation.sh` |

## Lo Que Ya Podemos Estandarizar

- Estructura de repo:
  - `src/<package>/`
  - `config/`
  - `deploy/systemd/`
  - `scripts/`
  - `tests/`
  - `docs/`
  - `migrations/`
- Stack web/API:
  - `FastAPI`
  - `Uvicorn`
  - `Jinja2`
- Config:
  - `.env` para runtime/secretos
  - YAML para catalogos, features y reglas
- DB:
  - PostgreSQL como default
  - Alembic como migracion
- Operacion:
  - `_common.sh`
  - `install.sh`, `install_dev.sh`, `update.sh`, `backup.sh`, `validate_installation.sh`, `uninstall.sh`
  - naming `systemd` por entorno y rol
- Tooling:
  - `pyproject.toml`
  - `requirements.txt`
  - `requirements-dev.txt`
  - `ruff`
  - `pytest`
- Aplicacion:
  - CLI comun
  - `/health`, `/api/health`
  - dashboard/admin shell base

## Lo Que Debe Quedar Como Variacion De Dominio

- modelo de datos especifico
- payload de ingesta
- reglas de negocio
- workers especiales
- canales opcionales
- reportes XLSX/exports
- catalogos y correlaciones

## Evaluacion Por Prioridad De Migracion

| Proyecto | Prioridad | Motivo |
|---|---|---|
| `AMELI Metro Status` | 1 | ya esta cerca del estandar y sirve como repo piloto |
| `AMELI Omega Receiver` | 2 | comparte FastAPI + PostgreSQL + Jinja2, pero hay que sacar units inline |
| `AMELI Report Starlink` | 3 | muy valioso por auth, roles, auditoria y Alembic |
| `AMELI Notifier` | 4 | muy fuerte en CLI/config, pero su web y runtime mixto requieren mas criterio |
| `AMELI Bandwidth` | 5 | es el mas distinto por `http.server` + SQLite y archivo monolitico |

## Conclusiones Practicas

1. La plataforma base comun ya existe conceptualmente en 4 de 5 proyectos.
2. `Bandwidth` es la excepcion arquitectonica principal.
3. `Metro` es hoy el mejor candidato para fijar el contrato del estandar.
4. `Starlink` aporta la capa de seguridad/admin mas madura.
5. `Omega` aporta una separacion clara `api/web` util para el template.
6. `Notifier` aporta la mejor capa de config rica, CLI y operacion multicanal.
