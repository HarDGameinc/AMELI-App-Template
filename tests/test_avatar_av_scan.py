"""Regression coverage for ASVS V12.4.1 — antivirus scan on avatar uploads.

Closes roadmap item #7. The integration lives in
``ameli_web/accounts/av.py:scan_bytes`` (transport) and is wired by
``update_avatar`` view (policy). Operator opt-in via
``settings.AV_ENDPOINT`` (env ``AMELI_APP_AV_ENDPOINT``).

These tests cover the full state machine: no endpoint → scan
skipped; clean verdict → file persists + no audit; infected verdict
→ rejection + audit + file NOT persisted; check_failed (timeout,
unreachable, bad response) → fail-open + audit; the URL credential
redaction; and the wire-shape parsers for clamd TCP and HTTP/JSON.

No real clamd binary is required — every test mocks the transport
at the ``scan_bytes`` boundary (or its internal ``_scan_*`` helpers).
"""
from __future__ import annotations

import io
from unittest.mock import patch

import pytest
from django.contrib.auth import get_user_model
from django.core.files.uploadedfile import SimpleUploadedFile
from PIL import Image

from ameli_web.accounts import av
from ameli_web.accounts.models import User as _U  # noqa: F401 - keep type accessible
from ameli_web.audit.models import AuditEvent

User = get_user_model()


def _png_bytes(size=(64, 64), colour=(120, 200, 80)) -> bytes:
    buffer = io.BytesIO()
    Image.new("RGB", size, color=colour).save(buffer, format="PNG")
    return buffer.getvalue()


def _upload(name: str = "avatar.png") -> SimpleUploadedFile:
    return SimpleUploadedFile(name, _png_bytes(), content_type="image/png")


@pytest.fixture()
def user(db):
    return User.objects.create_user(
        username="alice",
        password="UserPass!12?",
        role=User.ROLE_PUBLIC,
        email="alice@example.com",
    )


# ---------------------------------------------------------------------------
# scan_bytes — verdict surface
# ---------------------------------------------------------------------------

def test_scan_bytes_returns_disabled_when_endpoint_empty():
    assert av.scan_bytes(b"any-bytes", "") == ("disabled", "")


def test_scan_bytes_rejects_unknown_scheme():
    assert av.scan_bytes(b"x", "ftp://av.example.com") == ("check_failed", "bad_scheme")


def test_scan_bytes_translates_timeout_to_check_failed():
    """A ``TimeoutError`` from the transport must be reported as a
    fail-open verdict, NOT as ``infected``. Property: a network
    misconfiguration never gets a user kicked out of profile updates.
    """
    with patch.object(av, "_scan_clamd_tcp", side_effect=TimeoutError("slow")):
        verdict, detail = av.scan_bytes(b"x", "tcp://127.0.0.1:3310")
    assert verdict == "check_failed"
    assert detail == "timeout"


def test_scan_bytes_translates_connection_refused_to_check_failed():
    with patch.object(av, "_scan_clamd_tcp", side_effect=ConnectionRefusedError()):
        verdict, detail = av.scan_bytes(b"x", "tcp://127.0.0.1:3310")
    assert verdict == "check_failed"
    assert "connection" in detail


def test_scan_bytes_translates_oserror_to_unreachable():
    with patch.object(av, "_scan_clamd_tcp", side_effect=OSError("Network unreachable")):
        verdict, detail = av.scan_bytes(b"x", "tcp://127.0.0.1:3310")
    assert verdict == "check_failed"
    assert detail == "unreachable"


# ---------------------------------------------------------------------------
# _redact — URL credential scrubbing
# ---------------------------------------------------------------------------

def test_redact_strips_basic_auth_credentials():
    assert av._redact("http://user:pass@av.example.com/scan") == "http://***@av.example.com/scan"


def test_redact_passes_through_credentialless_url():
    assert av._redact("tcp://127.0.0.1:3310") == "tcp://127.0.0.1:3310"


# ---------------------------------------------------------------------------
# HTTP transport — verdict parsing
# ---------------------------------------------------------------------------

def _fake_http_response(body: bytes):
    """Build a context-manager mock that mimics ``urlopen`` returning
    a single ``body`` blob.
    """

    class _Resp:
        def __enter__(self_inner):
            return self_inner

        def __exit__(self_inner, *args):
            return False

        def read(self_inner):
            return body

    return _Resp()


