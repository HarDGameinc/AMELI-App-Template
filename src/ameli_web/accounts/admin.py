from __future__ import annotations

from django.contrib import admin
from django.contrib.auth.admin import UserAdmin as DjangoUserAdmin

from .models import User, UserSession


@admin.register(User)
class UserAdmin(DjangoUserAdmin):
    list_display = ("username", "display_name", "role", "is_active", "is_staff", "last_login")
    list_filter = ("role", "is_active", "theme_preference")
    search_fields = ("username", "display_name", "email")
    fieldsets = DjangoUserAdmin.fieldsets + (
        (
            "AMELI",
            {
                "fields": (
                    "display_name",
                    "role",
                    "theme_preference",
                    "avatar",
                    "must_change_password",
                    "created_at",
                    "updated_at",
                )
            },
        ),
    )
    readonly_fields = ("created_at", "updated_at", "last_login")


@admin.register(UserSession)
class UserSessionAdmin(admin.ModelAdmin):
    list_display = ("user", "session_key", "last_seen_at", "ip_address", "revoked_at")
    list_filter = ("revoked_at",)
    search_fields = ("user__username", "session_key", "ip_address", "user_agent")
    readonly_fields = ("created_at", "last_seen_at")
