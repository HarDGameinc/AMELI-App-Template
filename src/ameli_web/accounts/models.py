from __future__ import annotations

import secrets
from pathlib import Path

from django.contrib.auth.models import AbstractUser
from django.db import models


def avatar_upload_to(user: "User", filename: str) -> str:
    suffix = Path(filename or "avatar.png").suffix.lower() or ".png"
    safe_username = "".join(ch.lower() if ch.isalnum() else "-" for ch in (user.username or "user")).strip("-") or "user"
    return f"avatars/{safe_username}-{secrets.token_hex(8)}{suffix}"


class User(AbstractUser):
    ROLE_SUPERADMIN = "superadmin"
    ROLE_PUBLIC = "public"
    ROLE_CHOICES = [
        (ROLE_SUPERADMIN, "superadmin"),
        (ROLE_PUBLIC, "public"),
    ]
    THEME_AUTO = "auto"
    THEME_LIGHT = "light"
    THEME_DARK = "dark"
    THEME_CHOICES = [
        (THEME_AUTO, "Auto"),
        (THEME_LIGHT, "Claro"),
        (THEME_DARK, "Oscuro"),
    ]
    # Semantic constants kept for service / view code that needs to refer
    # to method "kinds" symbolically. Actual storage is now the
    # mfa_totp_enabled / mfa_email_enabled booleans below so both methods
    # can be enrolled simultaneously (stacked-methods industry pattern).
    MFA_METHOD_TOTP = "totp"
    MFA_METHOD_EMAIL = "email"

    display_name = models.CharField(max_length=80, blank=True)
    role = models.CharField(max_length=20, choices=ROLE_CHOICES, default=ROLE_PUBLIC)
    theme_preference = models.CharField(max_length=10, choices=THEME_CHOICES, default=THEME_AUTO)
    avatar = models.ImageField(upload_to=avatar_upload_to, blank=True, null=True)
    must_change_password = models.BooleanField(default=False)
    # Hard lock applied by ``check_login_throttle`` after too many
    # consecutive lockout windows. Cleared by an admin via the
    # ``admin_unlock_user`` service — never time-based, so a sustained
    # brute-force attempt cannot eventually wait it out.
    locked_at = models.DateTimeField(blank=True, null=True)
    locked_reason = models.CharField(max_length=64, blank=True, default="")
    mfa_secret = models.CharField(max_length=64, blank=True, default="")
    mfa_enabled = models.BooleanField(default=False)
    mfa_required = models.BooleanField(default=False)
    mfa_totp_enabled = models.BooleanField(default=False)
    mfa_email_enabled = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["username"]

    def save(self, *args, **kwargs):
        self.role = self.role or self.ROLE_PUBLIC
        if self.role == self.ROLE_SUPERADMIN:
            self.is_staff = True
            self.is_superuser = True
        else:
            self.is_staff = False
            self.is_superuser = False
        super().save(*args, **kwargs)

    @property
    def avatar_url(self) -> str | None:
        return self.avatar.url if self.avatar else None

    @property
    def display_identity_name(self) -> str:
        return self.display_name.strip() or self.username

    @property
    def initials(self) -> str:
        source = self.display_identity_name.replace("_", " ")
        letters = "".join(part[0].upper() for part in source.split() if part)
        return letters[:2] or "AM"

    @property
    def display_alias_value(self) -> str:
        return self.display_name.strip() or "Usando nombre de usuario"

    @property
    def display_avatar_value(self) -> str:
        return "Imagen cargada" if self.avatar else "Usando iniciales"

    @property
    def display_theme_label(self) -> str:
        return {
            self.THEME_AUTO: "Auto",
            self.THEME_LIGHT: "Claro",
            self.THEME_DARK: "Oscuro",
        }.get(self.theme_preference, "Auto")


class UserSession(models.Model):
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name="web_sessions")
    session_key = models.CharField(max_length=64, unique=True)
    created_at = models.DateTimeField(auto_now_add=True)
    last_seen_at = models.DateTimeField(auto_now=True)
    user_agent = models.CharField(max_length=512, blank=True)
    ip_address = models.CharField(max_length=128, blank=True)
    revoked_at = models.DateTimeField(blank=True, null=True)

    class Meta:
        ordering = ["-last_seen_at"]

    def __str__(self) -> str:
        return f"{self.user.username}::{self.session_key}"


class MFARecoveryCode(models.Model):
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name="recovery_codes")
    code_hash = models.CharField(max_length=128)
    created_at = models.DateTimeField(auto_now_add=True)
    used_at = models.DateTimeField(blank=True, null=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self) -> str:
        return f"{self.user.username}::recovery"


class MFAEmailChallenge(models.Model):
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name="email_challenges")
    code_hash = models.CharField(max_length=128)
    created_at = models.DateTimeField(auto_now_add=True)
    expires_at = models.DateTimeField()
    used_at = models.DateTimeField(blank=True, null=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self) -> str:
        return f"{self.user.username}::email-challenge"


