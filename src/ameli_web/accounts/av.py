"""Antivirus scanning for user uploads (ASVS V12.4.1).

The template ships an optional integration that the operator enables
by setting ``AMELI_APP_AV_ENDPOINT``. Two transports are supported:

* ``tcp://host:port`` — clamd's INSTREAM protocol over a raw TCP
  socket. The classic deployment shape: ``apt install clamav-daemon``
  on the same host, then ``AMELI_APP_AV_ENDPOINT=tcp://127.0.0.1:3310``.
* ``http://...`` / ``https://...`` — an HTTP endpoint that accepts a
  POST of the raw bytes and returns JSON ``{"stream": "OK"|"FOUND",
  "signature": "<name>"?}``. Suited for a sidecar (e.g. clamav-rest)
  or a managed AV service.

When the endpoint is unset, ``scan_bytes`` returns ``("disabled", "")``
and the caller skips the gate. When the endpoint is set but
unreachable / times out / errors, ``scan_bytes`` returns
``("check_failed", "<reason>")`` and the caller follows the project's
fail-open-with-audit policy (mirrors how the HIBP password validator
handles outages: the user action proceeds, the operator sees the
failure in the audit chain). Genuine ``("infected", "<signature>")``
results MUST block the upload at the call site.

stdlib-only on purpose: the template's HTTP-client policy
(``validators.py:33``) is "no requests / no httpx" so we use
``socket`` for clamd TCP and ``urllib`` for HTTP.
"""
from __future__ import annotations

import json
import logging
import socket
import struct
from urllib.error import URLError
from urllib.request import Request, urlopen

logger = logging.getLogger(__name__)

# clamd INSTREAM chunks. The protocol limits the per-chunk size to
# 25 MB by default; our avatar cap is 3 MB so a single chunk is fine.
# We still split into 64 KiB chunks so the same module works for a
# future file class beyond avatars without a rewrite.
_CHUNK_SIZE = 64 * 1024

# Verdict shape: ``(status, detail)``. Status is one of:
# * "ok"              — clean file, allow upload
# * "infected"        — virus detected; caller MUST reject
# * "check_failed"    — endpoint configured but unreachable / errored
# * "disabled"        — no endpoint configured; scanning is off
# Detail carries the signature on "infected" (e.g. "Eicar-Test-Signature")
# or a one-token failure reason on "check_failed" (e.g. "timeout",
# "connection_refused", "bad_response").


def scan_bytes(data: bytes, endpoint: str, *, timeout: float = 5.0) -> tuple[str, str]:
    """Scan ``data`` against the configured AV endpoint.

    Empty ``endpoint`` short-circuits to ``("disabled", "")`` so the
    caller can do ``if status == "disabled": skip`` without having to
    re-check the setting.

    Any exception from the underlying transport (network unreachable,
    timeout, malformed response, etc.) is caught and reported as
    ``("check_failed", "<reason>")`` — the call site logs an audit row
    and proceeds with the upload (fail-open policy).
    """
    if not endpoint:
        return ("disabled", "")
    try:
        if endpoint.startswith("tcp://"):
            return _scan_clamd_tcp(data, endpoint, timeout=timeout)
        if endpoint.startswith(("http://", "https://")):
            return _scan_http(data, endpoint, timeout=timeout)
        logger.warning("AV endpoint scheme not recognised: %r", endpoint)
        return ("check_failed", "bad_scheme")
    except TimeoutError:
        logger.warning("AV scan timed out against %s", _redact(endpoint))
        return ("check_failed", "timeout")
    except (ConnectionRefusedError, ConnectionResetError, BrokenPipeError) as exc:
        logger.warning("AV scan transport failure against %s: %s",
                       _redact(endpoint), type(exc).__name__)
        return ("check_failed", type(exc).__name__.lower())
    except (URLError, OSError) as exc:
        logger.warning("AV scan unreachable against %s: %s",
                       _redact(endpoint), exc)
        return ("check_failed", "unreachable")
    except Exception as exc:  # noqa: BLE001 — any other transport error is fail-open
        logger.warning("AV scan unexpected failure against %s: %s",
                       _redact(endpoint), type(exc).__name__)
        return ("check_failed", "unexpected")


