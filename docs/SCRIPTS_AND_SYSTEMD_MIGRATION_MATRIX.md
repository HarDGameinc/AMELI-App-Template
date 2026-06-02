# Scripts And systemd Migration Matrix

Matriz detallada para decidir, repo por repo, qué scripts y units deben:

- mantenerse
- renombrarse
- fusionarse
- pasar a ser opcionales
- eliminarse del estándar general

## Regla Madre

Un proyecto AMELI no necesita tener todos los scripts existentes hoy en todos
los repositorios. Lo que sí necesita es:

- una capa base común
- una convención única de naming
- una topología `systemd` reconocible
- validaciones operativas consistentes

El resto debe tratarse como utilidad opcional de dominio u operación.

## Capa Base Común

Todos los proyectos deben converger, como mínimo, a:

- `scripts/_common.sh`
- `scripts/install.sh`
- `scripts/install_dev.sh`
- `scripts/update.sh`
- `scripts/uninstall.sh`
- `scripts/backup.sh`
- `scripts/validate_installation.sh`
- `deploy/systemd/`

## Scripts Actuales Versus Objetivo

| Proyecto | Script actual | Destino propuesto | Accion | Motivo |
|---|---|---|---|---|
| Bandwidth | `install.sh` | `install.sh` | mantener y refactorizar | ya cumple rol base |
| Bandwidth | `update.sh` | `update.sh` | mantener y simplificar | debe compartir helper comun |
| Bandwidth | `uninstall.sh` | `uninstall.sh` | mantener | parte del ciclo base |
| Bandwidth | `purge.sh` | `purge.sh` opcional | mantener como opcional | destructivo, no base |
| Bandwidth | `install_dev.sh` | `install_dev.sh` | mantener | util para convivencia |
| Bandwidth | `install_dev_isolated.sh` | `install_dev.sh` | fusionar | hoy solo delega |
| Bandwidth | `update_dev.sh` | `install_dev.sh` + `update.sh` | absorber | evitar duplicacion por modo |
| Bandwidth | `uninstall_dev.sh` | `uninstall.sh` | absorber | misma logica con entorno |
| Bandwidth | `validate_dev.sh` | `validate_installation.sh` | absorber | validar por modo, no por nombre distinto |
| Bandwidth | `configure_ufw.sh` | `configure_ufw.sh` opcional | mantener opcional | util de red, no universal |
| Bandwidth | `validate_ufw.sh` | `validate_ufw.sh` opcional | mantener opcional | util de red, no universal |
| Bandwidth | `configure_ha_share.sh` | `configure_ha_share.sh` opcional | mantener opcional | muy dominio/infra especifico |
| Bandwidth | `validate_ha_share.sh` | `validate_ha_share.sh` opcional | mantener opcional | muy dominio/infra especifico |
| Metro | `install.sh` | `install.sh` | mantener | muy buena base |
| Metro | `update.sh` | `update.sh` | mantener | buena base multientorno |
| Metro | `uninstall.sh` | `uninstall.sh` | mantener | base |
| Metro | `purge.sh` | `purge.sh` opcional | mantener opcional | destructivo |
| Metro | `backup.sh` | `backup.sh` | mantener | base |
| Metro | `bootstrap_db.sh` | `bootstrap_db.sh` opcional | mantener opcional | aplica a apps con DB |
| Metro | `validate_installation.sh` | `validate_installation.sh` | mantener | buen candidato de base comun |
| Metro | `_common.sh` | `_common.sh` | mantener y convertir en referencia | mejor helper comun actual |
| Notifier | `install_dev_isolated.sh` | `install_dev.sh` avanzado | mantener como variante avanzada | muy util para instancias aisladas |
| Notifier | `reset_dev_clean.sh` | `reset_dev_clean.sh` opcional | mantener opcional | herramienta de soporte DEV |
| Notifier | `sync_prod_config_to_dev.sh` | `sync_prod_config_to_dev.sh` opcional | mantener opcional | utilidad fuerte de onboarding/testing |
| Notifier | `install_ups_correlated_rules_*` | script de dominio | sacar del estándar general | no es infraestructura base |
| Omega | `install.sh` | `install.sh` | mantener | base |
| Omega | `install_dev.sh` | `install_dev.sh` | mantener | base |
| Omega | `update.sh` | `update.sh` | mantener | base |
| Omega | `uninstall.sh` | `uninstall.sh` | mantener | base |
| Omega | `validate_installation.sh` | `validate_installation.sh` | mantener y adelgazar | hoy mezcla demasiado dominio |
| Omega | `backup_create.sh` | `backup.sh` | fusionar | `backup.sh` debe ser la entrada estandar |
| Omega | `backup_list.sh` | `backup.sh list` o script opcional | absorber u opcional | misma familia funcional |
| Omega | `backup_inspect.sh` | `backup.sh inspect` o script opcional | absorber u opcional | misma familia funcional |
| Starlink | `install.sh` | `install.sh` | mantener | base |
| Starlink | `install_dev.sh` | `install_dev.sh` | mantener | base |
| Starlink | `update.sh` | `update.sh` | mantener | base |
| Starlink | `uninstall.sh` | `uninstall.sh` | mantener | base |
| Starlink | `validate_installation.sh` | `validate_installation.sh` | mantener y modularizar | tiene buenas ideas, pero mezcla dominio |
| Starlink | `configure.sh` | `configure.sh` opcional | mantener opcional | no todas las apps lo requieren |
| Starlink | `configure_ufw.sh` | `configure_ufw.sh` opcional | mantener opcional | util de red |
| Starlink | `validate_ufw.sh` | `validate_ufw.sh` opcional | mantener opcional | util de red |
| Starlink | `status.sh` | `status.sh` opcional | mantener opcional | wrapper administrativo |
| Starlink | `repair_permissions.sh` | `repair_permissions.sh` opcional | mantener opcional | útil cuando hay despliegues complejos |
| Starlink | `api.sh` | CLI Python o wrapper opcional | degradar a opcional | comodidad, no requisito |
| Starlink | `web.sh` | CLI Python o wrapper opcional | degradar a opcional | comodidad, no requisito |
| Starlink | `capture.sh` | CLI Python o wrapper opcional | degradar a opcional | comodidad, no requisito |
| Starlink | `maintenance.sh` | CLI Python o wrapper opcional | degradar a opcional | comodidad, no requisito |