class EmailChangeRequest(models.Model):
    """A pending email change waiting for double-opt-in confirmation.

    The legitimate user starts a change with their current password; we
    write a record here, email the NEW address with a confirm link, and
    email the OLD address with an alert + cancel link. The change is
    applied only when the new address proves it can receive mail.
    """

    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name="email_changes")
    new_email = models.EmailField()
    token_hash = models.CharField(max_length=128, db_index=True, unique=True)
    created_at = models.DateTimeField(auto_now_add=True)
    expires_at = models.DateTimeField()
    confirmed_at = models.DateTimeField(blank=True, null=True)
    cancelled_at = models.DateTimeField(blank=True, null=True)
    cancel_reason = models.CharField(max_length=64, blank=True, default="")
    ip_address = models.CharField(max_length=128, blank=True, default="")

    class Meta:
        ordering = ["-created_at"]

    def __str__(self) -> str:
        return f"{self.user.username}::email-change::{self.new_email}"

    @property
    def is_pending(self) -> bool:
        return self.confirmed_at is None and self.cancelled_at is None

    def is_expired(self, *, at=None) -> bool:
        from django.utils import timezone

        return (at or timezone.now()) >= self.expires_at


class ThrottleCounter(models.Model):
    """Atomic per-(scope, key, window) counter for the rate-limit helpers.

    The login / forgot-password / MFA-resend throttles used to count rows
    in ``AuditEvent`` with a plain ``COUNT(*)`` and decide based on the
    result. Two requests racing past the read could both observe the
    same below-threshold count and slip an extra attempt past the limit
    (a TOCTOU window). This table replaces the count source with a row
    we can ``SELECT FOR UPDATE`` so the increment-and-check is serial.

    ``unique_together`` keeps storage bounded: one row per (scope, key,
    window). Old windows can be pruned by a maintenance job; nothing
    breaks if they linger.
    """

    scope = models.CharField(max_length=32, db_index=True)
    key = models.CharField(max_length=128)
    window_start = models.DateTimeField()
    count = models.IntegerField(default=0)

    class Meta:
        unique_together = [("scope", "key", "window_start")]
        indexes = [
            models.Index(fields=["scope", "key", "window_start"]),
        ]

    def __str__(self) -> str:
        return f"{self.scope}::{self.key}::{self.window_start.isoformat()}={self.count}"


class OutboundEmail(models.Model):
    """Retry queue for emails whose inline send failed.

    Services that can tolerate eventual delivery (password reset,
    admin notifications) call ``services.send_with_retry`` which tries
    inline first and persists a row here only when the send raises.
    The ``notify`` worker processes pending rows on its tick using
    exponential backoff. After ``max_attempts`` the row is marked
    failed and audited so the operator can investigate.

    Bodies may contain time-limited tokens (reset URLs). The
    ``expires_at`` column lets us drop rows whose token won't be
    accepted anymore — better to fail loudly than ship a dead link.
    """

    STATUS_PENDING = "pending"
    STATUS_SENT = "sent"
    STATUS_FAILED = "failed"
    STATUS_CHOICES = [
        (STATUS_PENDING, "pending"),
        (STATUS_SENT, "sent"),
        (STATUS_FAILED, "failed"),
    ]

    subject = models.CharField(max_length=255)
    body = models.TextField()
    from_email = models.CharField(max_length=255, blank=True, default="")
    to_emails = models.JSONField(default=list)
    use_ascii_passthrough = models.BooleanField(default=False)
    audit_action = models.CharField(max_length=80, blank=True, default="")
    audit_payload = models.JSONField(default=dict, blank=True)
    target_username = models.CharField(max_length=150, blank=True, default="")
    status = models.CharField(
        max_length=10, choices=STATUS_CHOICES, default=STATUS_PENDING, db_index=True,
    )
    attempts = models.IntegerField(default=0)
    max_attempts = models.IntegerField(default=5)
    next_retry_at = models.DateTimeField(db_index=True)
    last_error = models.TextField(blank=True, default="")
    expires_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        indexes = [
            models.Index(fields=["status", "next_retry_at"]),
        ]
        ordering = ["next_retry_at", "id"]

    def __str__(self) -> str:
        return f"{self.status}::{self.subject}->{self.to_emails}"


class MaintenanceMode(models.Model):
    """Single-row table holding the maintenance-mode flag.

    When ``active`` is true the middleware shows a banner on every
    rendered page and, if ``read_only`` is also true, returns 503 to
    write requests (POST/PUT/PATCH/DELETE) from non-staff users. The
    intent is to keep the app reachable as a read-only window while
    a migration / deploy / DB maintenance runs, without dropping
    visitors entirely.

    The single-row guarantee is enforced by always reading/writing
    pk=1 from the service layer.
    """

    SINGLETON_PK = 1

    active = models.BooleanField(default=False)
    read_only = models.BooleanField(default=True)
    message = models.TextField(blank=True, default="")
    activated_at = models.DateTimeField(null=True, blank=True)
    deactivated_at = models.DateTimeField(null=True, blank=True)
    activated_by_username = models.CharField(max_length=150, blank=True, default="")
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self) -> str:
        return f"MaintenanceMode(active={self.active}, read_only={self.read_only})"
