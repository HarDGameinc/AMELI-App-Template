"""Alternate web launcher — alias of ``ameli_app.api``.

The canonical entry point is ``python -m ameli_app.api`` (see
``AGENTS.md`` §Runtime). This module exists as an alias so child
apps that override the deployment scaffolding can keep the
``ameli-app-web.service`` systemd unit and switch the implementation
behind it without renaming the unit file. The two launchers are
intentionally identical today; if they diverge, document the split
here and in the systemd unit comments.
"""
from __future__ import annotations

import os

import uvicorn

from .config import load_settings


def serve() -> None:
    settings = load_settings()
    os.environ.setdefault("DJANGO_SETTINGS_MODULE", "ameli_web.settings")
    uvicorn.run("ameli_web.asgi:application", host=settings.host, port=settings.web_port, log_level="info")


if __name__ == "__main__":
    serve()
