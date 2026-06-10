"""Block 3 hardening coverage (operational allowlist, CDN SRI, HIBP
optional check, atomic throttle, CSP nonces, audit HMAC).

Items land item by item; the file grows alongside each commit. Each
test pins one observable guarantee from the audit findings.
"""

from __future__ import annotations

import pytest


# ---------------------------------------------------------------------------
# H12 — /health, /api/health, /metrics behind an optional IP allowlist
# ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_health_endpoints_public_without_allowlist(client, settings):
    settings.HEALTH_METRICS_ALLOWLIST = set()
    assert client.get("/health").status_code == 200
    assert client.get("/api/health").status_code == 200
    assert client.get("/metrics").status_code == 200


@pytest.mark.django_db
def test_health_endpoints_refuse_clients_outside_allowlist(client, settings):
    settings.HEALTH_METRICS_ALLOWLIST = {"10.0.0.42"}
    # Django test client emits REMOTE_ADDR=127.0.0.1 by default.
    for path in ("/health", "/api/health", "/metrics"):
        response = client.get(path)
        assert response.status_code == 403, path


@pytest.mark.django_db
def test_health_endpoints_let_allowlisted_clients_through(client, settings):
    settings.HEALTH_METRICS_ALLOWLIST = {"127.0.0.1"}
    for path in ("/health", "/api/health", "/metrics"):
        response = client.get(path)
        assert response.status_code == 200, path


@pytest.mark.django_db
def test_health_allowlist_honours_trusted_proxy_forwarded_ip(client, settings):
    """When the deploy sits behind a reverse proxy that adds
    X-Forwarded-For, ``client_ip`` resolves the original client. The
    allowlist must match against THAT address, not the proxy's loopback."""
    settings.HEALTH_METRICS_ALLOWLIST = {"203.0.113.5"}
    settings.TRUSTED_PROXIES = {"127.0.0.1"}

    blocked = client.get("/health")
    assert blocked.status_code == 403

    allowed = client.get("/health", HTTP_X_FORWARDED_FOR="203.0.113.5")
    assert allowed.status_code == 200


# ---------------------------------------------------------------------------
# H10 — CDN bundles pinned to an exact version and SRI-aware
# ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_swagger_html_pins_exact_version(client):
    """An unversioned ``@5`` URL silently picks up any future release on
    the CDN. Pin a concrete tag so a compromise window cannot include
    the docs page in the blast radius."""
    response = client.get("/docs")
    body = response.content.decode("utf-8")
    assert "swagger-ui-dist@5.20.0" in body
    assert "swagger-ui-dist@5/" not in body  # the floating tag is gone


@pytest.mark.django_db
def test_redoc_html_pins_exact_version(client):
    response = client.get("/redoc")
    body = response.content.decode("utf-8")
    assert "redoc@2.1.5/" in body
    assert "redoc@next/" not in body


@pytest.mark.django_db
def test_swagger_html_renders_integrity_when_configured(client, settings):
    settings.CDN_SRI_HASHES = {
        "swagger_ui_css": "sha384-test-css-hash",
        "swagger_ui_bundle": "sha384-test-bundle-hash",
        "swagger_ui_preset": "sha384-test-preset-hash",
        "redoc_bundle": "",
    }
    body = client.get("/docs").content.decode("utf-8")
    assert 'integrity="sha384-test-css-hash"' in body
    assert 'integrity="sha384-test-bundle-hash"' in body
    assert 'integrity="sha384-test-preset-hash"' in body
    assert body.count('crossorigin="anonymous"') >= 3


@pytest.mark.django_db
def test_swagger_html_omits_integrity_when_unconfigured(client, settings):
    settings.CDN_SRI_HASHES = {}
    body = client.get("/docs").content.decode("utf-8")
    assert "integrity=" not in body


@pytest.mark.django_db
def test_docs_response_relaxes_csp_to_allow_jsdelivr(client):
    """Without a per-page CSP override, the strict project-wide policy
    (script-src 'self') blocks Swagger UI / ReDoc bundles before they
    even reach the SRI check. /docs and /redoc need jsdelivr.net
    whitelisted just for themselves."""
    docs = client.get("/docs")
    assert "cdn.jsdelivr.net" in docs["Content-Security-Policy"]
    assert "script-src" in docs["Content-Security-Policy"]

    redoc = client.get("/redoc")
    assert "cdn.jsdelivr.net" in redoc["Content-Security-Policy"]


