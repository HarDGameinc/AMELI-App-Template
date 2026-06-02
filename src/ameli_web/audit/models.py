from __future__ import annotations

from django.db import models


class AuditEvent(models.Model):
    actor_username = models.CharField(max_length=150, blank=True)
    action = models.CharField(max_length=80)
    target_username = models.CharField(max_length=150, blank=True)
    payload = models.JSONField(default=dict, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self) -> str:
        actor = self.actor_username or "anon"
        return f"{self.action}::{actor}"
