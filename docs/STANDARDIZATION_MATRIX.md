# Standardization Matrix

Matriz comparativa de los proyectos AMELI actuales versus el estandar objetivo
de `AMELI_APP_TEMPLATE`.

## Resumen Ejecutivo

| Area | Bandwidth | Metro | Notifier | Omega | Starlink | Estandar objetivo |
|---|---|---|---|---|---|---|
| Layout Python | `app/` monolitico | paquete raiz `ameli_metro/` | `src/ameli_notifier/` | `app/` | `app/` | `src/ameli_app/` |
| Config runtime | `.env` tipo key=value | `.env` + env vars | YAML + runtime | YAML ejemplo | YAML + env | `.env` + YAML |
| DB principal | SQLite + cache JSON | PostgreSQL | PostgreSQL o SQLite legacy | PostgreSQL | PostgreSQL + Alembic | PostgreSQL + Alembic |
| API framework | `http.server` custom | FastAPI | servidor HTTP custom | FastAPI | FastAPI | FastAPI |
| Dashboard web | HTML embebido en Python | Jinja2 + static | dashboard server custom | FastAPI + HTML/JS | web separada + API | Jinja2 + static |
| Admin web | no | auth basica, sin admin rico | auth/session + dashboard users | admin CRUD fuerte | admin, roles, auditoria | `/admin` modular |
| CLI | fuerte dentro de un archivo | entrada por modulo | CLI muy rica | CLI + API | CLI rica | CLI base reusable |
| Scripts | muchos, heterogeneos | bastante ordenados | mezclados en raiz y `scripts/` | operativos, concretos | muy completos | set comun |
| systemd | nombres propios por dashboard/capture | `api`, `capturador`, `notifier`, `maintenance` | `dashboard`, `worker` | fuera del repo actual | API/web/capture separados | `api`, `worker`, `maintenance`, con variantes `capture`/`notifier` |
| Tests | 0 | 7 | 0 | 10 | 4 | minimo 5 base |
| CI | no | si | no | no | no | si |

## Hallazgos Principales

### Lo ya convergente

- Todos tienen un flujo operacional parecido:
  `captura o ingesta -> persistencia -> API o dashboard -> operacion`.
- Todos necesitan scripts de ciclo de vida.
- Todos tienen algun concepto de health, status o validacion de instalacion.
- Todos manejan configuracion externa y no solo hardcode.
- Cuatro de cinco ya estan en PostgreSQL o moviendose hacia PostgreSQL.

### Lo hoy divergente

- Hay tres layouts de codigo distintos: `src/`, paquete en raiz y `app/`.
- Los nombres de scripts no son consistentes.
- Los nombres y el alcance de units systemd cambian por proyecto.
- La capa web esta implementada de tres maneras distintas.
- Auth y admin existen en varios proyectos, pero con patrones distintos.
- El nivel de test y CI es desigual.

## Estandarizacion Recomendada Por Area

| Area | Estandarizar | Mantener variable por dominio |
|---|---|---|
| Layout | si | no |
| Scripts | si | no |
| systemd | si | no |
| logging | si | no |
| config/env | si | no |
| CLI base | si | no |
| endpoints health/status | si | no |
| auth base | si | no |
| dashboard shell | si | si, contenido interno |
| admin shell | si | si, CRUD y permisos reales |
| modelo de datos | no | si |
| reglas de negocio | no | si |
| integraciones externas | no | si |
| frecuencia de timers | parcialmente | si |

## Qué Tomar De Cada Proyecto

### AMELI Bandwidth

- Tomar:
  separacion `dev/prod`, validaciones operativas, catalogo CSV, CLI utilitaria.
- No copiar tal cual:
  archivo Python unico y servidor HTTP custom.

### AMELI Metro Status

- Tomar:
  arquitectura modular, tests, CI, deploy multientorno, FastAPI, captura/API/notifier/mantenimiento.
- No copiar tal cual:
  layout en paquete raiz como nuevo default.

### AMELI Notifier

- Tomar:
  layout `src/`, CLI extensa, config YAML rica, auth/session, comandos operacionales.
- No copiar tal cual:
  mezcla de runtime legacy SQLite como base de proyectos nuevos.

### AMELI Omega Receiver

- Tomar:
  admin web fuerte, multi-tenant opcional, seguridad, inventario detectado, pruebas funcionales.
- No copiar tal cual:
  superficie API/admin enorme como requisito minimo de todas las apps.

### AMELI Report Starlink

- Tomar:
  auth, roles, auditoria, paneles separados, reportes, catalogo administrable, scripts robustos.
- No copiar tal cual:
  estructura `app/` y mezcla fuerte de UI con dominio en el mismo modulo.

## Decision Final

El estandar base AMELI debe usar:

- `src/` package layout
- FastAPI
- PostgreSQL + Alembic
- `.env` para runtime y secretos
- YAML/CSV para defaults y catalogos
- scripts comunes
- units systemd comunes
- dashboard shell + admin shell reutilizables
- CLI minima obligatoria
- tests base y CI
