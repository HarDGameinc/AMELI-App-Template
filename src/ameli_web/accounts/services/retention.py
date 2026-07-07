"""Retention sweep — purge stale operational rows + re-anchor the audit chain.

Moved from services/__init__.py (PC-1 cleanup, 2026-07-01).
Public symbols re-exported via services/__init__.py; always import
from there, not directly.
"""
from __future__ import annotations

from datetime import timedelta
from typing import Any

from django.db import transaction
from django.utils import timezone

from ameli_web.audit.models import AuditEvent

from ..models import (
    EmailChangeRequest,
    MFAEmailChallenge,
    OutboundEmail,
    ThrottleCounter,
    UserSession,
)
from .audit import _audit_hmac, _audit_hmac_key, record_audit


def run_retention_sweep(
    *,
    sessions_revoked_max_age_days: int = 30,
    outbound_email_sent_max_age_days: int = 30,
    throttle_counter_max_age_days: int = 1,
    email_change_resolved_max_age_days: int = 30,
    mfa_email_challenge_consumed_max_age_days: int = 7,
    audit_max_age_days: int | None = None,
) -> dict[str, Any]:
    """Purge old operational rows so the DB doesn't grow without bound.

    The sweep is conservative and idempotent: only resolved /
    expired / revoked rows are touched, never anything still in
    flight. Defaults align with what an operator would expect from
    a baseline retention policy on a fresh deploy; callers can
    override per-knob for tighter or looser windows.

    Returns a dict of ``{table: rows_deleted}`` plus an ``audit_*``
    summary so the operator can confirm the run in journalctl /
    /admin/.

    ``audit_max_age_days=None`` skips the audit prune — the audit
    chain is the long-term log of "who did what" and most policies
    keep it. Pass an integer to enforce a horizon (rows older are
    deleted and a fresh chain anchor is written so verify-audit
    stays clean — anchor logic lives in
    :func:`_anchor_audit_chain_after_prune`).
    """
    now = timezone.now()
    counts: dict[str, int] = {}

    # 1) Revoked / stale UserSession rows.
    cutoff = now - timedelta(days=sessions_revoked_max_age_days)
    n, _ = UserSession.objects.filter(
        revoked_at__isnull=False, revoked_at__lt=cutoff,
    ).delete()
    counts["user_sessions"] = n

    # 2) Sent / failed OutboundEmail rows.
    cutoff = now - timedelta(days=outbound_email_sent_max_age_days)
    n, _ = OutboundEmail.objects.filter(
        status__in=[OutboundEmail.STATUS_SENT, OutboundEmail.STATUS_FAILED],
        updated_at__lt=cutoff,
    ).delete()
    counts["outbound_emails"] = n

    # 3) ThrottleCounter rows whose window is well in the past.
    cutoff = now - timedelta(days=throttle_counter_max_age_days)
    n, _ = ThrottleCounter.objects.filter(window_start__lt=cutoff).delete()
    counts["throttle_counters"] = n

    # 4) Resolved (confirmed / cancelled) EmailChangeRequest rows.
    cutoff = now - timedelta(days=email_change_resolved_max_age_days)
    n, _ = EmailChangeRequest.objects.filter(
        created_at__lt=cutoff,
    ).exclude(confirmed_at__isnull=True, cancelled_at__isnull=True).delete()
    counts["email_change_requests"] = n

    # 5) Used / expired MFA email challenges.
    cutoff = now - timedelta(days=mfa_email_challenge_consumed_max_age_days)
    n, _ = MFAEmailChallenge.objects.filter(
        created_at__lt=cutoff,
    ).filter(used_at__isnull=False).delete()
    counts["mfa_email_challenges"] = n

    counts["audit_events"] = 0
    if audit_max_age_days is not None:
        counts["audit_events"] = _prune_audit_with_anchor(
            cutoff=now - timedelta(days=audit_max_age_days),
        )

    record_audit(
        "retention_sweep",
        target_username="",
        payload={"counts": dict(counts)},
    )
    return {"ok": True, "counts": counts, "swept_at": now.isoformat()}


def _prune_audit_with_anchor(*, cutoff) -> int:
    """Delete audit rows older than ``cutoff`` and re-anchor the chain.

    The chain links each row to the previous one via ``prev_hmac``;
    naively deleting the head would orphan the tail. We:

    1. Delete the rows older than ``cutoff`` in one transaction.
    2. Re-chain every surviving row that already carried an hmac
       under the LIVE key: the first survivor restarts with
       ``prev_hmac=""``, subsequent rows chain forward through the
       new hmacs. This keeps post-prune rows cryptographically
       anchored — a DB-write attacker that edits a surviving row
       cannot rehash it without the key — while accepting that we
       lose the cryptographic link back to the now-deleted head.
       Rows that pre-dated the chain (``hmac=""``) stay legacy and
       reset the prev pointer the same way :func:`verify_audit_chain`
       does.
    3. Write a ``retention_audit_anchor`` row that becomes the new
       head of the chain, chained from the last re-chained survivor.

    Old behaviour demoted survivors to ``hmac=""`` which made the
    post-prune tail invisible to ``verify_audit_chain`` and let any
    attacker with DB write access tamper undetected; the re-chain
    above preserves that guarantee going forward. Operators that
    need to keep the original hmacs (e.g. proof of integrity over
    the pruned window) should archive the audit table externally
    before running this prune — the prune still re-stamps surviving
    rows, so the canonical bytes change.
    """
    deleted = 0
    with transaction.atomic():
        deleted, _ = AuditEvent.objects.filter(created_at__lt=cutoff).delete()
        if not deleted:
            return 0

        key = _audit_hmac_key()
        new_prev = ""
        if key:
            # 2) Walk survivors in id order, re-chain each chained row.
            survivors = (
                AuditEvent.objects.filter(created_at__gte=cutoff)
                .order_by("id")
            )
            for row in survivors.iterator(chunk_size=500):
                if not row.hmac:
                    # Pre-chain legacy row; mirror verify_audit_chain
                    # by leaving it alone and restarting prev.
                    new_prev = ""
                    continue
                new_hmac = _audit_hmac(
                    key=key,
                    prev_hmac=new_prev,
                    action=row.action,
                    actor_username=row.actor_username,
                    target_username=row.target_username,
                    payload=row.payload,
                    created_at=row.created_at,
                )
                AuditEvent.objects.filter(pk=row.pk).update(
                    prev_hmac=new_prev, hmac=new_hmac,
                )
                new_prev = new_hmac
        else:
            # No key configured: the chain is already empty, so
            # surviving rows have nothing to re-stamp. Reset prev
            # so the anchor still writes with prev_hmac="".
            AuditEvent.objects.filter(created_at__gte=cutoff).update(prev_hmac="")

        # 3) Fresh anchor chained from the last re-chained survivor.
        event = AuditEvent.objects.create(
            actor_username="",
            target_username="",
            action="retention_audit_anchor",
            payload={"deleted_rows": deleted, "cutoff": cutoff.isoformat()},
            prev_hmac=new_prev,
        )
        if key:
            event.refresh_from_db(fields=["created_at"])
            event.hmac = _audit_hmac(
                key=key,
                prev_hmac=new_prev,
                action=event.action,
                actor_username=event.actor_username,
                target_username=event.target_username,
                payload=event.payload,
                created_at=event.created_at,
            )
            event.save(update_fields=["hmac"])
    return deleted
