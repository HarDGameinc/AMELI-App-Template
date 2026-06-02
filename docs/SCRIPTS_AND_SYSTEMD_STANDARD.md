# Scripts And systemd Standard

Contrato operativo para estandarizar `scripts/` y `systemd` en los proyectos
AMELI actuales y futuros.

## Objetivo

Resolver una diferencia hoy repetida entre repos:

- mismos problemas operativos
- nombres distintos de scripts
- `systemd` guardado en lugares distintos
- units con topologias parecidas pero sin convencion comun

La meta no es forzar que todas las apps tengan exactamente los mismos
procesos, sino que usen el mismo marco operativo:

- mismo set de scripts base
- misma ubicacion de templates `systemd`
- misma forma de renderizar nombres por entorno
- mismas reglas de permisos, runtime y validacion

## Estado Actual Por Proyecto

| Proyecto | Scripts principales | Ubicacion systemd | Topologia principal | Observaciones |
|---|---|---|---|---|
| Bandwidth | `install`, `update`, `uninstall`, `purge`, `install_dev`, `install_dev_isolated`, `configure_ufw`, `configure_ha_share`, `validate_*` | `systemd/` | `dashboard` + `capture.timer` | fuerte en HA/UFW; naming muy especifico |
| Metro | `install`, `update`, `uninstall`, `purge`, `backup`, `bootstrap_db`, `validate_installation`, `_common` | `deploy/systemd/` | `api` + `capturador@` + 2 timers + `notifier` + `maintenance` | mejor base para el estandar |
| Notifier | `install_dev_isolated`, `reset_dev_clean`, `sync_prod_config_to_dev`, scripts de reglas | `systemd/` | `dashboard` + `worker.timer` | muy bueno en CLI/dev aislado, incompleto como set comun |
| Omega | `install`, `install_dev`, `update`, `uninstall`, `validate_installation`, `backup_*` | generado desde scripts | `api` + `web` | valida puertos y runtime HTTP muy bien |
| Starlink | `install`, `install_dev`, `update`, `uninstall`, `validate_installation`, `configure`, `configure_ufw`, `status`, `repair_permissions`, `api`, `web`, `capture`, `maintenance` | generado desde scripts | `api` + `web` + `capture.timer` | `common.sh` muy rico; excelente base operacional |

## Lo Que Ya Comparten

- instalacion como `root` en Debian
- copia o sincronizacion a `/opt/<app>`
- configuracion real en `/etc/<app>`
- datos en `/var/lib/<app>`
- logs en `/var/log/<app>`
- runtime Python con `venv`
- alta de servicios y timers en `systemd`
- algun chequeo final de estado o health HTTP

## Lo Que Hoy Difiere

### Nombres de scripts

- unos usan `backup.sh`
- otros `backup_create.sh`, `backup_list.sh`, `backup_inspect.sh`
- unos usan `status.sh`, otros no
- algunos separan `api.sh`, `web.sh`, `capture.sh`
- algunos tienen `install_dev.sh`, otros solo instalacion aislada o multientorno

### Donde vive `systemd`

- `systemd/` en Bandwidth y Notifier
- `deploy/systemd/` en Metro
- generado directamente por scripts en Omega y Starlink

### Nombres de units

- `dashboard`
- `api`
- `web`
- `worker`
- `capturador`
- `capture`
- `notifier`
- `maintenance`

### Nivel de seguridad/hardening

- algunos usan usuario dedicado y `ReadWritePaths`
- otros corren como `root`
- algunos usan `ProtectSystem`, `NoNewPrivileges`, `PrivateTmp`
- otros tienen units mucho mas simples

## Estandar Objetivo

## Ubicacion

### Scripts

Todos los scripts operacionales deben vivir en:

```text
scripts/
```

### systemd

Todos los templates versionados deben vivir en:

```text
deploy/systemd/
```

No se deben generar units completas desde bash salvo para compatibilidad
transitoria durante una migracion. El estandar final es:

- templates versionados en repo
- placeholders renderizados por `scripts/_common.sh`

## Set De Scripts Base

### Obligatorios

- `scripts/install.sh`
- `scripts/install_dev.sh`
- `scripts/update.sh`
- `scripts/uninstall.sh`
- `scripts/backup.sh`
- `scripts/validate_installation.sh`
- `scripts/_common.sh`

### Opcionales segun dominio

- `scripts/bootstrap_db.sh`
- `scripts/configure_ufw.sh`
- `scripts/status.sh`
- `scripts/repair_permissions.sh`
- `scripts/capture.sh`
- `scripts/api.sh`
- `scripts/web.sh`
- `scripts/maintenance.sh`

## Clasificacion De Scripts

Para evitar que todo termine mezclado, los scripts deben clasificarse asi:

### Base de ciclo de vida

- `install.sh`
- `install_dev.sh`
- `update.sh`
- `uninstall.sh`
- `backup.sh`
- `validate_installation.sh`
- `_common.sh`

### Utilidades de plataforma opcionales

- `bootstrap_db.sh`
- `configure_ufw.sh`
- `status.sh`
- `repair_permissions.sh`

### Wrappers de conveniencia

- `api.sh`
- `web.sh`
- `capture.sh`
- `maintenance.sh`

### Herramientas de dominio o soporte

- importadores de reglas
- sincronizadores de config prod->dev
- share/CIFS
- reseteos DEV completos

La regla es simple:

- lo base vive en todos
- lo opcional vive solo donde aporta
- lo de dominio no debe contaminar el estándar común

## Responsabilidad De Cada Script

### `install.sh`