@pytest.mark.django_db
def test_strict_csp_still_applies_to_other_pages(client):
    """The CDN whitelist must NOT leak to unrelated pages. A response from
    the dashboard home should keep the project default that does not
    mention jsdelivr."""
    home = client.get("/")
    csp = home.get("Content-Security-Policy", "")
    assert "cdn.jsdelivr.net" not in csp


@pytest.mark.django_db
def test_swagger_html_auto_prefixes_sha384_for_raw_base64(client, settings):
    """Operators normally paste the raw output of ``openssl dgst -sha384
    -binary | openssl base64 -A`` into the env file. Without the
    ``sha384-`` algorithm prefix the browser rejects the integrity
    attribute and downloads the bundle ungated — silently defeating
    the whole protection. Auto-prefix when missing, pass through
    already-prefixed values untouched."""
    settings.CDN_SRI_HASHES = {
        "swagger_ui_css": "19U5QfIgtj822TyFqWtYKqauOZosmdEalgX8htxti5Pkm6oyuyR9ePwNbSaBclKA",
        "swagger_ui_bundle": "sha512-already-prefixed",
        "swagger_ui_preset": "",
        "redoc_bundle": "",
    }
    body = client.get("/docs").content.decode("utf-8")
    assert 'integrity="sha384-19U5QfIgtj822TyFqWtYKqauOZosmdEalgX8htxti5Pkm6oyuyR9ePwNbSaBclKA"' in body
    assert 'integrity="sha512-already-prefixed"' in body


# ---------------------------------------------------------------------------
# H7 — HIBP k-anonymity password check (opt-in)
# ---------------------------------------------------------------------------


@pytest.fixture()
def hibp_validator(monkeypatch, settings):
    """A configured HIBPPasswordValidator with the network mocked out."""
    from ameli_web.accounts import validators

    settings.HIBP_PASSWORD_CHECK = True
    return validators


def _sha1(text: str) -> str:
    import hashlib

    return hashlib.sha1(text.encode("utf-8")).hexdigest().upper()


def test_hibp_validator_passes_when_disabled(settings):
    """When the toggle is off (the default) the validator never makes a
    network call and never raises, regardless of how leaked the password
    is. The plain policy validator still does the heavy lifting."""
    from ameli_web.accounts.validators import HIBPPasswordValidator

    settings.HIBP_PASSWORD_CHECK = False
    HIBPPasswordValidator().validate("Password!2026")


def test_hibp_validator_rejects_known_leaked_password(hibp_validator, monkeypatch):
    """When the HIBP response includes our suffix with a non-zero count,
    refuse the password with a user-facing message."""
    from django.core.exceptions import ValidationError

    digest = _sha1("Password!2026")
    prefix, suffix = digest[:5], digest[5:]

    def fake_query(p, **kwargs):
        assert p == prefix  # only the prefix is sent, never the full hash
        return f"{suffix}:42\nFFFFFF:1\n"

    monkeypatch.setattr(hibp_validator, "_query_hibp", fake_query)
    with pytest.raises(ValidationError, match="HIBP"):
        hibp_validator.HIBPPasswordValidator().validate("Password!2026")


def test_hibp_validator_accepts_unseen_password(hibp_validator, monkeypatch):
    """A password whose suffix is not in the HIBP response passes."""
    def fake_query(p, **kwargs):
        return "AAAAAAAAAAAA:1\nBBBBBBBBBBBB:5\n"

    monkeypatch.setattr(hibp_validator, "_query_hibp", fake_query)
    hibp_validator.HIBPPasswordValidator().validate("SomeFreshPass!12?")


def test_hibp_validator_fails_open_on_network_error(hibp_validator, monkeypatch):
    """If HIBP is unreachable we LOG and let the password through.
    Failing closed would make password changes impossible the moment
    the upstream blips, which is a worse trade-off than the modest
    increase in attack surface."""
    from urllib.error import URLError

    def fake_query(p, **kwargs):
        raise URLError("dns failure")

    monkeypatch.setattr(hibp_validator, "_query_hibp", fake_query)
    hibp_validator.HIBPPasswordValidator().validate("AnyValidPass!12?")


