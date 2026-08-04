"""Hardened outbound HTTP for AMELI apps — SSRF / scheme / redirect / size guards.

Reference implementation for child-app outbound clients (fleet, checklist,
the next one): use :func:`fetch` instead of a raw
``urllib.request.urlopen`` whenever the target host is operator- or
data-configurable. It closes, in one place, the four traps a hand-rolled
client repeatedly gets wrong (upstream finding T-8, 2026-08-04):

1. **Scheme allowlist** — ``https`` only by default. A ``file://`` /
   ``ftp://`` / ``data:`` URL (SSRF or local-file read) is refused before
   any I/O.
2. **Minimal opener** — no ``FileHandler`` / ``FTPHandler`` /
   ``DataHandler`` / ``ProxyHandler`` / ``UnknownHandler``, so a redirect
   cannot smuggle one of those schemes in either.
3. **Safe redirects** — a redirect to a disallowed scheme is refused, and a
   redirect that changes origin drops credential headers
   (``Authorization`` / ``Cookie``) so a malicious or compromised host
   cannot harvest a Bearer token by 30x-ing the caller elsewhere.
4. **Response size cap** — reads at most ``max_bytes``, so a hostile or
   runaway endpoint cannot exhaust memory.

Stdlib only (no ``requests``) to keep the template dependency-free. The
template's own outbound calls go to fixed / operator-controlled URLs
(HIBP, the GitHub release check) and stay as they are; this module is for
NEW clients whose destination a fork or its operator configures.
"""
from __future__ import annotations

import urllib.error
import urllib.request
from dataclasses import dataclass
from urllib.parse import urlsplit

_DEFAULT_MAX_BYTES = 10 * 1024 * 1024  # 10 MiB
# Lower-cased header names dropped when a redirect changes origin.
_CREDENTIAL_HEADERS = frozenset({"authorization", "cookie", "proxy-authorization"})


class UnsafeURLError(ValueError):
    """The URL, or a redirect target, is not allowed by the safety policy."""


class ResponseTooLargeError(Exception):
    """The response body exceeded the configured ``max_bytes``."""


@dataclass
class SafeResponse:
    """The result of a successful :func:`fetch`."""

    status: int
    url: str  # final URL after any redirects
    headers: dict[str, str]
    body: bytes


def _origin(url: str) -> tuple[str, str, int | None]:
    parsed = urlsplit(url)
    return (parsed.scheme.lower(), (parsed.hostname or "").lower(), parsed.port)


def _check_scheme(url: str, allowed: tuple[str, ...]) -> None:
    parsed = urlsplit(url)
    if parsed.scheme.lower() not in allowed:
        raise UnsafeURLError(
            f"scheme {parsed.scheme!r} not allowed for {url!r} "
            f"(allowed: {', '.join(allowed) or '<none>'})"
        )
    if not parsed.hostname:
        raise UnsafeURLError(f"missing host in {url!r}")


class _SafeRedirectHandler(urllib.request.HTTPRedirectHandler):
    """Refuse disallowed-scheme redirects; strip credentials cross-origin."""

    def __init__(self, allowed_schemes: tuple[str, ...]) -> None:
        self._allowed = allowed_schemes

    def redirect_request(self, req, fp, code, msg, headers, newurl):  # noqa: ANN001, ANN201
        _check_scheme(newurl, self._allowed)  # raises UnsafeURLError
        new = super().redirect_request(req, fp, code, msg, headers, newurl)
        if new is None:
            return None
        if _origin(req.full_url) != _origin(newurl):
            for key in [k for k in new.headers if k.lower() in _CREDENTIAL_HEADERS]:
                del new.headers[key]
            unredirected = getattr(new, "unredirected_hdrs", {})
            for key in [k for k in unredirected if k.lower() in _CREDENTIAL_HEADERS]:
                del unredirected[key]
        return new


def build_safe_opener(allowed_schemes: tuple[str, ...]) -> urllib.request.OpenerDirector:
    """An ``OpenerDirector`` with only the HTTP(S) handlers plus the safe
    redirect handler — no file/ftp/data/proxy/unknown handlers. Exposed for
    advanced callers; most should use :func:`fetch`.
    """
    opener = urllib.request.OpenerDirector()
    opener.add_handler(urllib.request.HTTPSHandler())
    if "http" in allowed_schemes:
        opener.add_handler(urllib.request.HTTPHandler())
    opener.add_handler(urllib.request.HTTPDefaultErrorHandler())
    opener.add_handler(urllib.request.HTTPErrorProcessor())
    opener.add_handler(_SafeRedirectHandler(allowed_schemes))
    return opener


def fetch(
    url: str,
    *,
    timeout: float,
    headers: dict[str, str] | None = None,
    data: bytes | None = None,
    method: str | None = None,
    max_bytes: int = _DEFAULT_MAX_BYTES,
    allowed_schemes: tuple[str, ...] = ("https",),
) -> SafeResponse:
    """Fetch ``url`` with the four guards described in the module docstring.

    ``timeout`` is required — an outbound call without one can hang forever.
    Raises :class:`UnsafeURLError` (bad scheme / redirect),
    :class:`ResponseTooLargeError` (over ``max_bytes``), or the usual
    ``urllib.error.URLError`` / ``HTTPError`` for transport/HTTP failures.
    """
    allowed = tuple(scheme.lower() for scheme in allowed_schemes)
    _check_scheme(url, allowed)
    # Scheme is allow-listed above and the opener carries no file/ftp/data
    # handler, so this is not the unrestricted urlopen S310/B310 warns about.
    request = urllib.request.Request(  # noqa: S310  # nosec B310
        url, data=data, headers=headers or {}, method=method
    )
    opener = build_safe_opener(allowed)
    with opener.open(request, timeout=timeout) as resp:
        # Read one extra byte to detect (and reject) an over-cap body without
        # first buffering the whole thing.
        body = resp.read(max_bytes + 1)
        if len(body) > max_bytes:
            raise ResponseTooLargeError(
                f"response from {resp.url!r} exceeded max_bytes={max_bytes}"
            )
        return SafeResponse(
            status=getattr(resp, "status", None) or resp.getcode(),
            url=resp.url,
            headers={key: value for key, value in resp.headers.items()},
            body=body,
        )
