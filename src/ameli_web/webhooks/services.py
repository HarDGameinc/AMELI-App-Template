from __future__ import annotations

import hashlib
import hmac
import ipaddress
import json
import secrets
import socket
import time
from typing import Any
from urllib import error as urllib_error
from urllib import request as urllib_request
from urllib.parse import urlparse

from django.utils import timezone

from .models import WebhookDelivery, WebhookEndpoint

_DEFAULT_TIMEOUT_SECONDS = 5
_MAX_RESPONSE_EXCERPT = 400


class WebhookTargetForbidden(Exception):
    """Raised when an endpoint URL resolves to a private/loopback/reserved
    address that the dispatcher must refuse (SSRF mitigation).

    A superadmin (or compromised superadmin account) could otherwise point
    a webhook at ``http://169.254.169.254/`` to read cloud metadata, at
    ``http://127.0.0.1:5432/`` to fingerprint internal services, or at
    ``http://10.0.0.1/admin/`` to pivot to lateral systems.
    """


def _is_safe_target_address(host: str) -> bool:
    """Resolve ``host`` and accept only globally routable IP addresses.

    Refuses loopback, link-local, multicast, reserved, private (RFC1918),
    unspecified, and shared address space. Also blocks IPv4-mapped IPv6
    variants of the same to defeat ``::ffff:10.0.0.1`` style tricks.
    """
    try:
        infos = socket.getaddrinfo(host, None)
    except socket.gaierror:
        return False
    for info in infos:
        sockaddr = info[4]
        raw_ip = sockaddr[0]
        try:
            ip_obj = ipaddress.ip_address(raw_ip)
        except ValueError:
            return False
        # Unmap IPv4-in-IPv6 so the private-range check matches.
        if isinstance(ip_obj, ipaddress.IPv6Address) and ip_obj.ipv4_mapped:
            ip_obj = ip_obj.ipv4_mapped
        if (
            ip_obj.is_loopback
            or ip_obj.is_link_local
            or ip_obj.is_multicast
            or ip_obj.is_reserved
            or ip_obj.is_private
            or ip_obj.is_unspecified
        ):
            return False
    return True


def _assert_target_is_safe(url: str) -> None:
    parsed = urlparse(url)
    host = parsed.hostname or ""
    if not host:
        raise WebhookTargetForbidden("webhook url has no hostname")
    if not _is_safe_target_address(host):
        raise WebhookTargetForbidden(
            f"webhook target {host!r} resolves to a private or reserved address; "
            "refusing to deliver to avoid SSRF"
        )


def _generate_secret() -> str:
    """Return a hex-encoded 32-byte secret. Hex keeps it printable for
    operators to copy into Slack/Discord configuration."""
    return secrets.token_hex(32)


def _sign(secret: str, body: bytes) -> str:
    return hmac.new(secret.encode("utf-8"), body, hashlib.sha256).hexdigest()


def serialize_endpoint(endpoint: WebhookEndpoint, *, include_secret: bool = False) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "id": endpoint.id,
        "name": endpoint.name,
        "url": endpoint.url,
        "events": list(endpoint.events or []),
        "enabled": endpoint.enabled,
        "created_at": endpoint.created_at.isoformat() if endpoint.created_at else None,
        "last_triggered_at": endpoint.last_triggered_at.isoformat() if endpoint.last_triggered_at else None,
        "last_success_at": endpoint.last_success_at.isoformat() if endpoint.last_success_at else None,
        "last_failure_at": endpoint.last_failure_at.isoformat() if endpoint.last_failure_at else None,
        "total_deliveries": endpoint.total_deliveries,
        "total_failures": endpoint.total_failures,
    }
    if include_secret:
        payload["secret"] = endpoint.secret
    return payload


def serialize_delivery(delivery: WebhookDelivery) -> dict[str, Any]:
    return {
        "id": delivery.id,
        "endpoint_id": delivery.endpoint_id,
        "event_action": delivery.event_action,
        "status_code": delivery.status_code,
        "response_excerpt": delivery.response_excerpt,
        "success": delivery.success,
        "error": delivery.error,
        "duration_ms": delivery.duration_ms,
        "created_at": delivery.created_at.isoformat() if delivery.created_at else None,
    }


def create_webhook_endpoint(*, name: str, url: str, events: list[str] | None = None, user=None) -> WebhookEndpoint:
    """Create an endpoint with a freshly generated secret.

    Returns the model instance; serialize with ``include_secret=True`` once
    to show the operator the value, never again afterwards (the field is
    available on subsequent reads but the UI hides it).
    """
    clean_name = (name or "").strip()
    clean_url = (url or "").strip()
    if not clean_name:
        raise ValueError("webhook name is required")
    if not clean_url.startswith(("http://", "https://")):
        raise ValueError("webhook url must start with http:// or https://")
    # Refuse private/loopback targets at create time so an operator gets a
    # clear error instead of "all my deliveries are failing silently".
    try:
        _assert_target_is_safe(clean_url)
    except WebhookTargetForbidden as exc:
        raise ValueError(str(exc)) from exc
    clean_events = [str(e).strip() for e in (events or []) if str(e).strip()]
    endpoint = WebhookEndpoint.objects.create(
        name=clean_name,
        url=clean_url,
        events=clean_events,
        secret=_generate_secret(),
        created_by=user if user and getattr(user, "is_authenticated", False) else None,
    )
    return endpoint


