# Operations

## Local validation

```bash
python -m venv .venv
. .venv/bin/activate
pip install -r requirements.txt -r requirements-dev.txt
pip install -e .
pytest
ruff check .
ruff format --check .
```

## Linux install

```bash
sudo APP_ENV=dev APP_SLUG=ameli-new-app APP_PACKAGE=ameli_new_app bash scripts/install.sh
```

The installer preserves `/etc/<instance>/app.env` and `/etc/<instance>/app.yaml`
if they already exist.

## Health checks

```bash
ameli-app config-check --config config/app.yaml.example
ameli-app db-status --config config/app.yaml.example
curl http://127.0.0.1:18080/health
```

## Backup

```bash
sudo APP_ENV=prod bash scripts/backup.sh
```