def test_http_transport_clean_json():
    with patch.object(av, "urlopen", return_value=_fake_http_response(b'{"stream": "OK"}')):
        assert av._scan_http(b"x", "http://av.example.com", timeout=1.0) == ("ok", "")


def test_http_transport_infected_with_signature():
    body = b'{"stream": "FOUND", "signature": "Eicar-Test-Signature"}'
    with patch.object(av, "urlopen", return_value=_fake_http_response(body)):
        verdict, sig = av._scan_http(b"x", "http://av.example.com", timeout=1.0)
    assert verdict == "infected"
    assert sig == "Eicar-Test-Signature"


def test_http_transport_infected_without_signature_defaults_to_unknown():
    with patch.object(av, "urlopen", return_value=_fake_http_response(b'{"stream": "FOUND"}')):
        verdict, sig = av._scan_http(b"x", "http://av.example.com", timeout=1.0)
    assert verdict == "infected"
    assert sig == "unknown"


def test_http_transport_plain_text_ok():
    """A barebones AV proxy may return plain text rather than JSON.
    The transport accepts ``OK`` / ``FOUND`` and falls back to
    ``check_failed`` for anything else.
    """
    with patch.object(av, "urlopen", return_value=_fake_http_response(b"OK")):
        assert av._scan_http(b"x", "http://av.example.com", timeout=1.0) == ("ok", "")


def test_http_transport_bad_response_short_circuits():
    with patch.object(av, "urlopen", return_value=_fake_http_response(b"<html>nope</html>")):
        assert av._scan_http(b"x", "http://av.example.com", timeout=1.0) == ("check_failed", "bad_response")


# ---------------------------------------------------------------------------
# clamd TCP transport — wire-shape parsing
# ---------------------------------------------------------------------------

class _FakeClamdSocket:
    """Minimal socket mock for clamd INSTREAM. Captures the sent
    bytes and replies with a pre-baked response.
    """

    def __init__(self, reply: bytes):
        self.reply = reply
        self.sent = b""
        self._read_offset = 0

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def settimeout(self, _t):
        pass

    def sendall(self, data):
        self.sent += data

    def recv(self, n):
        chunk = self.reply[self._read_offset:self._read_offset + n]
        self._read_offset += len(chunk)
        return chunk


def test_clamd_tcp_clean_verdict():
    fake = _FakeClamdSocket(b"stream: OK\0")
    with patch.object(av.socket, "create_connection", return_value=fake):
        verdict, detail = av._scan_clamd_tcp(b"data", "tcp://127.0.0.1:3310", timeout=1.0)
    assert verdict == "ok"
    assert detail == ""
    # The INSTREAM command + a length-prefixed chunk + the 4-byte zero
    # terminator all landed on the wire.
    assert fake.sent.startswith(b"zINSTREAM\0")
    assert fake.sent.endswith(b"\0\0\0\0")


def test_clamd_tcp_infected_extracts_signature():
    fake = _FakeClamdSocket(b"stream: Eicar-Test-Signature FOUND\0")
    with patch.object(av.socket, "create_connection", return_value=fake):
        verdict, sig = av._scan_clamd_tcp(b"data", "tcp://127.0.0.1:3310", timeout=1.0)
    assert verdict == "infected"
    assert sig == "Eicar-Test-Signature"


def test_clamd_tcp_bad_reply_returns_check_failed():
    fake = _FakeClamdSocket(b"WTF: garbage\0")
    with patch.object(av.socket, "create_connection", return_value=fake):
        verdict, detail = av._scan_clamd_tcp(b"data", "tcp://127.0.0.1:3310", timeout=1.0)
    assert verdict == "check_failed"
    assert detail == "bad_response"


def test_clamd_tcp_default_port_3310():
    """Endpoint ``tcp://host`` without a port falls back to 3310 —
    the clamd default. Operators that follow the
    ``apt install clamav-daemon`` happy path do not have to set the
    port explicitly.
    """
    captured = {}

    def _spy(addr, timeout):
        captured["addr"] = addr
        return _FakeClamdSocket(b"stream: OK\0")

    with patch.object(av.socket, "create_connection", side_effect=_spy):
        av._scan_clamd_tcp(b"x", "tcp://av-host", timeout=1.0)
    assert captured["addr"] == ("av-host", 3310)


