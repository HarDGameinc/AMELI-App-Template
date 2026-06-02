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