- instalar prerequisitos del sistema
- crear usuario y grupo de servicio si aplica
- crear `venv`
- instalar dependencias Python
- inicializar config real sin pisar secretos existentes
- registrar y habilitar units
- ejecutar validacion final

### `install_dev.sh`

- instalar variante `dev`
- soportar convivencia con `prod`
- prefijar nombre de units, rutas y puertos por entorno o instancia
- no pisar runtime productivo

### `update.sh`

- crear backup previo razonable
- sincronizar paquete
- reinstalar o actualizar dependencias
- re-renderizar units si corresponde
- reiniciar servicios persistentes
- validar runtime HTTP o CLI

### `uninstall.sh`

- detener y deshabilitar units
- remover wrappers, services y archivos de despliegue
- conservar config y datos salvo que se pida purga explicita

### `backup.sh`

- crear backup de DB y archivos sensibles de runtime
- no depender de rutas hardcodeadas fuera del marco del proyecto
- emitir ruta final del backup

### `validate_installation.sh`

Debe chequear como minimo:

- archivos base presentes (`README`, `VERSION`, `pyproject`)
- Python/venv operativo
- imports o entrypoints clave
- config presente
- DB alcanzable si aplica
- estado de `systemd`
- health HTTP o comandos de estado cuando corresponda

### `_common.sh`

Debe concentrar:

- deteccion de `prod|dev`
- nombres derivados de app, units, puertos y paths
- helpers de permisos
- render de units
- helpers de `systemctl`
- helpers para editar `.env`
- convenciones de backup

## Convencion De Naming `systemd`

Base:

- `<app>-api.service`
- `<app>-web.service`
- `<app>-worker.service`
- `<app>-worker.timer`
- `<app>-maintenance.service`
- `<app>-maintenance.timer`

Variantes permitidas por dominio:

- `<app>-capture.service`
- `<app>-capture.timer`
- `<app>-capture@.service`
- `<app>-notifier.service`

La convención final recomendada es:

```text
<app>-<env>-<role>.service
<app>-<env>-<role>.timer
```

Ejemplos:

- `ameli-metro-prod-api.service`
- `ameli-metro-dev-notifier.service`
- `ameli-starlink-prod-web.service`
- `ameli-bandwidth-dev-capture.timer`

Para convivencia por entorno:

- `<app>-prod-api.service`
- `<app>-dev-api.service`

o equivalentemente un prefijo derivado desde `_common.sh`, pero la regla debe
ser consistente dentro del repo.

## Hardening Minimo Recomendado

Toda unit nueva deberia evaluar estas directivas:

- `User=` y `Group=` dedicados
- `WorkingDirectory=`
- `EnvironmentFile=` cuando aplique
- `Restart=on-failure` para servicios persistentes
- `NoNewPrivileges=true`
- `PrivateTmp=true`
- `ProtectSystem=full`
- `ReadWritePaths=...`

No todos los proyectos requieren todas las directivas, pero esta es la base
esperada para nuevas apps y migraciones.

## Contrato De Runtime

Los scripts y units deben asumir este layout operativo:

```text
/opt/<instance>
/etc/<instance>
/var/lib/<instance>
/var/log/<instance>
```

Donde `<instance>` puede incorporar `prod`, `dev` o un sufijo equivalente.

## Mapeo Recomendado Por Proyecto

### Bandwidth

Mantener como opcionales:

- `configure_ha_share.sh`
- `configure_ufw.sh`
- `validate_ha_share.sh`
- `validate_ufw.sh`

Migrar hacia:

- mover `systemd/` a `deploy/systemd/`
- reemplazar `dashboard` por `web` en naming de unit
- absorber `install_dev_isolated.sh` dentro de `install_dev.sh`
- mover pruebas de parser y export HTML fuera del validador base

### Metro

Mantener:

- `bootstrap_db.sh`
- `backup.sh`
- `capturador@.service`
- `notifier.service`

Migrar hacia:

- units con usuario dedicado
- nombre comun por entorno desde `_common.sh`
- `deploy/systemd/` como patron de referencia
- migrar `capturador` hacia `capture` como naming comun, manteniendo
  compatibilidad temporal

### Notifier

Mantener:

- `install_dev_isolated.sh` como herramienta avanzada

Migrar hacia:

- agregar `install.sh`, `update.sh`, `uninstall.sh`, `backup.sh`,
  `validate_installation.sh`
- conservar `dashboard` y `worker` como variante valida del estandar
- converger `dashboard.service` a `web.service`

### Omega

Mantener:

- validacion de puertos
- validacion HTTP post-install

Migrar hacia:

- sacar units inline desde bash y llevarlas a `deploy/systemd/`
- consolidar `backup_create/list/inspect` bajo un `backup.sh` comun y
  utilidades opcionales
- renombrar runtime a `api` y `web` con sufijo de entorno

### Starlink

Mantener:

- `common.sh`
- wrappers `api.sh`, `web.sh`, `capture.sh`, `maintenance.sh`
- `repair_permissions.sh`

Migrar hacia:

- mover generacion inline de units a templates versionados
- preservar `api + web + capture.timer` como perfil valido del template
- degradar `api.sh`, `web.sh`, `capture.sh`, `maintenance.sh` a wrappers
  opcionales sobre una CLI Python comun

## Decision Recomendada

Tomar como base comun:

- modelo de helpers y multientorno de Metro
- robustez operacional de Starlink
- validacion runtime de Omega
- hardening de Notifier

Y formalizarlo en el template con:

- `scripts/_common.sh` comun
- `deploy/systemd/` versionado
- checklist de validacion comun
- excepciones por dominio solo para `capture`, `notifier`, `web` y `worker`
- perfiles `systemd` definidos en `docs/SYSTEMD_PROFILE_STANDARD.md`
