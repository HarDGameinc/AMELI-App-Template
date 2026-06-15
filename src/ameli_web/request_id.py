"""Request correlation id.

Every HTTP request gets a stable id (either the ``X-Request-Id``
header sent by an upstream proxy, or a fresh UUID minted here). The
id is stashed on a contextvar so any code path running on this
request can attach it to logs / audit rows without manual plumbing,
and copied onto the response so a client / load balancer can stitch
together a request across services.

A logging filter (:class:`RequestIdLogFilter`) promotes the id to a
``request_id`` attribute on every log record so the JSON formatter
serializes it automatically and the text formatter can interpolate
it via ``%(request_id)s``.
"""
from __future__ import annotations

import logging
import re
import uuid
from collections.abc import Callable
from contextvars import ContextVar

from django.http import HttpRequest, HttpResponse

_request_id_var: ContextVar[str | None] = ContextVar("ameli_request_id", default=None)
_SAFE_RE = re.compile(r"^[A-Za-z0-9._\-]{1,128}$")
_HEADER_NAME = "HTTP_X_REQUEST_ID"
_RESPONSE_HEADER = "X-Request-Id"


def get_request_id() -> str:
    """Return the current request's id, or empty string outside a request."""
    return _request_id_var.get() or ""


def _coerce_inbound(value: str | None) -> str | None:
    """Accept an upstream id only if it looks safe.

    A malicious client could otherwise inject newlines, very long
    strings, or shell metacharacters into our logs. The ``_SAFE_RE``
    keeps us in the alphabet that traceparent / OpenTelemetry / most
    proxies use.
    """
    if not value:
        return None
    value = value.strip()
    if not _SAFE_RE.match(value):
        return None
    return value


class RequestIdMiddleware:
    """Stash an id on the request, propagate it to the response.

    Place this VERY early in the middleware list so every subsequent
    middleware and view runs under the contextvar.
    """

    def __init__(self, get_response: Callable[[HttpRequest], HttpResponse]):
        self.get_response = get_response

    def __call__(self, request: HttpRequest) -> HttpResponse:
        inbound = _coerce_inbound(request.META.get(_HEADER_NAME))
        request_id = inbound or uuid.uuid4().hex
        request.id = request_id  # type: ignore[attr-defined]
        token = _request_id_var.set(request_id)
        try:
            response = self.get_response(request)
            # Stamp the header inside the try block so a downstream
            # middleware that raises during response processing does
            # not strand the header. Django's view-level exception
            # handler converts view exceptions into a 500 response
            # before control returns here, so the normal error path
            # also lands on this assignment.
            response[_RESPONSE_HEADER] = request_id
            return response
        finally:
            _request_id_var.reset(token)

    def process_exception(self, request: HttpRequest, exception: BaseException) -> None:
        """Hook so Django's exception machinery runs with the
        ``ameli_request_id`` contextvar still set (the contextvar
        token is only reset in ``__call__``'s finally, after this
        method returns). Any audit row or log line emitted by the
        500 handler keeps its correlation id.
        """
        return None


class RequestIdLogFilter(logging.Filter):
    """Inject ``request_id`` on every log record so formatters can
    surface it without each call-site passing ``extra=``."""

    def filter(self, record: logging.LogRecord) -> bool:
        if not hasattr(record, "request_id"):
            record.request_id = _request_id_var.get() or "-"
        return True
