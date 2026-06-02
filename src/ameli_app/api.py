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
