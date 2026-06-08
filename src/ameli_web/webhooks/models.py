from __future__ import annotations

from django.conf import settings
from django.db import models


class WebhookEndpoint(models.Model):
    """An external HTTP endpoint that wants to receive AMELI audit events.

    Each row owns its own ``secret`` (random 32 bytes hex) used to sign
    the payload via HMAC-SHA256. Operators rotate the secret by deleting
    and recreating the endpoint — there is no live rotation flow yet
    because the use case is internal scripts and Slack/Discord webhooks
    where re-pasting the URL is cheap.
    """

    name = models.CharField(max_length=120)
    url = models.URLField(max_length=2000)
    secret = models.CharField(max_length=80)
    events = models.JSONField(
        default=list,
        blank=True,
        help_text=(
            "List of audit ``action`` strings this endpoint subscribes to. "
            "Empty list means ALL events."
        ),
    )
    enabled = models.BooleanField(default=True)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="webhook_endpoints",
    )
    created_at = models.DateTimeField(auto_now_add=True)
    last_triggered_at = models.DateTimeField(blank=True, null=True)
    last_success_at = models.DateTimeField(blank=True, null=True)
    last_failure_at = models.DateTimeField(blank=True, null=True)
    total_deliveries = models.PositiveIntegerField(default=0)
    total_failures = models.PositiveIntegerField(default=0)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self) -> str:
        return f"webhook::{self.name}"

    def subscribed_to(self, action: str) -> bool:
        """Empty ``events`` list = subscribed to everything, by convention.

        Stored as a list so the admin UI and serialiser can show the
        subscription set without a join.
        """
        if not self.events:
            return True
        return action in self.events


class WebhookDelivery(models.Model):
    """Single attempt to POST a payload to a ``WebhookEndpoint``.

    We persist the outcome (success/failure, status code, response excerpt)
    so the admin UI can show recent deliveries when an operator complains
    that "the webhook stopped working".
    """

    endpoint = models.ForeignKey(
        WebhookEndpoint, on_delete=models.CASCADE, related_name="deliveries"
    )
    event_action = models.CharField(max_length=80)
    event_payload = models.JSONField(default=dict, blank=True)
    status_code = models.PositiveIntegerField(blank=True, null=True)
    response_excerpt = models.CharField(max_length=400, blank=True)
    success = models.BooleanField(default=False)
    error = models.CharField(max_length=400, blank=True)
    duration_ms = models.PositiveIntegerField(blank=True, null=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self) -> str:
        return f"delivery::{self.endpoint_id}::{self.event_action}"
