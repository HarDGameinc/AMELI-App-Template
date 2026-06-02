# systemd Profile Standard

Perfiles de servicios `systemd` permitidos para apps AMELI.

La idea no es que todas las apps levanten los mismos procesos, sino que
cuando un proceso exista, use naming y estructura coherentes.

## Convencion De Nombres

Todos los servicios deben usar:

```text
<app>-<env>-<role>.service
<app>-<env>-<role>.timer
```

Ejemplos:

- `ameli-metro-prod-api.service`
- `ameli-metro-dev-notifier.service`
- `ameli-bandwidth-dev-web.service`
- `ameli-starlink-prod-capture.timer`

## Roles Permitidos

### Base

- `api`
- `web`
- `worker`
- `maintenance`

### Especializados

- `capture`
- `capture-primary`
- `capture-secondary`
- `notifier`

### Template

- `capture@.service`

## Perfil 1: Web + Capture

Pensado para dashboards livianos que capturan o refrescan estado por timer.

Units:

- `<app>-<env>-web.service`
- `<app>-<env>-capture.service`
- `<app>-<env>-capture.timer`

Proyecto de referencia:

- Bandwidth

## Perfil 2: Web + Worker

Pensado para apps con dashboard y procesamiento periódico desacoplado.

Units:

- `<app>-<env>-web.service`
- `<app>-<env>-worker.service`
- `<app>-<env>-worker.timer`

Proyecto de referencia:

- Notifier

## Perfil 3: API + Web

Pensado para apps con backend HTTP separado del panel administrativo.

Units:

- `<app>-<env>-api.service`
- `<app>-<env>-web.service`

Proyecto de referencia:

- Omega

## Perfil 4: API + Web + Capture

Pensado para apps con API/web persistentes y un capturador periódico.

Units:

- `<app>-<env>-api.service`
- `<app>-<env>-web.service`
- `<app>-<env>-capture.service`
- `<app>-<env>-capture.timer`

Proyecto de referencia:

- Starlink

## Perfil 5: API + Capture + Notifier + Maintenance

Pensado para pipelines de captura y notificación sin panel web rico
independiente.

Units:

- `<app>-<env>-api.service`
- `<app>-<env>-capture@.service`
- `<app>-<env>-capture-primary.timer`
- `<app>-<env>-capture-secondary.timer`
- `<app>-<env>-notifier.service`
- `<app>-<env>-maintenance.service`
- `<app>-<env>-maintenance.timer`

Proyecto de referencia:

- Metro

## Reglas Generales De Unit

### Servicios persistentes

Deben evaluar:

- `Type=simple`
- `Restart=on-failure`
- `RestartSec=5`

Aplica a:

- `api`
- `web`
- `notifier`

### Jobs periódicos

Deben usar:

- `Type=oneshot`

Aplica a:

- `worker`
- `capture`
- `maintenance`

### Seguridad mínima

Toda unit nueva debería incluir, salvo razón documentada:

- `User=`
- `Group=`
- `WorkingDirectory=`
- `EnvironmentFile=` o `Environment=`
- `NoNewPrivileges=true`
- `PrivateTmp=true`
- `ProtectSystem=full`
- `ReadWritePaths=...`

## Regla Sobre `dashboard`

En `systemd`, `dashboard` debe converger a `web`.

Motivo:

- simplifica perfiles
- evita duplicidad conceptual
- permite que una misma template soporte dashboard simple o admin web

## Regla Sobre Entorno

El entorno debe estar en el nombre de la unit:

```text
<app>-prod-web.service
<app>-dev-web.service
```

No se deben mezclar dentro del mismo host units sin sufijo de entorno cuando
el proyecto soporta convivencia `prod|dev`.
