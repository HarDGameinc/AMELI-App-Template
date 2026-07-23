"""Canonical runtime entry point for the template.

The template is a **Django monolith**: this one ASGI process
(``ameli_web.asgi:application``) serves BOTH the server-rendered HTML
dashboard and the JSON API — there is no separate frontend tier. It binds
``api_port`` and is the single upstream Caddy reverse-proxies to. The
workers (capture / maintenance / notifier) are separate out-of-band
processes against the same DB, not in the request path.

``ameli_app.web`` is an alias of this launcher on ``web_port`` — a
reserved seam for a future frontend split; see that module.
"""
from __future__ import annotations

import os

import uvicorn

from .config import load_settings


def main() -> None:
    settings = load_settings()
    os.environ.setdefault("DJANGO_SETTINGS_MODULE", "ameli_web.settings")
    print(f"Web Django en http://{settings.host}:{settings.api_port}")
    uvicorn.run("ameli_web.asgi:application", host=settings.host, port=settings.api_port, log_level="info")


if __name__ == "__main__":
    main()
