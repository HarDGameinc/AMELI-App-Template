"""Reusable offset/limit pagination for listings rendered via Django.

The Template surfaces three operational listings (profile sessions, admin
users, admin audit) that grow over time. We want a single, predictable
"Mostrando X-Y de N" + Prev/Next pattern for all of them, with stable URL
state so refreshing or sharing a link lands on the same window.

This module deliberately stays small. Per-page sizes are clamped, the
"page" parameter is coerced and normalised, and the page object exposes
everything the template needs without extra Django template logic.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from django.core.paginator import EmptyPage, Paginator
from django.db.models import QuerySet

DEFAULT_PER_PAGE = 20
MAX_PER_PAGE = 200


@dataclass(frozen=True)
class Page:
    """View-friendly snapshot of a paginated slice.

    ``items`` is the actual list of records for the current window (already
    materialised, so the template can iterate it twice if needed). The
    remaining fields drive the footer ("Mostrando 1-20 de 137") and the
    Prev/Next controls.
    """

    items: list[Any]
    page: int
    per_page: int
    total: int
    total_pages: int
    has_prev: bool
    has_next: bool
    start_index: int
    end_index: int

    @property
    def prev_page(self) -> int:
        return max(1, self.page - 1)

    @property
    def next_page(self) -> int:
        return min(self.total_pages or 1, self.page + 1)

    def as_context(self, *, page_param: str = "page") -> dict[str, Any]:
        """Return the dict shape used by ``pagination_footer.html``.

        ``page_param`` is the query-string key the footer should append to
        the current URL (``users_page``, ``audit_page``, ...). Storing it
        in the context lets one template render multiple paginated panels
        on the same page without colliding.
        """
        return {
            "items": self.items,
            "page": self.page,
            "per_page": self.per_page,
            "total": self.total,
            "total_pages": self.total_pages,
            "has_prev": self.has_prev,
            "has_next": self.has_next,
            "prev_page": self.prev_page,
            "next_page": self.next_page,
            "start_index": self.start_index,
            "end_index": self.end_index,
            "page_param": page_param,
        }


def coerce_page(raw: Any, *, default: int = 1) -> int:
    """Normalise a request value (``request.GET.get(...)``) into a page int.

    Anything that does not parse cleanly falls back to ``default``. Negative
    or zero values are clamped to ``1`` so the rest of the helpers can assume
    a 1-based index.
    """
    try:
        value = int(str(raw).strip())
    except (TypeError, ValueError):
        return default
    return max(1, value)


def coerce_per_page(raw: Any, *, default: int = DEFAULT_PER_PAGE, maximum: int = MAX_PER_PAGE) -> int:
    """Same idea as :func:`coerce_page` for ``per_page``, clamped to ``maximum``.

    The upper bound stops a malicious or accidental ``?per_page=99999`` from
    pulling an entire table into memory.
    """
    try:
        value = int(str(raw).strip())
    except (TypeError, ValueError):
        return default
    if value < 1:
        return default
    return min(value, maximum)


def paginate_queryset(
    queryset: QuerySet,
    *,
    page: int = 1,
    per_page: int = DEFAULT_PER_PAGE,
) -> Page:
    """Slice ``queryset`` into a :class:`Page` snapshot.

    Uses Django's :class:`~django.core.paginator.Paginator` under the hood so
    the SQL is the standard ``LIMIT/OFFSET`` Django emits for every paginated
    admin. If ``page`` overflows past the last page we clamp to the final
    page rather than raising; in operational tooling we'd rather show the
    last window than a 404.
    """
    per_page = max(1, per_page)
    page = max(1, page)
    paginator = Paginator(queryset, per_page)
    try:
        slice_ = paginator.page(page)
    except EmptyPage:
        slice_ = paginator.page(paginator.num_pages or 1)
        page = slice_.number

    total = paginator.count
    start_index = slice_.start_index() if total else 0
    end_index = slice_.end_index() if total else 0

    return Page(
        items=list(slice_.object_list),
        page=page,
        per_page=per_page,
        total=total,
        total_pages=paginator.num_pages,
        has_prev=slice_.has_previous(),
        has_next=slice_.has_next(),
        start_index=start_index,
        end_index=end_index,
    )


def paginate_list(
    rows: list[Any],
    *,
    page: int = 1,
    per_page: int = DEFAULT_PER_PAGE,
) -> Page:
    """In-memory variant of :func:`paginate_queryset`.

    Useful for paginating already-serialised lists (for example a list of
    ``serialize_session`` dicts that were built from ``user.web_sessions``)
    without converting them back to a queryset.
    """
    per_page = max(1, per_page)
    page = max(1, page)
    total = len(rows)
    total_pages = max(1, (total + per_page - 1) // per_page) if total else 1
    if page > total_pages:
        page = total_pages
    start = (page - 1) * per_page
    end = start + per_page
    items = rows[start:end]
    start_index = start + 1 if items else 0
    end_index = start + len(items) if items else 0
    return Page(
        items=items,
        page=page,
        per_page=per_page,
        total=total,
        total_pages=total_pages,
        has_prev=page > 1,
        has_next=page < total_pages,
        start_index=start_index,
        end_index=end_index,
    )
