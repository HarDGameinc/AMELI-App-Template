"""Coverage for the double-opt-in email change flow (#5).

Each scenario walks the full pipeline (request → confirm or cancel) so a
future refactor cannot silently drop one of the guardrails:

* current password required
* alert email to the OLD address (with a cancel link)
* confirm email to the NEW address
* token expires
* MFA-email gets cleared on confirm
"""

from __future__ import annotations

from datetime import timedelta

import pytest
from django.contrib.auth import get_user_model
from django.core import mail
from django.utils import timezone

from ameli_web.accounts.models import EmailChangeRequest
from ameli_web.accounts.services import (
    bootstrap_superadmin,
    cancel_email_change,
    confirm_email_change,
    create_user_account,
    pending_email_change_for,
    request_email_change,
)

User = get_user_model()

ADMIN_PASSWORD = "AdminPass!12?Secure"
TESTER_PASSWORD = "TesterPass!12?Secure"


@pytest.fixture()
def admin_user(db):
    bootstrap_superadmin(username="admin", password=ADMIN_PASSWORD)
    return User.objects.get(username="admin")


@pytest.fixture()
def tester(db, admin_user, settings):
    settings.EMAIL_BACKEND = "django.core.mail.backends.locmem.EmailBackend"
    settings.AMELI_APP_PUBLIC_URL_BASE = "http://localhost:8080"
    create_user_account(
        actor_username="admin",
        username="tester",
        password=TESTER_PASSWORD,
        role="public",
    )
    user = User.objects.get(username="tester")
    user.email = "old@example.com"
    user.save()
    mail.outbox.clear()
    return user


def _make_request(client):
    """Build a fake request-like object exposing the bits the service
    helper actually reads (``build_absolute_uri``). We only ever exercise
    the fallback path with ``AMELI_APP_PUBLIC_URL_BASE`` configured."""

    class FakeRequest:
        def build_absolute_uri(self, path: str) -> str:
            return f"http://localhost:8080{path}"

    return FakeRequest()


@pytest.mark.django_db
def test_request_email_change_persists_and_sends_two_mails(tester):
    result = request_email_change(
        tester,
        new_email="new@example.com",
        current_password=TESTER_PASSWORD,
        request=_make_request(None),
        ip="10.0.0.5",
    )
    assert result["ok"] is True
    assert result["status"] == "pending"
    # One mail to the new address (confirm) + one to the old (alert).
    addresses = sorted([m.to[0] for m in mail.outbox])
    assert addresses == ["new@example.com", "old@example.com"]
    # The persisted record carries hash, expiry and ip.
    record = EmailChangeRequest.objects.get(id=result["request_id"])
    assert record.new_email == "new@example.com"
    assert record.is_pending is True
    assert record.ip_address == "10.0.0.5"
    # And the user's primary email is NOT changed yet.
    tester.refresh_from_db()
    assert tester.email == "old@example.com"


@pytest.mark.django_db
def test_request_email_change_rejects_wrong_password(tester):
    with pytest.raises(ValueError, match="contrasena"):
        request_email_change(
            tester,
            new_email="new@example.com",
            current_password="not-the-password",
            request=_make_request(None),
        )
    assert EmailChangeRequest.objects.count() == 0


@pytest.mark.django_db
def test_request_email_change_rejects_same_address(tester):
    with pytest.raises(ValueError, match="igual"):
        request_email_change(
            tester,
            new_email="old@example.com",
            current_password=TESTER_PASSWORD,
            request=_make_request(None),
        )


@pytest.mark.django_db
def test_request_email_change_supersedes_previous_pending(tester):
    request_email_change(
        tester,
        new_email="new1@example.com",
        current_password=TESTER_PASSWORD,
        request=_make_request(None),
    )
    request_email_change(
        tester,
        new_email="new2@example.com",
        current_password=TESTER_PASSWORD,
        request=_make_request(None),
    )
    pending = EmailChangeRequest.objects.filter(
        user=tester, confirmed_at__isnull=True, cancelled_at__isnull=True
    )
    assert pending.count() == 1
    assert pending.first().new_email == "new2@example.com"


@pytest.mark.django_db
def test_confirm_email_change_applies_new_address(tester):
    # Capture the token from the confirm mail body.
    request_email_change(
        tester,
        new_email="new@example.com",
        current_password=TESTER_PASSWORD,
        request=_make_request(None),
    )
    record = EmailChangeRequest.objects.get(user=tester)
    # Extract the token from the confirm URL (last path segment before /).
    confirm_msg = next(m for m in mail.outbox if m.to == ["new@example.com"])
    import re

    match = re.search(r"/confirm/(\d+)/([^/\s]+)/", confirm_msg.body)
    assert match
    request_id, token = int(match.group(1)), match.group(2)
    assert request_id == record.id

    result = confirm_email_change(request_id=request_id, token_plaintext=token)
    assert result["status"] == "confirmed"
    tester.refresh_from_db()
    assert tester.email == "new@example.com"
    record.refresh_from_db()
    assert record.confirmed_at is not None


@pytest.mark.django_db
def test_cancel_email_change_via_alert_link(tester):
    request_email_change(
        tester,
        new_email="new@example.com",
        current_password=TESTER_PASSWORD,
        request=_make_request(None),
    )
    alert_msg = next(m for m in mail.outbox if m.to == ["old@example.com"])
    import re

    match = re.search(r"/cancel/(\d+)/([^/\s]+)/", alert_msg.body)
    assert match
    request_id, token = int(match.group(1)), match.group(2)

    result = cancel_email_change(request_id=request_id, token_plaintext=token)
    assert result["status"] == "cancelled"
    tester.refresh_from_db()
    assert tester.email == "old@example.com"
    record = EmailChangeRequest.objects.get(id=request_id)
    assert record.cancelled_at is not None