def revoke_webhook_endpoint(endpoint_id: int) -> WebhookEndpoint:
    endpoint = WebhookEndpoint.objects.filter(id=endpoint_id).first()
    if endpoint is None:
        raise ValueError("webhook not found")
    endpoint.enabled = False
    endpoint.save(update_fields=["enabled"])
    return endpoint


def deliver_event(endpoint: WebhookEndpoint, *, action: str, payload: dict[str, Any]) -> WebhookDelivery:
    """POST the event to the endpoint URL and persist the outcome.

    Synchronous on purpose: there is no worker queue yet and these are
    low-volume (audit events fire on user actions). A 5 second timeout
    caps the cost on a flaky receiver. If this becomes a hotspot, swap
    in a background worker and keep the same signature.
    """
    timestamp = timezone.now().isoformat()
    body_dict = {
        "event": action,
        "payload": payload,
        "timestamp": timestamp,
        "endpoint_id": endpoint.id,
    }
    body = json.dumps(body_dict, ensure_ascii=False, sort_keys=True).encode("utf-8")
    signature = _sign(endpoint.secret, body)
    headers = {
        "Content-Type": "application/json",
        "X-Ameli-Event": action,
        "X-Ameli-Timestamp": timestamp,
        "X-Ameli-Signature": f"sha256={signature}",
        "User-Agent": "AMELI-Webhook/1.0",
    }

    start = time.monotonic()
    status_code: int | None = None
    response_excerpt = ""
    error_text = ""
    success = False

    # Re-check the target at delivery time. DNS records can change between
    # ``create`` and ``deliver`` (rebinding attacks); revalidating here
    # closes that window cheaply.
    try:
        _assert_target_is_safe(endpoint.url)
    except WebhookTargetForbidden as exc:
        delivery = WebhookDelivery.objects.create(
            endpoint=endpoint,
            event_action=action,
            event_payload=payload,
            status_code=None,
            response_excerpt="",
            success=False,
            error=str(exc)[:_MAX_RESPONSE_EXCERPT],
            duration_ms=0,
        )
        now = timezone.now()
        endpoint.last_triggered_at = now
        endpoint.total_deliveries = (endpoint.total_deliveries or 0) + 1
        endpoint.last_failure_at = now
        endpoint.total_failures = (endpoint.total_failures or 0) + 1
        endpoint.save(
            update_fields=[
                "last_triggered_at", "last_failure_at",
                "total_deliveries", "total_failures",
            ]
        )
        return delivery

    request = urllib_request.Request(endpoint.url, data=body, headers=headers, method="POST")
    try:
        with urllib_request.urlopen(request, timeout=_DEFAULT_TIMEOUT_SECONDS) as response:
            status_code = response.status
            response_excerpt = response.read(_MAX_RESPONSE_EXCERPT).decode("utf-8", errors="replace")
            success = 200 <= status_code < 300
    except urllib_error.HTTPError as exc:
        status_code = exc.code
        try:
            response_excerpt = exc.read(_MAX_RESPONSE_EXCERPT).decode("utf-8", errors="replace")
        except Exception:
            response_excerpt = ""
        success = 200 <= status_code < 300
        error_text = f"HTTPError {exc.code}"
    except urllib_error.URLError as exc:
        error_text = f"URLError: {exc.reason}"[:400]
    except Exception as exc:  # network, dns, etc.
        error_text = f"{type(exc).__name__}: {exc}"[:400]

    duration_ms = int((time.monotonic() - start) * 1000)

    delivery = WebhookDelivery.objects.create(
        endpoint=endpoint,
        event_action=action,
        event_payload=payload,
        status_code=status_code,
        response_excerpt=response_excerpt[:_MAX_RESPONSE_EXCERPT],
        success=success,
        error=error_text,
        duration_ms=duration_ms,
    )

    now = timezone.now()
    endpoint.last_triggered_at = now
    endpoint.total_deliveries = (endpoint.total_deliveries or 0) + 1
    if success:
        endpoint.last_success_at = now
    else:
        endpoint.last_failure_at = now
        endpoint.total_failures = (endpoint.total_failures or 0) + 1
    endpoint.save(
        update_fields=[
            "last_triggered_at", "last_success_at", "last_failure_at",
            "total_deliveries", "total_failures",
        ]
    )
    return delivery


def dispatch_for_audit_event(action: str, payload: dict[str, Any]) -> int:
    """Deliver an audit event to every enabled, subscribed endpoint.

    Returns the number of endpoints attempted. Failures are swallowed so a
    crashing webhook never breaks the audit recording path that called us;
    they're visible in ``WebhookDelivery`` rows for the operator.
    """
    endpoints = list(WebhookEndpoint.objects.filter(enabled=True))
    attempted = 0
    for endpoint in endpoints:
        if not endpoint.subscribed_to(action):
            continue
        try:
            deliver_event(endpoint, action=action, payload=payload)
        except Exception:  # pragma: no cover - hard failure inside dispatcher
            pass
        attempted += 1
    return attempted
