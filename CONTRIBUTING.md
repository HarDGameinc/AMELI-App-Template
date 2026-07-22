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

## Local dev environment — Windows-native, tested on a real server

Per [`DECISIONS.md`](docs/DECISIONS.md) **#11**, the daily loop is
**Windows-native** and extensive testing happens on a **real Linux server**.
WSL2 and Docker are out of the loop (see the note at the end of this
section).

**Setup (once per machine):**
```powershell
py -3.12 -m venv .venv
.\.venv\Scripts\pip install --upgrade pip
# From the RANGES, not requirements.lock: the lock pins uvloop (POSIX-only)
# unconditionally, so it cannot install on Windows.
.\.venv\Scripts\pip install -r requirements.txt -r requirements-dev.txt
.\.venv\Scripts\pip install -e . --no-deps
```

**Daily loop:**
```powershell
$env:APP_ENV="dev"; .\.venv\Scripts\pytest -q      # 1135 passed / 58 skipped
.\.venv\Scripts\ruff check .
.\.venv\Scripts\mypy src
```

> ### ⚠️ A green Windows run is necessary, not sufficient
>
> **~30 tests are skipped on `win32`** — the shell / systemd / backup suite
> (`test_common_sh_slug_autodetect`, `test_systemd_profile`,
> `test_backup_restore`, `test_install_sh_restart`, …), which is exactly
> what covers `scripts/*.sh` and `deploy/systemd/*`.
>
> **Any change to those surfaces needs green CI *or* a server test before
> it ships.** CI (`ubuntu-latest`, full suite + Postgres + e2e + CodeQL on
> every push/PR) is the authoritative gate; the local Windows run is the
> fast pre-filter. Never treat "green locally" as validation for shell,
> systemd, install or backup changes.

**Windows gotchas:**
- The **ranges** pull Django 6 / Pillow 12 locally, which drifts from the
  hash-pinned set that actually ships. That drift is covered by CI, which
  installs the locks on Linux — but remember the local venv is *not* what
  production runs.
- **mypy** — Windows "App Control" can block the compiled mypyc DLL
  (`ImportError: DLL load failed`). Reinstall pure-Python per venv:
  `pip install --no-binary mypy --force-reinstall --no-deps "mypy==2.1.0"`.
  One Windows-only false positive remains (`socket.AF_UNIX` in
  `accounts/av.py`).
- **Run env vars** for a local SQLite run:
  `AMELI_APP_DJANGO_SECRET_KEY`, `DATABASE_URL=""`, `AMELI_APP_SQLITE_PATH`,
  `APP_CONFIG`, `DJANGO_SETTINGS_MODULE=ameli_web.settings`. The pytest
  suite sets sane defaults via `tests/conftest.py`.

### Extensive testing — on the server

The real Linux box is the test environment for everything the Windows
suite cannot reach: `install.sh`, systemd units, file ownership,
backup/restore and TLS behind Caddy. It is *more* faithful than any local
emulation because it is the same OS and init system as production.

```bash
# on the server
git clone https://github.com/HarDGameinc/AMELI-App-Template.git <dir> && cd <dir>
sudo APP_ENV=<env> scripts/install.sh          # auto-generates the crypto keys
sudo <install_dir>/.venv/bin/ameli-app --env-file <etc>/app.env configure
APP_ENV=<env> bash scripts/validate_installation.sh
```
Do **not** hardcode paths, unit names or ports from memory — derive them on
the box with `validate_installation.sh` (see `OPERATIONS.md` → "Live
deployment ground truth").

### WSL2 / Docker — documented, not used

Both remain in the repo (`docker-compose.yml`, `Dockerfile`,
`test_docker_stack.py` as the anti-drift guard) for consumers who want
them, and the WSL2 recipe lives in [`DECISIONS.md`](docs/DECISIONS.md) #9
for the audit trail. **Neither is part of this operator's loop** — #9 was
superseded by #11 because the WSL2 bridge cost more work than it saved.

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
