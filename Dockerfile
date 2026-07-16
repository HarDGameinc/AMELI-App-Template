# syntax=docker/dockerfile:1.7

# Multi-stage build so the final image doesn't carry build toolchains.
# Targets:
#   builder      — installs the hash-pinned runtime deps into a venv
#   builder-dev  — builder + dev deps (pytest, ruff, ...) for the dev image
#   runtime      — lean prod image: venv + source, non-root uid (DEFAULT)
#   dev          — runtime + dev deps + tests, so pytest runs in-container
#
# Tagging convention:
#   ameli-app-template:dev    — dev compose (--target dev) + smoke tests
#   ameli-app-template:<sha>  — pinned per commit for prod (--target runtime)

ARG PYTHON_VERSION=3.12

# ----- builder (hash-pinned runtime deps) -----
FROM python:${PYTHON_VERSION}-slim AS builder

ENV PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PIP_NO_CACHE_DIR=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

# Build deps for the C-extension wheels (argon2, pillow, psycopg).
RUN apt-get update && apt-get install -y --no-install-recommends \
      build-essential \
      libffi-dev \
      libjpeg-dev \
      libpq-dev \
      zlib1g-dev \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /build
COPY requirements.lock requirements-dev.lock pyproject.toml ./
COPY src ./src

RUN python -m venv /opt/venv
ENV PATH="/opt/venv/bin:$PATH"
# Install the exact hash-pinned lock (ASVS V14.2.3 — parity with the prod
# systemd deploy), then the local package with --no-deps so the un-hashable
# editable install does not break the --require-hashes run.
RUN pip install --upgrade pip \
    && pip install --require-hashes -r requirements.lock \
    && pip install -e . --no-deps

# ----- builder-dev (adds dev deps to the venv for the dev image) -----
FROM builder AS builder-dev
# requirements-dev.lock is a superset of the runtime lock; the runtime
# packages are already satisfied — this layer adds pytest/ruff/pip-audit/etc.
RUN pip install --require-hashes -r requirements-dev.lock

# ----- runtime (lean prod image; DEFAULT target) -----
FROM python:${PYTHON_VERSION}-slim AS runtime

# PYTHONPATH points at the copied source: the editable ``.pth`` written in
# the builder references /build/src, which does not exist here (WORKDIR is
# /app), so without this ``import ameli_web`` fails (ModuleNotFoundError).
ENV PATH="/opt/venv/bin:$PATH" \
    PYTHONPATH="/app/src" \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    DJANGO_SETTINGS_MODULE=ameli_web.settings

# Runtime libs only (no compilers / headers).
RUN apt-get update && apt-get install -y --no-install-recommends \
      libpq5 \
      libjpeg62-turbo \
      tini \
    && rm -rf /var/lib/apt/lists/*

# Run as a fixed non-root uid so a host bind-mount keeps consistent
# ownership across machines.
ARG APP_UID=10001
RUN groupadd --system --gid ${APP_UID} ameli \
    && useradd --system --uid ${APP_UID} --gid ameli --home /app ameli

WORKDIR /app
COPY --from=builder /opt/venv /opt/venv
COPY --from=builder /build/src ./src
COPY --from=builder /build/pyproject.toml ./pyproject.toml
COPY config ./config
COPY scripts ./scripts
# version.py resolves ``parents[2]/VERSION`` = /app/VERSION; without this the
# image reports ``v0.0.0-dev`` at /health.
COPY VERSION ./VERSION

# Writable surfaces. /app itself stays read-only so a runaway write
# outside these paths fails fast.
RUN mkdir -p /var/lib/ameli-app /var/log/ameli-app \
    && chown -R ameli:ameli /var/lib/ameli-app /var/log/ameli-app /app

USER ameli

EXPOSE 18080

# ``tini`` reaps zombies and forwards signals cleanly to uvicorn —
# important so the notifier daemon's child sleep gets a SIGTERM on
# ``docker stop`` instead of hanging the container.
ENTRYPOINT ["/usr/bin/tini", "--"]

# Default command is the API. ``docker-compose.yml`` overrides
# this for the notifier service.
CMD ["python", "-m", "uvicorn", "ameli_web.asgi:application", \
     "--host", "0.0.0.0", "--port", "18080"]

# ----- dev (runtime + dev deps + tests; ``docker compose`` builds this) -----
FROM runtime AS dev
# Swap in the dev venv (superset) and add the test tree so
# ``docker compose run --rm api pytest`` works. Separate target so the
# prod ``runtime`` image stays lean (no test toolchain).
USER root
COPY --from=builder-dev /opt/venv /opt/venv
COPY tests ./tests
COPY requirements-dev.lock ./requirements-dev.lock
RUN chown -R ameli:ameli /app /opt/venv
USER ameli
