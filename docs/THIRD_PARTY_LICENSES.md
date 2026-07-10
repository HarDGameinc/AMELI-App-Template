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
    --packages argon2-cffi Django Pillow psycopg pyotp \
               python-dateutil PyYAML qrcode uvicorn \
    > docs/THIRD_PARTY_LICENSES.generated.md
```

Then reconcile against this hand-maintained file. The hand-maintained
version is the source of truth because it carries the operator-facing
notes (e.g. LGPL implications for psycopg).

## Runtime dependencies

| Package | Version pin | License | Notes |
| --- | --- | --- | --- |
| argon2-cffi | ~=23.1 | MIT | Argon2id password hashing backend. |
| Django | ~=5.2 | BSD-3-Clause | Web framework. Copyright (c) Django Software Foundation. |
| Pillow | ~=11.0 | MIT-CMU (HPND) | Avatar pipeline (decode + Lanczos resize + re-encode). |
| psycopg[binary] | ~=3.1 | **LGPL-3.0-or-later** | PostgreSQL driver. See "LGPL note" below. |
| pyotp | ~=2.9 | MIT | TOTP code generation + verification. |
| python-dateutil | ~=2.9 | Apache-2.0 / BSD-3 dual | Used by Django; we link the Apache-2.0 NOTICE here. |
| PyYAML | ~=6.0 | MIT | Config + handoff parser. |
| qrcode | ~=7.4 | BSD-3-Clause | TOTP enrollment QR. |
| uvicorn[standard] | ~=0.30 | BSD-3-Clause | ASGI server. |

> The **Version pin** column is indicative (the declared floor in
> `pyproject.toml` / `requirements.txt`). The exact, hash-locked versions
> actually shipped live in `requirements.lock` — that file is the source
> of truth for what is redistributed. License *type* does not change
> across these packages' minor/patch bumps, so the attribution above holds
> regardless of the locked version.

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
| axe-core (vendored) | 4.10.2 | **MPL-2.0** | Vendored at `tests/e2e/vendor/axe.min.js` for the Playwright accessibility smoke. Test-only (not shipped in the runtime artifact), unmodified, MPL header preserved. File-level copyleft applies only to `axe.min.js` itself, which we do not modify — no effect on the template's MIT license. Not a pip dependency (kept out of the hash-locked `requirements*.lock`). |

## Web fonts (Google Fonts, CDN-referenced)

The UI links three font families from the Google Fonts CDN (`base.html`),
so the font files are served by Google and are **not redistributed** in
the template's own artifact — no notice is legally required for merely
referencing them. They are listed here for transparency and for adopters
who choose to **self-host** the files (self-hosting redistributes them,
which does activate the OFL / Apache-2.0 notice requirements).

| Family | Where | License | Copyright |
| --- | --- | --- | --- |
| DM Sans | Display / headings (D-1) | SIL OFL 1.1 | Colophon Foundry, Jonny Pinhorn, Indian Type Foundry |
| IBM Plex Sans | Body copy (D-1) | SIL OFL 1.1 | © 2017 IBM Corp. |
| Material Symbols Rounded | Icon glyphs | Apache-2.0 | © Google LLC |

- **SIL OFL 1.1** (DM Sans, IBM Plex Sans): the fonts may be used, bundled,
  embedded and redistributed freely, including in commercial products; the
  only constraints are that they not be sold on their own and that the
  Reserved Font Name not be reused on a modified version. Ship the OFL text
  with the font files if you self-host.
- **Apache-2.0** (Material Symbols Rounded): if self-hosted, forward
  Google's `NOTICE` alongside the glyph files (see the Apache NOTICE section
  below).

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
- **Material Symbols Rounded** — only if **self-hosted** (the default
  CDN reference does not redistribute the glyphs): Copyright Google LLC.

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
| MIT ↔ SIL OFL 1.1 (fonts) | yes | Permissive; Reserved Font Name is the only real constraint. CDN-referenced, so not redistributed by default. |
| MIT ↔ MPL-2.0 (axe-core) | yes | File-level copyleft, test-only, unmodified. |

The template ships zero GPL / AGPL-licensed code.
