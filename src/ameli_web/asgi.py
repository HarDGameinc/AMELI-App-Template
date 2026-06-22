from __future__ import annotations

import os

from django.core.asgi import get_asgi_application

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "ameli_web.settings")

# Initialise OpenTelemetry BEFORE the Django application is built so
# the Django auto-instrumentation can wrap middlewares as they load.
# When ``AMELI_APP_OTEL_EXPORTER_OTLP_ENDPOINT`` is empty, this is a
# no-op — see ``telemetry.setup_otel``.
from .telemetry import setup_otel  # noqa: E402 - must follow settings env setup

setup_otel()

application = get_asgi_application()
