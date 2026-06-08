from __future__ import annotations

from django.db.models.signals import post_save
from django.dispatch import receiver

from ameli_web.audit.models import AuditEvent

from .services import dispatch_for_audit_event


@receiver(post_save, sender=AuditEvent)
def _dispatch_webhook_for_audit_event(sender, instance: AuditEvent, created: bool, **kwargs):
    """Fan out new audit events to all enabled webhooks.

    Hook only on ``created=True`` because we don't want to re-fire when
    an event row is touched later (the model only mutates ``created_at``
    via tests; in production audit events are insert-only). The dispatcher
    catches its own exceptions so a flaky receiver never breaks the audit
    write path.
    """
    if not created:
        return
    dispatch_for_audit_event(instance.action, instance.payload or {})
