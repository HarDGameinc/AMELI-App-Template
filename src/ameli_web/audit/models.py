from __future__ import annotations

from django.db import models


class AuditEvent(models.Model):
    actor_username = models.CharField(max_length=150, blank=True)
    action = models.CharField(max_length=80)
    target_username = models.CharField(max_length=150, blank=True)
    payload = models.JSONField(default=dict, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    # Hash chain: each row's hmac covers the previous row's hmac plus
    # this row's canonical payload. ``ameli-app verify-audit`` walks
    # them in order; any tampering (edited row, deleted row, reordered
    # row) breaks the chain at the first divergence.
    prev_hmac = models.CharField(max_length=128, blank=True, default="")
    hmac = models.CharField(max_length=128, blank=True, default="", db_index=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self) -> str:
        actor = self.actor_username or "anon"
        return f"{self.action}::{actor}"
