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
