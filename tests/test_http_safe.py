"""Coverage for ameli_app.http_safe — the hardened outbound HTTP helper.

Upstream finding T-8 (2026-08-04): child-app HTTP clients kept re-deriving
(and getting wrong) the SSRF / scheme / redirect-credential / size guards.
This locks the four properties of the shared helper.
"""
from __future__ import annotations

import email.message
import http.server
import threading
import urllib.error
import urllib.request

import pytest

from ameli_app import http_safe

# ---------------------------------------------------------------------------
# 1. Scheme allowlist
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("url", [
    "file:///etc/passwd",
    "ftp://example.com/x",
    "data:text/plain;base64,aGk=",
    "http://example.com/x",          # http not allowed by default
    "gopher://example.com/",
])
def test_fetch_rejects_disallowed_scheme_before_io(url):
    with pytest.raises(http_safe.UnsafeURLError):
        http_safe.fetch(url, timeout=1)


def test_fetch_rejects_url_without_host():
    with pytest.raises(http_safe.UnsafeURLError):
        http_safe.fetch("https:///nohost", timeout=1)


def test_http_allowed_only_when_opted_in():
    # Default refuses http; explicit allowed_schemes lets it through the
    # scheme gate (the request itself still fails — no server — but with a
    # transport error, not UnsafeURLError).
    with pytest.raises(http_safe.UnsafeURLError):
        http_safe.fetch("http://127.0.0.1:1/x", timeout=0.1)
    with pytest.raises(urllib.error.URLError):
        http_safe.fetch("http://127.0.0.1:1/x", timeout=0.1, allowed_schemes=("http",))


# ---------------------------------------------------------------------------
# 2. Minimal opener — no file/ftp/data/proxy handlers
# ---------------------------------------------------------------------------

def test_opener_has_no_dangerous_handlers():
    opener = http_safe.build_safe_opener(("https",))
    banned = (
        urllib.request.FileHandler,
        urllib.request.FTPHandler,
        urllib.request.DataHandler,
        urllib.request.ProxyHandler,
        urllib.request.UnknownHandler,
    )
    for handler in opener.handlers:
        assert not isinstance(handler, banned), f"dangerous handler: {handler!r}"


def test_opener_has_no_http_handler_unless_allowed():
    https_only = http_safe.build_safe_opener(("https",))
    assert not any(
        type(h) is urllib.request.HTTPHandler for h in https_only.handlers
    )
    with_http = http_safe.build_safe_opener(("http", "https"))
    assert any(type(h) is urllib.request.HTTPHandler for h in with_http.handlers)


# ---------------------------------------------------------------------------
# 3. Safe redirects
# ---------------------------------------------------------------------------

def _redirect(handler, from_url, to_url, headers):
    req = urllib.request.Request(from_url, headers=headers)  # noqa: S310 (test helper)
    return handler.redirect_request(
        req, None, 302, "Found", email.message.Message(), to_url
    )


def test_redirect_to_disallowed_scheme_is_refused():
    handler = http_safe._SafeRedirectHandler(("https",))
    with pytest.raises(http_safe.UnsafeURLError):
        _redirect(handler, "https://a.example/x", "file:///etc/passwd", {})


def test_cross_origin_redirect_drops_credentials():
    handler = http_safe._SafeRedirectHandler(("https",))
    new = _redirect(
        handler, "https://a.example/x", "https://evil.example/y",
        {"Authorization": "Bearer secret", "Cookie": "sid=1", "Accept": "*/*"},
    )
    lowered = {k.lower() for k in new.headers}
    assert "authorization" not in lowered
    assert "cookie" not in lowered
    assert "accept" in lowered  # non-credential headers survive


def test_same_origin_redirect_keeps_credentials():
    handler = http_safe._SafeRedirectHandler(("https",))
    new = _redirect(
        handler, "https://a.example/x", "https://a.example/y",
        {"Authorization": "Bearer secret"},
    )
    assert any(k.lower() == "authorization" for k in new.headers)


# ---------------------------------------------------------------------------
# 4. End-to-end against a local server (happy path + size cap)
# ---------------------------------------------------------------------------

class _Handler(http.server.BaseHTTPRequestHandler):
    def log_message(self, *args):  # silence the test server
        pass

    def do_GET(self):
        if self.path == "/ok":
            body = b"hello world"
        elif self.path == "/big":
            body = b"x" * 5000
        else:
            self.send_error(404)
            return
        self.send_response(200)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)


@pytest.fixture()
def local_server():
    server = http.server.HTTPServer(("127.0.0.1", 0), _Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{server.server_address[1]}"
    finally:
        server.shutdown()
        server.server_close()


def test_fetch_happy_path(local_server):
    resp = http_safe.fetch(f"{local_server}/ok", timeout=5, allowed_schemes=("http",))
    assert resp.status == 200
    assert resp.body == b"hello world"
    assert resp.url.endswith("/ok")


def test_fetch_enforces_size_cap(local_server):
    with pytest.raises(http_safe.ResponseTooLargeError):
        http_safe.fetch(
            f"{local_server}/big", timeout=5, allowed_schemes=("http",), max_bytes=100
        )


def test_fetch_under_cap_returns_full_body(local_server):
    resp = http_safe.fetch(
        f"{local_server}/big", timeout=5, allowed_schemes=("http",), max_bytes=5000
    )
    assert len(resp.body) == 5000
