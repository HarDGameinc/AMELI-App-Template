from __future__ import annotations

import pytest
from django.contrib.auth import get_user_model

from ameli_web.pagination import (
    DEFAULT_PER_PAGE,
    MAX_PER_PAGE,
    coerce_page,
    coerce_per_page,
    paginate_list,
    paginate_queryset,
)

User = get_user_model()


# ---- coerce_page ----


@pytest.mark.parametrize("raw,expected", [
    ("1", 1),
    ("5", 5),
    ("  3  ", 3),
    ("0", 1),
    ("-7", 1),
    ("abc", 1),
    (None, 1),
    ("", 1),
])
def test_coerce_page_normalises_values(raw, expected):
    assert coerce_page(raw) == expected


def test_coerce_page_honours_custom_default():
    assert coerce_page("not-a-number", default=4) == 4


# ---- coerce_per_page ----


def test_coerce_per_page_uses_default_when_missing():
    assert coerce_per_page(None) == DEFAULT_PER_PAGE


def test_coerce_per_page_clamps_above_maximum():
    assert coerce_per_page(str(MAX_PER_PAGE + 500)) == MAX_PER_PAGE


def test_coerce_per_page_rejects_non_positive():
    assert coerce_per_page("0") == DEFAULT_PER_PAGE
    assert coerce_per_page("-3") == DEFAULT_PER_PAGE


def test_coerce_per_page_accepts_explicit_value():
    assert coerce_per_page("42") == 42


# ---- paginate_list ----


def test_paginate_list_first_page_returns_first_window():
    rows = list(range(50))
    page = paginate_list(rows, page=1, per_page=10)

    assert page.items == list(range(10))
    assert page.page == 1
    assert page.total == 50
    assert page.total_pages == 5
    assert page.has_prev is False
    assert page.has_next is True
    assert page.start_index == 1
    assert page.end_index == 10


def test_paginate_list_middle_page_has_both_neighbours():
    page = paginate_list(list(range(50)), page=3, per_page=10)

    assert page.items == list(range(20, 30))
    assert page.has_prev is True
    assert page.has_next is True
    assert page.start_index == 21
    assert page.end_index == 30


def test_paginate_list_last_page_no_next():
    page = paginate_list(list(range(45)), page=5, per_page=10)

    assert page.items == [40, 41, 42, 43, 44]
    assert page.has_next is False
    assert page.end_index == 45


def test_paginate_list_page_overflow_clamps_to_last_page():
    page = paginate_list(list(range(20)), page=99, per_page=10)

    assert page.page == 2
    assert page.items == list(range(10, 20))


def test_paginate_list_empty_input_renders_zero_state():
    page = paginate_list([], page=1, per_page=10)

    assert page.items == []
    assert page.total == 0
    assert page.start_index == 0
    assert page.end_index == 0
    assert page.has_prev is False
    assert page.has_next is False


def test_paginate_list_per_page_is_clamped_to_at_least_one():
    page = paginate_list([1, 2, 3], page=1, per_page=0)

    assert page.per_page == 1
    assert page.items == [1]


# ---- paginate_queryset ----


@pytest.mark.django_db
def test_paginate_queryset_returns_window_and_total(db):
    for index in range(30):
        User.objects.create_user(username=f"user-{index:02d}", password="Test12345abc?")
    queryset = User.objects.order_by("username")

    page = paginate_queryset(queryset, page=2, per_page=10)

    assert len(page.items) == 10
    assert page.total == 30
    assert page.total_pages == 3
    assert page.page == 2
    assert page.has_prev is True
    assert page.has_next is True
    assert page.items[0].username == "user-10"


@pytest.mark.django_db
def test_paginate_queryset_overflow_clamps_to_last(db):
    for index in range(15):
        User.objects.create_user(username=f"user-{index:02d}", password="Test12345abc?")

    page = paginate_queryset(User.objects.order_by("username"), page=999, per_page=5)

    assert page.page == 3
    assert len(page.items) == 5


@pytest.mark.django_db
def test_paginate_queryset_empty_returns_zero_state(db):
    page = paginate_queryset(User.objects.none(), page=1, per_page=10)

    assert page.items == []
    assert page.total == 0
    assert page.has_prev is False
    assert page.has_next is False


# ---- Page.as_context ----


def test_as_context_exposes_template_friendly_dict():
    page = paginate_list(list(range(30)), page=2, per_page=10)

    ctx = page.as_context(page_param="users_page")

    assert ctx["page_param"] == "users_page"
    assert ctx["page"] == 2
    assert ctx["prev_page"] == 1
    assert ctx["next_page"] == 3
    assert ctx["total"] == 30
    assert ctx["start_index"] == 11
    assert ctx["end_index"] == 20
    assert "items" in ctx
