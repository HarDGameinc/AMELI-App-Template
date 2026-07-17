# Contributing

Operating conventions for this repository. These lived only in dated
session handoffs (`docs/CLAUDE_HANDOFF_*` §8.2) — historical logs a fresh
agent does not read reliably. This file is the durable source; handoffs
stay as the per-session narrative.

New to the codebase? Read [`AGENTS.md`](AGENTS.md) first (purpose,
architecture, policies), then the most recent `docs/CLAUDE_HANDOFF_*`.

## Branching

- **Work on `dev`.** The dev server (`ha-report2`) always pulls `dev`.
- **`main` is the release branch** (GitHub default). It was promoted to
  **`v0.5.0-django`** on 2026-07-07 (previously frozen until this
  milestone). It advances **only by PR from `dev` with green CI** — never a
  direct push, and only by explicit operator instruction.
- There is no local `main` checkout by default; `origin/main` is the
  release reference.

## Commits

- **[Conventional Commits](https://www.conventionalcommits.org/)**:
  `type(scope): summary` (e.g. `feat(mfa): …`, `fix(avatar): …`,
  `test(js): …`, `docs(agents): …`, `chore(release): …`).
- Every commit ends with the footer:

  ```
  Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>
  ```

- **Never** skip hooks or signing (`--no-verify`, `--no-gpg-sign`). If a
  hook fails, fix the cause.
- Prefer a new commit over amending an already-pushed one.

## Pre-push checks (run all four)

```bash
ruff check .
mypy src
pytest
node --test tests/js/*.test.js
```

All must be green before pushing. CI (`.github/workflows/ci.yml`) runs
the same set across Python 3.11–3.14 plus `pip-audit`, Playwright e2e and
the `js-unit` job; see [`docs/OPERATIONS.md`](docs/OPERATIONS.md) for the
CI/branch-protection detail.

Coverage floor is 85% (`pyproject.toml`); mypy and ruff floors are zero.

## Local dev environment — WSL2 primary

Per [`DECISIONS.md`](docs/DECISIONS.md) #9, the dev environment is **WSL2
Ubuntu 24.04** — one clone, one venv, one loop. Same hash-pinned lock the
prod deploy ships, so there is no Windows/Linux drift.

**Setup (once per machine):**
```powershell
# host: PowerShell as admin
wsl --install -d Ubuntu-24.04
```
```bash
# inside WSL2 (Ubuntu-24.04):
sudo apt-get install -y python3-venv python3-dev build-essential \
    libffi-dev libjpeg-dev libpq-dev zlib1g-dev git
cd ~ && git clone https://github.com/HarDGameinc/AMELI-App-Template.git ameli-app-template
cd ameli-app-template
python3 -m venv .venv && .venv/bin/pip install --upgrade pip
# BOTH locks — they are complementary, not superset/subset.
# django overlaps only because pytest-django pulls it. Installing only the
# dev lock leaves you without uvloop/uvicorn.
.venv/bin/pip install --require-hashes -r requirements.lock       # runtime
.venv/bin/pip install --require-hashes -r requirements-dev.lock   # tooling
.venv/bin/pip install -e . --no-deps
```

**Daily loop (inside WSL2):**
```bash
wsl                                     # (Ubuntu-24.04 is the default distro)
cd ~/ameli-app-template
APP_ENV=dev .venv/bin/pytest -q         # 1156 passed / 28 skipped
.venv/bin/ruff check .
.venv/bin/mypy src
```

**Editing from Windows-side tools** reaches the WSL clone via
`\\wsl.localhost\Ubuntu-24.04\home\hardg\ameli-app-template\` (VS Code
with the Remote-WSL extension is transparent). Terminals run inside WSL.
The Windows path `C:\Users\...\AMELI_APP_TEMPLATE` is treated as archived —
see [`DECISIONS.md`](docs/DECISIONS.md) #9.

**Local deployment** (pre-promotion smoke, inside WSL2). WSL2 emulates the
production server directly — no Docker in the loop. Set up Postgres once
(`sudo apt install postgresql && sudo -u postgres createuser --pwprompt
ameli && sudo -u postgres createdb -O ameli ameli_dev`), then run the app
the same way `ameli-app-template-dev-api.service` does on `ha-report2`:
```bash
DATABASE_URL="postgresql+psycopg://ameli:PASSWORD@localhost/ameli_dev" \
    APP_ENV=dev .venv/bin/python -m ameli_app.api
```
This is the closest local pre-promotion smoke — same code path, same
uvicorn launcher, same Postgres backend as the server. If you don't need
Postgres parity (fast suite runs), the SQLite fallback still works via
`AMELI_APP_SQLITE_PATH` (see Windows fallback below for the env vars).

### Windows-native fallback (deprecated, keep only for edge cases)

Kept during the transition for the mypy-DLL edge case and quick emergency
edits when WSL is unreachable. Not the daily loop.

- **Create the venv from the ranges** (`requirements.txt` / `requirements-
  dev.txt`), NOT `requirements.lock` — the lock pins `uvloop` (POSIX-only)
  unconditionally. The ranges pull Django 6 / Pillow 12 locally; suite is
  green but drifts from what ships.
- **mypy** — Windows "App Control" can block the compiled mypyc DLL
  (`ImportError: DLL load failed`). Reinstall pure-Python per venv:
  `pip install --no-binary mypy --force-reinstall --no-deps "mypy==2.1.0"`.
  One Windows-only false positive remains (`socket.AF_UNIX` in
  `accounts/av.py`).
- **Shell/POSIX tests** are `skipif(sys.platform == "win32")` — they exercise
  `bash`/`tar`/`geteuid` and run on the Linux CI (and in the WSL loop).
- **Run env vars** for a local SQLite run:
  `AMELI_APP_DJANGO_SECRET_KEY`, `DATABASE_URL=""`, `AMELI_APP_SQLITE_PATH`,
  `APP_CONFIG`, `DJANGO_SETTINGS_MODULE=ameli_web.settings`. The pytest
  suite sets sane defaults via `tests/conftest.py`.
- Suite on Windows-native: **1126 passed / 58 skipped** (30 fewer than
  WSL because of the win32 skips).

## Releases

Version bumps follow a fixed ritual and happen only after server
validation — see [`docs/RELEASE.md`](docs/RELEASE.md).

## Deploying to the dev server

Root shell, no `sudo` binary:

```bash
git fetch && git reset --hard origin/dev
.venv/bin/pip install --require-hashes -r requirements.lock   # no-op if deps unchanged
.venv/bin/python manage.py migrate --noinput
.venv/bin/python manage.py check
systemctl restart ameli-app-template-dev-api.service
```

Full procedure and validation in [`docs/OPERATIONS.md`](docs/OPERATIONS.md).
