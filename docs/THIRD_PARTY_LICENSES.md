# Third-party licenses

The AMELI App Template (MIT) bundles or depends on the following
third-party packages at runtime. This file is the canonical
attribution surface required by their licenses (BSD / MIT / Apache
all require the copyright + license notice to be preserved in
distributions).

Regenerate after a dependency bump:

```bash
pip install pip-licenses
pip-licenses --from=mixed --order=license \
    --format=markdown \
    --packages alembic argon2-cffi Django Pillow psycopg pyotp \
               python-dateutil PyYAML qrcode SQLAlchemy uvicorn \
    > docs/THIRD_PARTY_LICENSES.generated.md
```

Then reconcile against this hand-maintained file. The hand-maintained
version is the source of truth because it carries the operator-facing
notes (e.g. LGPL implications for psycopg).

## Runtime dependencies

| Package | Version pin | License | Notes |
| --- | --- | --- | --- |
| alembic | ~=1.13 | MIT | Migration tooling; only used by the optional SQLAlchemy path. |
| argon2-cffi | ~=23.1 | MIT | Argon2id password hashing backend. |
| Django | ~=5.2 | BSD-3-Clause | Web framework. Copyright (c) Django Software Foundation. |
| Pillow | ~=11.0 | MIT-CMU (HPND) | Avatar pipeline (decode + Lanczos resize + re-encode). |
| psycopg[binary] | ~=3.1 | **LGPL-3.0-or-later** | PostgreSQL driver. See "LGPL note" below. |
| pyotp | ~=2.9 | MIT | TOTP code generation + verification. |
| python-dateutil | ~=2.9 | Apache-2.0 / BSD-3 dual | Used by Django; we link the Apache-2.0 NOTICE here. |
| PyYAML | ~=6.0 | MIT | Config + handoff parser. |
| qrcode | ~=7.4 | BSD-3-Clause | TOTP enrollment QR. |
| SQLAlchemy | ~=2.0 | MIT | Optional async/raw SQL surface. |
| uvicorn[standard] | ~=0.30 | BSD-3-Clause | ASGI server. |

## Development / test dependencies

These are NOT shipped in the runtime artifact but appear in
`requirements-dev.txt`:

| Package | Version pin | License |
| --- | --- | --- |
| httpx | ~=0.27 | BSD-3-Clause |
| pytest | ~=8.0 | MIT |
| pytest-django | ~=4.9 | BSD-3-Clause |
| ruff | ~=0.6 | MIT |
| pip-audit | ~=2.7 | Apache-2.0 |

## LGPL note (psycopg)

`psycopg[binary]` is distributed under LGPL-3.0-or-later. The LGPL's
copyleft clause activates only when you **modify** psycopg itself —
linking + calling its public API (which is what this template does)
does NOT propagate the LGPL to AMELI App Template code. Operators
who fork psycopg and ship their fork in the same binary must release
the modified psycopg source under LGPL; the rest of the template
stays MIT.

If your deploy environment forbids LGPL altogether, you can replace
`psycopg[binary]` with the pure-Python `psycopg2-binary` (BSD-like
LGPL exception) — both expose a Django-compatible adapter via the
`django.db.backends.postgresql` engine.

## Apache-2.0 NOTICE aggregation

Apache-2.0 requires us to forward any upstream `NOTICE` text. The
template currently pulls in two Apache-2.0 deps:

- `python-dateutil` (when redistributed under its Apache-2.0 face):
  Copyright 2017- Paul Ganssle <paul@ganssle.io>. Copyright 2017-
  dateutil contributors.
- `pip-audit` (dev only; not shipped at runtime): Copyright Trail of
  Bits.

Operators redistributing AMELI App Template binaries that include
these wheels must preserve the above attributions alongside this
file.

## Compatibility matrix

| License pair | Compatible? | Note |
| --- | --- | --- |
| MIT ↔ BSD-3 | yes | Both permissive; either notice may be retained. |
| MIT ↔ Apache-2.0 | yes | Apache-2.0 NOTICE must travel with the artifact. |
| MIT ↔ LGPL-3.0 (psycopg) | yes (via dynamic link) | See "LGPL note". |
| MIT ↔ MIT-CMU (Pillow) | yes | Functionally identical to MIT. |

The template ships zero GPL / AGPL-licensed code.
