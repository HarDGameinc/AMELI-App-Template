from __future__ import annotations

from types import SimpleNamespace

from django.test import override_settings

from ameli_web.accounts.services import client_ip


def _request(*, remote_addr: str, forwarded: str | None = None):
    """Build a minimal RequestFactory-style object for the helper."""
    headers = {"X-Forwarded-For": forwarded} if forwarded else {}
    return SimpleNamespace(
        META={"REMOTE_ADDR": remote_addr},
        headers=headers,
    )


# ---- whitelist behaviour ----


def test_untrusted_peer_ignores_forwarded_header():
    """An attacker hitting the app directly cannot spoof their IP."""
    request = _request(remote_addr="8.8.8.8", forwarded="1.2.3.4")

    # ``8.8.8.8`` is not in the default trusted set; the forwarded header is
    # discarded and we return the actual peer address.
    assert client_ip(request) == "8.8.8.8"


def test_default_trusts_loopback_only():
    request = _request(remote_addr="127.0.0.1", forwarded="9.9.9.9")
    assert client_ip(request) == "9.9.9.9"

    request_v6 = _request(remote_addr="::1", forwarded="9.9.9.9")
    assert client_ip(request_v6) == "9.9.9.9"


@override_settings(TRUSTED_PROXIES=["10.0.0.5"])
def test_settings_override_extends_trusted_set():
    request = _request(remote_addr="10.0.0.5", forwarded="9.9.9.9")
    assert client_ip(request) == "9.9.9.9"


@override_settings(TRUSTED_PROXIES=[])
def test_empty_trusted_proxies_disables_forwarded_entirely():
    request = _request(remote_addr="127.0.0.1", forwarded="9.9.9.9")
    assert client_ip(request) == "127.0.0.1"


def test_no_forwarded_header_returns_remote_addr():
    request = _request(remote_addr="127.0.0.1")
    assert client_ip(request) == "127.0.0.1"


def test_forwarded_chain_uses_leftmost_ip():
    request = _request(remote_addr="127.0.0.1", forwarded="1.2.3.4, 10.0.0.5")
    assert client_ip(request) == "1.2.3.4"