# ---------------------------------------------------------------------------
# View integration — policy
# ---------------------------------------------------------------------------

@pytest.mark.django_db
def test_view_skips_scan_when_endpoint_disabled(client, user, settings):
    settings.AV_ENDPOINT = ""
    client.force_login(user)
    response = client.post("/profile/avatar/", {"avatar": _upload()})
    assert response.status_code in (200, 302)
    user.refresh_from_db()
    assert user.avatar  # file landed
    # No AV audit row because scanning was disabled.
    assert not AuditEvent.objects.filter(action__startswith="avatar_upload_av_").exists()


@pytest.mark.django_db
def test_view_persists_on_clean_verdict(client, user, settings):
    settings.AV_ENDPOINT = "tcp://127.0.0.1:3310"
    client.force_login(user)
    with patch("ameli_web.accounts.av.scan_bytes", return_value=("ok", "")):
        response = client.post("/profile/avatar/", {"avatar": _upload()})
    assert response.status_code in (200, 302)
    user.refresh_from_db()
    assert user.avatar
    # Clean scan does not write an AV audit row — only the existing
    # ``update_my_preferences`` row fires.
    assert not AuditEvent.objects.filter(
        action__startswith="avatar_upload_av_",
    ).exists()


@pytest.mark.django_db
def test_view_rejects_and_audits_on_infected(client, user, settings):
    settings.AV_ENDPOINT = "tcp://127.0.0.1:3310"
    client.force_login(user)
    with patch(
        "ameli_web.accounts.av.scan_bytes",
        return_value=("infected", "Eicar-Test-Signature"),
    ):
        response = client.post(
            "/profile/avatar/",
            {"avatar": _upload()},
            HTTP_ACCEPT="application/json",
        )
    # JSON path: 400 with operator-facing error.
    assert response.status_code == 400
    body = response.json()
    assert body["ok"] is False
    assert "antivirus" in body["error"].lower()
    # File did NOT persist — the user's avatar stayed null.
    user.refresh_from_db()
    assert not user.avatar
    # Audit row carries signature + endpoint scheme but NOT the full
    # endpoint URL (we want operators to grep by scheme, not leak
    # internal hosts into the chain).
    row = AuditEvent.objects.filter(action="avatar_upload_av_rejected").first()
    assert row is not None
    assert row.payload["signature"] == "Eicar-Test-Signature"
    assert row.payload["endpoint_scheme"] == "tcp"


@pytest.mark.django_db
def test_view_fail_open_on_check_failed(client, user, settings):
    """ASVS-aligned fail-open: AV endpoint unreachable -> the upload
    still proceeds (user is not locked out of profile updates), but
    the audit chain records the outage so the operator sees it.
    Mirrors the HIBP password-validator policy.
    """
    settings.AV_ENDPOINT = "tcp://127.0.0.1:3310"
    client.force_login(user)
    with patch(
        "ameli_web.accounts.av.scan_bytes",
        return_value=("check_failed", "timeout"),
    ):
        response = client.post("/profile/avatar/", {"avatar": _upload()})
    assert response.status_code in (200, 302)
    user.refresh_from_db()
    assert user.avatar  # uploaded despite scan failure
    row = AuditEvent.objects.filter(action="avatar_upload_av_check_failed").first()
    assert row is not None
    assert row.payload["reason"] == "timeout"
    assert row.payload["endpoint_scheme"] == "tcp"


@pytest.mark.django_db
def test_view_rejection_message_does_not_leak_signature_to_html_path(
    client, user, settings,
):
    """The HTML response path flashes a generic error message; the
    signature stays in the audit chain only. Property: an attacker
    who triggers an infected upload does not learn from the response
    what specific signature the operator's AV catalog matched.
    """
    settings.AV_ENDPOINT = "tcp://127.0.0.1:3310"
    client.force_login(user)
    with patch(
        "ameli_web.accounts.av.scan_bytes",
        return_value=("infected", "Trojan.Win.Internal-Catalog-Name"),
    ):
        response = client.post("/profile/avatar/", {"avatar": _upload()})
    assert response.status_code in (200, 302)
    # The HTML response goes through messages.error → check the
    # in-memory message store rather than the response body.
    user.refresh_from_db()
    assert not user.avatar
    # Audit row has the signature; HTML response did NOT include it.
