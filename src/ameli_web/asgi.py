from __future__ import annotations

import logging
import os

from django.core.asgi import get_asgi_application

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "ameli_web.settings")

# Configure root logging BEFORE telemetry boots so its ``otel.enabled``
# / ``otel.disabled`` lines (and any other ``logger.info()`` from boot
# helpers loaded by Django startup) actually land somewhere.
#
# Guard with ``hasHandlers()`` so a test harness that already
# installed its own handler (pytest's caplog) is not stomped.
# ``configure_logging`` removes existing root handlers outright, which
# would silently break pytest's log capture.
if not logging.getLogger().hasHandlers():
    from ameli_app.logging_utils import configure_logging  # noqa: E402

    configure_logging()

# Initialise OpenTelemetry BEFORE the Django application is built so
# the Django auto-instrumentation can wrap middlewares as they load.
# When ``AMELI_APP_OTEL_EXPORTER_OTLP_ENDPOINT`` is empty, this is a
# no-op — see ``telemetry.setup_otel``.
from .telemetry import setup_otel, wrap_asgi_application  # noqa: E402

setup_otel()

# Wrap the ASGI app so each HTTP request becomes the parent span of
# the DB / outbound / manual spans emitted downstream. NoOp when
# OTel is inactive — returns the original application unchanged.
application = wrap_asgi_application(get_asgi_application())
