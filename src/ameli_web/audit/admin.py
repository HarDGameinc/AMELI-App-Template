from __future__ import annotations

from django.contrib import admin

from .models import AuditEvent


@admin.register(AuditEvent)
class AuditEventAdmin(admin.ModelAdmin):
    list_display = ("created_at", "action", "actor_username", "target_username")
    list_filter = ("action", "created_at")
    search_fields = ("actor_username", "target_username", "payload")
    readonly_fields = ("created_at",)
