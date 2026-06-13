# syntax=docker/dockerfile:1.7

# Multi-stage build so the final image doesn't carry build toolchains.
# Targets:
#   builder  — installs requirements into a venv
#   runtime  — copies the venv + source, runs as a non-root uid
#
# Tagging convention:
#   ameli-app-template:dev    — dev compose + smoke tests
#   ameli-app-template:<sha>  — pinned per commit for prod

ARG PYTHON_VERSION=3.12

# ----- builder -----
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
COPY requirements.txt requirements-dev.txt pyproject.toml ./
COPY src ./src

RUN python -m venv /opt/venv
ENV PATH="/opt/venv/bin:$PATH"
RUN pip install --upgrade pip \
    && pip install -r requirements.txt \
    && pip install -e .

# ----- runtime -----
FROM python:${PYTHON_VERSION}-slim AS runtime

ENV PATH="/opt/venv/bin:$PATH" \
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
