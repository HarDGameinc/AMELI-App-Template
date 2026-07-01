"""i18n + timezone + static files + media root + PROJECT_DIR path guards.

Moved from ameli_web/settings.py (PC-4, 2026-07-01).
"""
from __future__ import annotations

from pathlib import Path

from .base import _IS_DEV_ENV, CFG, PROJECT_DIR

LANGUAGE_CODE = "es-cl"
TIME_ZONE = CFG.timezone or "America/Santiago"
USE_I18N = True
USE_TZ = True

# Languages we ship with the Template. Operators can add more by dropping
# additional ``.po`` files under ``locale/<code>/LC_MESSAGES/django.po``
# and registering the code here.
LANGUAGES = [
    ("es", "Espanol"),
    ("en", "English"),
]
LOCALE_PATHS = [str(PROJECT_DIR / "locale")]

STATIC_URL = "/static/"
STATICFILES_DIRS = [str(PROJECT_DIR / "src" / "ameli_app" / "static")]
MEDIA_ROOT = str(CFG.profile_uploads_dir)
MEDIA_URL = "/media/"


# 2026-06-20 + 2026-06-21 wire test findings: outside dev, refuse to
# start when ``data_dir`` or ``profile_uploads_dir`` resolve INSIDE
# the project checkout (PROJECT_DIR). ``ameli_app.config.path_from_value``
# anchors relative YAML paths against PROJECT_DIR, which is root-owned
# on install.sh deploys — the app user gets PermissionError on the
# first write (avatar upload, sqlite dump in default data_dir, etc).
# Two such silent-fail surfaces have been caught manually now (data_dir
# 2026-06-20 /health/deep, profile_uploads_dir 2026-06-21 avatar upload
# 500). The boot guard forces the operator to pin absolute paths in
# app.yaml that live OUTSIDE the checkout (e.g. /var/lib/<instance>/...)
# so the failure mode is loud at startup instead of subtle at first write.
def _refuse_path_inside_checkout(setting_name: str, value: str) -> None:
    try:
        resolved = Path(value).resolve()
        if resolved == PROJECT_DIR or PROJECT_DIR in resolved.parents:
            if not _IS_DEV_ENV:
                raise RuntimeError(
                    f"{setting_name} resolves inside the project checkout "
                    f"({value!r} -> {resolved}). On install.sh deploys the "
                    f"checkout is root-owned and the app user cannot write "
                    f"there — first write (avatar upload, sqlite dump, etc) "
                    f"explodes with PermissionError. Edit /etc/<instance>/app.yaml "
                    f"to pin an ABSOLUTE path outside the checkout (e.g. "
                    f"``/var/lib/<instance>/uploads``) and ensure the dir "
                    f"is chowned to the app user. Caught at boot to avoid "
                    f"silent fail-at-first-write."
                )
    except RuntimeError:
        raise
    except Exception:  # noqa: BLE001, S110 - best-effort check; if Path.resolve fails we let Django boot
        pass


_refuse_path_inside_checkout("MEDIA_ROOT", MEDIA_ROOT)
_refuse_path_inside_checkout("CFG.data_dir", str(CFG.data_dir))