def _redact(endpoint: str) -> str:
    """Replace user-info in a URL before it lands in logs. clamd over
    TCP does not carry credentials, but an HTTP endpoint might.
    """
    if "@" in endpoint:
        scheme, _, rest = endpoint.partition("://")
        _, _, host = rest.rpartition("@")
        return f"{scheme}://***@{host}"
    return endpoint


def _scan_clamd_tcp(data: bytes, endpoint: str, *, timeout: float) -> tuple[str, str]:
    """Scan via clamd's INSTREAM TCP protocol.

    Wire shape:
        ``zINSTREAM\\0`` <chunk_1_len:4be> <chunk_1_bytes> ...
        <chunk_n_len:4be> <chunk_n_bytes> <0:4be>
    Server reply:
        ``stream: OK\\0``                — clean
        ``stream: <signature> FOUND\\0`` — infected
    """
    _, _, hostport = endpoint.partition("://")
    host, _, port_str = hostport.partition(":")
    port = int(port_str) if port_str else 3310
    with socket.create_connection((host, port), timeout=timeout) as sock:
        sock.settimeout(timeout)
        sock.sendall(b"zINSTREAM\0")
        for offset in range(0, len(data), _CHUNK_SIZE):
            chunk = data[offset:offset + _CHUNK_SIZE]
            sock.sendall(struct.pack("!I", len(chunk)) + chunk)
        sock.sendall(struct.pack("!I", 0))
        response = b""
        while True:
            piece = sock.recv(4096)
            if not piece:
                break
            response += piece
            if response.endswith(b"\0"):
                break
    text = response.rstrip(b"\0").decode("ascii", errors="replace").strip()
    # Typical replies:
    #   "stream: OK"
    #   "stream: Eicar-Test-Signature FOUND"
    if text.endswith(": OK"):
        return ("ok", "")
    if text.endswith(" FOUND"):
        sig = text[len("stream: "):-len(" FOUND")].strip() or "unknown"
        return ("infected", sig)
    logger.warning("AV scan returned unexpected reply: %r", text[:200])
    return ("check_failed", "bad_response")


def _scan_http(data: bytes, endpoint: str, *, timeout: float) -> tuple[str, str]:
    """Scan via an HTTP POST.

    The endpoint receives the raw bytes as the request body. The
    response body is expected to be JSON ``{"stream": "OK"|"FOUND",
    "signature": "<name>"?}``. Other shapes (plain text "OK" /
    "FOUND", a 200 with empty body, etc.) are tolerated where the
    intent is unambiguous — anything else falls back to
    ``("check_failed", "bad_response")``.
    """
    req = Request(  # noqa: S310 - endpoint is operator-controlled, allowlisted by env
        endpoint,
        data=data,
        method="POST",
        headers={
            "Content-Type": "application/octet-stream",
            "User-Agent": "AMELI-App-Template-AV",
        },
    )
    with urlopen(req, timeout=timeout) as response:  # noqa: S310
        body = response.read()
    try:
        payload = json.loads(body.decode("utf-8", errors="replace"))
    except (ValueError, UnicodeDecodeError):
        # Plain-text body — accept "OK" / "FOUND" but flag anything else.
        text = body.decode("ascii", errors="replace").strip().upper()
        if text == "OK":
            return ("ok", "")
        if text == "FOUND":
            return ("infected", "unknown")
        return ("check_failed", "bad_response")
    verdict = (payload.get("stream") or "").upper()
    if verdict == "OK":
        return ("ok", "")
    if verdict == "FOUND":
        return ("infected", payload.get("signature") or "unknown")
    return ("check_failed", "bad_response")
