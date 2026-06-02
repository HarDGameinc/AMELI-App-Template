# Standardization Checklist

Checklist que debe cumplir un proyecto AMELI para considerarse migrado al
estandar.

## Base de Repo

- Usa layout `src/`.
- Tiene `pyproject.toml`.
- Tiene `requirements.txt` y `requirements-dev.txt`.
- Tiene `README.md`, `VERSION` y docs base.

## Configuracion

- Usa `.env` para runtime y secretos.
- Usa YAML para config base.
- Usa `DATABASE_URL` como variable principal de DB.
- Distingue `APP_ENV=prod|dev`.

## Scripts

- Tiene `install.sh`.
- Tiene `install_dev.sh`.
- Tiene `update.sh`.
- Tiene `uninstall.sh`.
- Tiene `backup.sh`.
- Tiene `validate_installation.sh`.
- Tiene helpers comunes en `_common.sh`.
- Los scripts preservan config existente y son re-ejecutables sin romper el entorno.
- La validacion final comprueba runtime real, no solo existencia de archivos.

## systemd

- Tiene unit de API.
- Tiene unit de worker o una variante valida (`capture` o `notifier`).
- Tiene timer de worker o una variante valida (`capture.timer`).
- Tiene unit de maintenance.
- Tiene timer de maintenance.
- Renderiza nombres por entorno.
- Si el dominio lo requiere, separa `capture` y `notifier` en units propias.
- Usa templates versionados en `deploy/systemd/`.
- Usa usuario de servicio dedicado salvo excepcion documentada.
- Define `ReadWritePaths` y hardening minimo razonable.

## Aplicacion

- Tiene `/health`.
- Tiene `/api/health`.
- Tiene `/`.
- Tiene `/admin`.
- Tiene `version`, `config-check`, `db-status`, `worker-once`, `maintenance`.

## Seguridad

- Rutas sensibles protegidas.
- Secretos fuera de repo.
- Logs sin exponer tokens o passwords.

## Testing

- Tiene tests base.
- `pytest` pasa.
- `ruff check .` pasa.
- `ruff format --check .` pasa.

## Web

- Dashboard shell consistente.
- Admin shell consistente.
- Assets fuera de strings inline siempre que sea razonable.
- Health/version visibles en panel.
