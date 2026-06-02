from pathlib import Path


def _version_file() -> Path:
    return Path(__file__).resolve().parents[2] / "VERSION"


def get_version() -> str:
    try:
        return _version_file().read_text(encoding="utf-8").strip()
    except FileNotFoundError:
        return "v0.0.0-dev"


__version__ = get_version()
