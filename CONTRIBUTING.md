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

## Local dev environment (Windows notes)

The operator's workstation is native Windows; a few things differ from
the Linux CI/deploy:

- **Create the venv from the ranges, NOT `requirements.lock`.** The lock
  pins `uvloop` (POSIX-only, no Windows wheel) with no platform marker, so
  `pip install --require-hashes -r requirements.lock` fails to build it on
  Windows. Installing from `requirements.txt` / `requirements-dev.txt`
  lets `uvicorn` omit `uvloop`. (This also pulls Django 6 / Pillow 12
  locally; the suite is green on both stacks. The server stays on the
  hash-locked Django 5.2 LTS.)
- **mypy**: Windows "App Control" can block the compiled mypyc DLL
  (`ImportError: DLL load failed`). Reinstall pure-Python per venv:
  `pip install --no-binary mypy --force-reinstall --no-deps "mypy==2.1.0"`.
  One Windows-only false positive remains (`socket.AF_UNIX` in
  `accounts/av.py`); the Linux CI reports zero mypy errors.
- **Shell/POSIX tests** (`test_common_sh_slug_autodetect`,
  `test_systemd_profile`, parts of `test_backup_restore`) are
  `skipif(sys.platform == "win32")` — they exercise `bash`/`tar`/`geteuid`
  and run on the Linux CI.
- **Run env vars** for a local SQLite run:
  `AMELI_APP_DJANGO_SECRET_KEY`, `DATABASE_URL=""`, `AMELI_APP_SQLITE_PATH`,
  `APP_CONFIG`, `DJANGO_SETTINGS_MODULE=ameli_web.settings`. The pytest
  suite sets sane defaults via `tests/conftest.py`.

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