## Decisiones Por Familia De Scripts

### 1. Scripts base obligatorios

Se estandarizan siempre:

- `install.sh`
- `install_dev.sh`
- `update.sh`
- `uninstall.sh`
- `backup.sh`
- `validate_installation.sh`
- `_common.sh`

### 2. Scripts destructivos

No forman parte del mínimo obligatorio:

- `purge.sh`
- `reset_dev_clean.sh`

Deben existir solo cuando el proyecto realmente lo necesita y quedar
claramente marcados como destructivos.

### 3. Scripts de dominio

No deben entrar al estándar general:

- instaladores de reglas UPS en Notifier
- share CIFS / HA específicos de Bandwidth
- herramientas de pruebas o catálogos de un dominio puntual

### 4. Wrappers de conveniencia

Pueden existir, pero no deben reemplazar una CLI Python estándar:

- `api.sh`
- `web.sh`
- `capture.sh`
- `maintenance.sh`
- `status.sh`

La recomendación es que la acción exista primero en la CLI Python, y luego el
wrapper bash sea solo un alias operativo si de verdad aporta.

## systemd Actual Versus Objetivo

| Proyecto | Unit actual | Unit objetivo | Accion | Motivo |
|---|---|---|---|---|
| Bandwidth | `ameli-bandwidth-dashboard.service` | `<app>-<env>-web.service` | renombrar | `dashboard` debe converger a `web` |
| Bandwidth | `ameli-bandwidth-dashboard-capture.service` | `<app>-<env>-capture.service` | renombrar | naming comun |
| Bandwidth | `ameli-bandwidth-dashboard-capture.timer` | `<app>-<env>-capture.timer` | renombrar | naming comun |
| Metro | `ameli-metro-<env>-api.service` | mantener forma | mantener | muy buen patron |
| Metro | `ameli-metro-<env>-capturador@.service` | `<app>-<env>-capture@.service` | renombrar gradualmente | castellanismo local, mejor unificar |
| Metro | `ameli-metro-<env>-capturador-primary.timer` | `<app>-<env>-capture-primary.timer` | renombrar gradualmente | naming comun |
| Metro | `ameli-metro-<env>-capturador-secondary.timer` | `<app>-<env>-capture-secondary.timer` | renombrar gradualmente | naming comun |
| Metro | `ameli-metro-<env>-notifier.service` | mantener forma | mantener | variante valida |
| Metro | `ameli-metro-<env>-maintenance.service` | mantener forma | mantener | variante valida |
| Metro | `ameli-metro-<env>-maintenance.timer` | mantener forma | mantener | variante valida |
| Notifier | `ameli-notifier-dashboard.service` | `<app>-<env>-web.service` | renombrar | converger `dashboard -> web` |
| Notifier | `ameli-notifier-worker.service` | `<app>-<env>-worker.service` | mantener con entorno | base valida |
| Notifier | `ameli-notifier-worker.timer` | `<app>-<env>-worker.timer` | mantener con entorno | base valida |
| Omega | `ameli-omega-receiver.service` | `<app>-<env>-api.service` | renombrar | explicitar rol y entorno |
| Omega | `ameli-omega-receiver-web.service` | `<app>-<env>-web.service` | renombrar | naming comun |
| Starlink | `ameli-starlink-<env>-api.service` | mantener forma | mantener | ya va en buena direccion |
| Starlink | `ameli-starlink-<env>-web.service` | mantener forma | mantener | ya va en buena direccion |
| Starlink | `ameli-starlink-<env>-capturador.service` | `<app>-<env>-capture.service` | renombrar gradualmente | naming comun |
| Starlink | `ameli-starlink-<env>-capturador.timer` | `<app>-<env>-capture.timer` | renombrar gradualmente | naming comun |

