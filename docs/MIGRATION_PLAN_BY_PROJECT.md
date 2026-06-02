# Migration Plan By Project

Plan de migracion sugerido repo por repo para converger al estandar AMELI.

## Orden Recomendado

1. Metro Status
2. Omega Receiver
3. Report Starlink
4. Notifier
5. Bandwidth

## Fases Comunes

### Fase 1: Tooling y forma

- agregar o normalizar `pyproject.toml`
- normalizar `requirements-dev.txt`
- agregar `ruff` y `pytest`
- homologar estructura docs/tests/scripts

### Fase 2: Runtime comun

- homologar `.env` + YAML
- introducir `config.py` estandar
- introducir CLI base comun
- introducir health endpoints comunes

### Fase 3: Operacion comun

- mover scripts al set estandar
- renderizar systemd desde templates
- unificar nombres de servicios
- unificar validacion post-install
- aplicar contrato definido en `docs/SCRIPTS_AND_SYSTEMD_STANDARD.md`

### Fase 4: Web/admin comun

- mover dashboard a templates/static
- aplicar shell comun de dashboard
- aplicar shell comun de admin
- portar auth/audit/catalog segun aplique

### Fase 5: Dominio

- mantener reglas y modelos propios
- portar modulos de dominio a la nueva estructura
- limpiar excepciones heredadas

## Plan Por Repo

### Metro Status

Objetivo:
usar Metro como primer piloto porque ya tiene arquitectura modular, tests,
FastAPI y CI.

Mejoras:

- mover de paquete en raiz a `src/` en una fase separada
- alinear scripts y nombres systemd al estandar
- migrar units para usar usuario dedicado y hardening minimo comun
- extraer shell web comun de dashboard
- convertir auth basica en modulo reusable
- formalizar packaging con `pyproject` completo, entrypoints y `VERSION`

### Omega Receiver

Objetivo:
usar Omega como piloto de admin web y catalogo CRUD.

Mejoras:

- separar mejor `main.py` grande en modulos de API/admin
- mover UI admin a shell reutilizable
- normalizar scripts y naming systemd
- mapear multi-tenant como feature opcional del template

### Report Starlink

Objetivo:
portar auth, auditoria y reportes al marco comun.

Mejoras:

- conservar roles y auditoria como modulo reusable
- estandarizar layout `app/` hacia `src/`
- separar mejor API, web, auth y reportes
- homologar scripts y units

### Notifier

Objetivo:
aprovechar su mejor CLI y config como referencia de plataforma.

Mejoras:

- conservar `src/`
- introducir FastAPI/web shell comun si se quiere evolucionar la capa web
- reducir particularidades legacy de SQLite en proyectos nuevos
- extraer auth dashboard y catalog/rules como modulos compartibles

### Bandwidth

Objetivo:
migrarlo ultimo porque es el mas particular y liviano.

Mejoras:

- partir archivo unico en modulos
- reemplazar servidor custom por FastAPI o wrapper estandar
- mover HTML inline a templates/static
- adaptar SQLite/cache como variante opcional del template

## Modulos Reusables A Extraer

- auth base
- audit log
- catalog CRUD
- dashboard shell
- admin shell
- db-status y health
- install/update/validate lifecycle
- naming y rendering de systemd
