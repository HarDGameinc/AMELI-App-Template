from __future__ import annotations

from django.apps import AppConfig


class WebhooksConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "ameli_web.webhooks"
    label = "webhooks"

    def ready(self) -> None:
        # Wire the AuditEvent post_save dispatcher.
        from . import signals  # noqa: F401