# ---------------------------------------------------------------------------
# #4 — Atomic throttle counters replace the AuditEvent COUNT(*) TOCTOU
# ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_throttle_counter_bump_is_atomic_and_serialised(admin_user):
    """The bump helper increments via select_for_update + F('count')+1,
    so even repeated calls produce a strictly monotonic count."""
    from ameli_web.accounts.services import _bump_throttle_counter

    counts = [
        _bump_throttle_counter(scope="t-test", key="10.0.0.1", window_seconds=60)
        for _ in range(5)
    ]
    assert counts == [1, 2, 3, 4, 5]


@pytest.mark.django_db
def test_throttle_counter_window_snaps_to_buckets(admin_user):
    """Bumps inside the same window share one row; the next window owns
    its own row so old counts do not leak across the boundary."""
    from datetime import timedelta
    from django.utils import timezone

    from ameli_web.accounts.models import ThrottleCounter
    from ameli_web.accounts.services import _bump_throttle_counter

    _bump_throttle_counter(scope="t-bucket", key="k", window_seconds=60)
    _bump_throttle_counter(scope="t-bucket", key="k", window_seconds=60)

    # Drop a historical row to simulate an older bucket; the helper must
    # NOT touch it.
    ThrottleCounter.objects.create(
        scope="t-bucket",
        key="k",
        window_start=timezone.now() - timedelta(hours=3),
        count=999,
    )

    rows = list(ThrottleCounter.objects.filter(scope="t-bucket", key="k").order_by("window_start"))
    assert len(rows) == 2
    assert rows[0].count == 999  # untouched legacy row
    assert rows[1].count == 2    # the current-bucket row


@pytest.mark.django_db
def test_throttle_counter_separates_scopes_and_keys(admin_user):
    """The bump key includes scope and identity so an IP-level burst
    does not consume a per-user budget for an unrelated account."""
    from ameli_web.accounts.services import _bump_throttle_counter, _read_throttle_counter

    _bump_throttle_counter(scope="login_fail_ip", key="10.0.0.1", window_seconds=60)
    _bump_throttle_counter(scope="login_fail_user", key="alice", window_seconds=60)

    assert _read_throttle_counter(scope="login_fail_ip", key="10.0.0.1", window_seconds=60) == 1
    assert _read_throttle_counter(scope="login_fail_user", key="alice", window_seconds=60) == 1
    assert _read_throttle_counter(scope="login_fail_ip", key="10.0.0.2", window_seconds=60) == 0
    assert _read_throttle_counter(scope="login_fail_user", key="bob", window_seconds=60) == 0


@pytest.mark.django_db
def test_forgot_password_throttle_uses_atomic_counter(admin_user, settings):
    """Each call to the gate bumps the counter once; the (N+1)-th call
    crosses the threshold and raises, even if the audit log is empty."""
    from ameli_web.accounts.services import LoginThrottled, check_forgot_password_throttle

    settings.FORGOT_PASSWORD_IP_MAX = 3
    settings.FORGOT_PASSWORD_IP_WINDOW = 600

    for _ in range(3):
        check_forgot_password_throttle(ip="198.51.100.7")
    with pytest.raises(LoginThrottled):
        check_forgot_password_throttle(ip="198.51.100.7")


@pytest.mark.django_db
def test_mfa_resend_throttle_uses_atomic_counter(admin_user, settings):
    from ameli_web.accounts.services import LoginThrottled, check_mfa_resend_throttle

    settings.MFA_RESEND_IP_MAX = 2
    settings.MFA_RESEND_IP_WINDOW = 300

    for _ in range(2):
        check_mfa_resend_throttle(ip="198.51.100.8")
    with pytest.raises(LoginThrottled):
        check_mfa_resend_throttle(ip="198.51.100.8")


@pytest.fixture()
def admin_user(db):
    from django.contrib.auth import get_user_model

    from ameli_web.accounts.services import bootstrap_superadmin

    bootstrap_superadmin(username="admin", password="AdminPass!12?Secure")
    return get_user_model().objects.get(username="admin")


def test_hibp_validator_only_sends_prefix(hibp_validator, monkeypatch):
    """k-anonymity guarantee: the validator must only send the first
    five chars of the hash to HIBP, never the rest of the digest and
    never the plaintext."""
    captured = {}

    def fake_query(p, **kwargs):
        captured["prefix"] = p
        return ""

    monkeypatch.setattr(hibp_validator, "_query_hibp", fake_query)
    plaintext = "TestPrivacy!12?"
    hibp_validator.HIBPPasswordValidator().validate(plaintext)
    digest = _sha1(plaintext)
    assert captured["prefix"] == digest[:5]
    assert len(captured["prefix"]) == 5
