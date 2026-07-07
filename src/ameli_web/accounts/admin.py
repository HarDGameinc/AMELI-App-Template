from __future__ import annotations

from django.contrib import admin, messages
from django.contrib.auth.admin import UserAdmin as DjangoUserAdmin
from django.utils import timezone

from .models import OutboundEmail, User, UserSession


@admin.register(User)
class UserAdmin(DjangoUserAdmin):
    list_display = ("username", "display_name", "role", "is_active", "is_staff", "last_login")
    list_filter = ("role", "is_active", "theme_preference")
    search_fields = ("username", "display_name", "email")
    # ``DjangoUserAdmin.fieldsets`` is typed as Optional list; in
    # practice Django ships a non-None default, so the + is safe.
    fieldsets = DjangoUserAdmin.fieldsets + (  # type: ignore[operator]
        (
            "AMELI",
            {
                "fields": (
                    "display_name",
                    "role",
                    "theme_preference",
                    "color_theme",
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


@admin.action(description="Reintentar ahora (forzar next_retry_at = now)")
def retry_now(modeladmin, request, queryset):
    """Bump pending rows so the next notifier tick picks them up.

    Only acts on rows still in ``pending``; already-sent or failed
    rows are skipped without touching them.
    """
    updated = queryset.filter(status=OutboundEmail.STATUS_PENDING).update(
        next_retry_at=timezone.now(),
    )
    skipped = queryset.exclude(status=OutboundEmail.STATUS_PENDING).count()
    if updated:
        messages.success(
            request,
            f"{updated} row(s) marcadas para reintento inmediato.",
        )
    if skipped:
        messages.warning(
            request,
            f"{skipped} row(s) ignoradas (status != pending).",
        )


@admin.register(OutboundEmail)
class OutboundEmailAdmin(admin.ModelAdmin):
    """Operational view of the email retry queue.

    Rows are read-only from the UI on purpose — the queue is driven
    by the worker. Operators get visibility (what is queued, why it
    failed) and one action ("retry now") to compress the backoff
    when SMTP just came back online. Editing fields directly would
    risk inconsistent state (e.g. lowering attempts past a
    permanent failure).
    """

    list_display = (
        "id",
        "status",
        "attempts",
        "max_attempts",
        "audit_action",
        "target_username",
        "subject",
        "next_retry_at",
        "created_at",
    )
    list_filter = ("status", "audit_action", "use_ascii_passthrough")
    search_fields = (
        "subject",
        "target_username",
        "audit_action",
        "last_error",
    )
    readonly_fields = (
        "subject",
        "from_email",
        "to_emails",
        "use_ascii_passthrough",
        "audit_action",
        "audit_payload",
        "target_username",
        "status",
        "attempts",
        "max_attempts",
        "next_retry_at",
        "last_error",
        "expires_at",
        "created_at",
        "updated_at",
        "body",
    )
    actions = [retry_now]
    ordering = ("-id",)

    def has_add_permission(self, request) -> bool:
        # The queue is populated by send_with_retry. Manually adding
        # a row from the admin would bypass the audit hooks.
        return False

    def has_delete_permission(self, request, obj=None) -> bool:
        # Operators should not delete rows: the audit trail relies on
        # them. If you really want to purge, do it from the shell.
        return False