@pytest.mark.django_db
def test_confirm_rejects_expired_token(tester):
    request_email_change(
        tester,
        new_email="new@example.com",
        current_password=TESTER_PASSWORD,
        request=_make_request(None),
    )
    record = EmailChangeRequest.objects.get(user=tester)
    record.expires_at = timezone.now() - timedelta(seconds=1)
    record.save(update_fields=["expires_at"])
    confirm_msg = next(m for m in mail.outbox if m.to == ["new@example.com"])
    import re

    match = re.search(r"/confirm/(\d+)/([^/\s]+)/", confirm_msg.body)
    request_id, token = int(match.group(1)), match.group(2)

    with pytest.raises(ValueError, match="caduco"):
        confirm_email_change(request_id=request_id, token_plaintext=token)


@pytest.mark.django_db
def test_confirm_rejects_after_cancel(tester):
    request_email_change(
        tester,
        new_email="new@example.com",
        current_password=TESTER_PASSWORD,
        request=_make_request(None),
    )
    confirm_msg = next(m for m in mail.outbox if m.to == ["new@example.com"])
    alert_msg = next(m for m in mail.outbox if m.to == ["old@example.com"])
    import re

    c = re.search(r"/confirm/(\d+)/([^/\s]+)/", confirm_msg.body)
    a = re.search(r"/cancel/(\d+)/([^/\s]+)/", alert_msg.body)
    cancel_email_change(request_id=int(a.group(1)), token_plaintext=a.group(2))
    with pytest.raises(ValueError, match="cancelado"):
        confirm_email_change(request_id=int(c.group(1)), token_plaintext=c.group(2))


@pytest.mark.django_db
def test_confirm_clears_email_mfa_when_enrolled(tester):
    tester.mfa_email_enabled = True
    tester.mfa_enabled = True
    tester.save()
    request_email_change(
        tester,
        new_email="new@example.com",
        current_password=TESTER_PASSWORD,
        request=_make_request(None),
    )
    record = EmailChangeRequest.objects.get(user=tester)
    confirm_msg = next(m for m in mail.outbox if m.to == ["new@example.com"])
    import re

    match = re.search(r"/confirm/(\d+)/([^/\s]+)/", confirm_msg.body)
    confirm_email_change(
        request_id=int(match.group(1)), token_plaintext=match.group(2)
    )
    tester.refresh_from_db()
    assert tester.email == "new@example.com"
    assert tester.mfa_email_enabled is False
    # mfa_enabled should also flip off because TOTP is not enrolled.
    assert tester.mfa_enabled is False


@pytest.mark.django_db
def test_pending_email_change_for_returns_active_record(tester):
    assert pending_email_change_for(tester) is None
    request_email_change(
        tester,
        new_email="new@example.com",
        current_password=TESTER_PASSWORD,
        request=_make_request(None),
    )
    payload = pending_email_change_for(tester)
    assert payload is not None
    assert payload["new_email"] == "new@example.com"
    assert payload["expired"] is False


# ---- HTTP-level pins ----


@pytest.mark.django_db
def test_email_change_endpoint_returns_pending_payload(client, tester):
    client.force_login(tester)
    response = client.post(
        "/profile/email-change/",
        data='{"new_email": "new@example.com", "current_password": "%s"}' % TESTER_PASSWORD,
        content_type="application/json",
    )
    assert response.status_code == 200
    payload = response.json()
    assert payload["ok"] is True
    assert payload["status"] == "pending"
    assert payload["new_email"] == "new@example.com"


@pytest.mark.django_db
def test_email_change_endpoint_rejects_wrong_password(client, tester):
    client.force_login(tester)
    response = client.post(
        "/profile/email-change/",
        data='{"new_email": "new@example.com", "current_password": "wrong"}',
        content_type="application/json",
    )
    assert response.status_code == 400


@pytest.mark.django_db
def test_email_change_cancel_pending_in_app(client, tester):
    request_email_change(
        tester,
        new_email="new@example.com",
        current_password=TESTER_PASSWORD,
        request=_make_request(None),
    )
    client.force_login(tester)
    response = client.post("/profile/email-change/cancel-pending/")
    assert response.status_code == 200
    assert response.json()["status"] == "cancelled"


@pytest.mark.django_db
def test_email_change_confirm_via_get_renders_outcome(client, tester):
    request_email_change(
        tester,
        new_email="new@example.com",
        current_password=TESTER_PASSWORD,
        request=_make_request(None),
    )
    confirm_msg = next(m for m in mail.outbox if m.to == ["new@example.com"])
    import re

    match = re.search(r"/confirm/(\d+)/([^/\s]+)/", confirm_msg.body)
    request_id, token = match.group(1), match.group(2)

    # PHASE_B_SECURITY_REVIEW B5: confirm endpoint is now two-step.
    # GET renders the intersticial; POST applies the change. Mail
    # scanners that prefetch only the GET no longer burn the token.
    response = client.get(f"/profile/email-change/confirm/{request_id}/{token}/")
    assert response.status_code == 200
    assert b"Confirma el cambio de email" in response.content
    # The single-use token must STILL be valid — GET did not consume it.
    response = client.post(f"/profile/email-change/confirm/{request_id}/{token}/")
    assert response.status_code == 200
    assert b"Email actualizado" in response.content