## Naming Final Recomendado

Convención única:

```text
<app>-<env>-<role>.service
<app>-<env>-<role>.timer
```

Roles base:

- `api`
- `web`
- `worker`
- `maintenance`

Roles opcionales:

- `capture`
- `capture-primary`
- `capture-secondary`
- `notifier`

Template opcional:

```text
<app>-<env>-capture@.service
```

## Perfiles De Topologia Recomendados

### Perfil A: API + Web + Capture + Maintenance

Aplicable a:

- Starlink

Opcionalmente:

- Omega si su ingesta se desacopla mas

### Perfil B: API + Capture + Notifier + Maintenance

Aplicable a:

- Metro

### Perfil C: Web + Worker

Aplicable a:

- Notifier

### Perfil D: Web + Capture

Aplicable a:

- Bandwidth

### Perfil E: API + Web

Aplicable a:

- Omega

## Decision Sobre `dashboard` Versus `web`

Se recomienda estandarizar en `web`.

Motivos:

- sirve para dashboard simple y para panel administrativo
- alinea mejor con Starlink y Omega
- evita que `dashboard` se vuelva una categoria distinta cuando en realidad es
  una app web

Regla:

- el nombre visual puede seguir diciendo “dashboard”
- la unit debe converger a `web.service`

## Qué Debe Salir Del Estándar General

No deberían considerarse parte de la plataforma común:

- pruebas de parser de Bandwidth dentro de `validate_installation.sh`
- validaciones de HTML/export específicos de Bandwidth
- validaciones de catálogo y correlación específicas de Omega
- validaciones de auth/reportes específicas de Starlink
- scripts de instalación de reglas UPS específicas de Notifier

Eso debe vivir como:

- tests automáticos
- comandos de dominio
- validadores opcionales por módulo

No como requisito universal del deploy base.

## Qué Sí Conviene Compartir

### Desde Metro

- `_common.sh`
- render de units desde templates
- multientorno `prod|dev`
- lifecycle base sencillo

### Desde Starlink

- normalización de layout `/opt`, `/etc`, `/var/lib`, `/var/log`
- wrappers/CLI de operación
- helpers de permisos
- validación de runtime posterior a update

### Desde Omega

- chequeo de puertos
- validación HTTP fuerte post-install

### Desde Notifier

- hardening de `systemd`
- soporte de instancias dev aisladas

## Orden De Implementación Recomendada

1. Formalizar naming final en el template
2. Definir templates `systemd` versionados para `api`, `web`, `worker`,
   `capture`, `maintenance`, `notifier`
3. Consolidar `_common.sh` como helper estándar
4. Migrar Metro para dejar el patrón base
5. Migrar Starlink y Omega
6. Migrar Notifier y Bandwidth con sus excepciones controladas
