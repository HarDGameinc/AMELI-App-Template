"""Upstream finding T-5 (2026-08-04): the sliding-window counter rounds the
previous-bucket contribution UP, so a single prior attempt biases the count
by +1 for the whole current window. Harmless at the caps this template uses
(>= 5) but 100% of the budget at cap == 1 — a fork used cap == 1 and locked
users out permanently. Pin the bias so the docstring warning stays honest.
"""
from __future__ import annotations

from datetime import UTC, datetime

import pytest
from django.utils import timezone

from ameli_web.accounts.models import ThrottleCounter
from ameli_web.accounts.services.throttle import (
    _read_throttle_counter,
    _read_throttle_counter_sliding,
)


@pytest.mark.django_db
def test_sliding_counter_biases_up_by_one_from_previous_window():
    window = 60
    epoch = int(timezone.now().timestamp())
    bucket = (epoch // window) * window
    prev_start = datetime.fromtimestamp(bucket - window, tz=UTC)

    # One attempt in the PREVIOUS window, none in the current one.
    ThrottleCounter.objects.create(
        scope="t5", key="k", window_start=prev_start, count=1,
    )

    sliding = _read_throttle_counter_sliding(scope="t5", key="k", window_seconds=window)
    # The +1 boundary bias: this is exactly why cap < 3 is unsafe — at cap==1
    # a `count >= cap` gate would block forever off a single stale attempt.
    assert sliding == 1

    # The fixed-bucket reader has NO cross-window bias — the documented
    # escape hatch for a strict low-cap gate.
    fixed = _read_throttle_counter(scope="t5", key="k", window_seconds=window)
    assert fixed == 0


def test_docstring_documents_the_low_cap_constraint():
    assert "below 3" in _read_throttle_counter_sliding.__doc__
    assert "_read_throttle_counter" in _read_throttle_counter_sliding.__doc__
