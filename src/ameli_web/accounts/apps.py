from __future__ import annotations

from django.apps import AppConfig
from django.db.models.signals import post_migrate


class AccountsConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "ameli_web.accounts"
    verbose_name = "Cuentas"

    def ready(self) -> None:
        from . import signals  # noqa: F401
        from .signals import ensure_role_groups

        post_migrate.connect(ensure_role_groups, sender=self)
