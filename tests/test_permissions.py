"""Regression coverage for ASVS V1.4.4 — single vetted access-control
mechanism.

Closes roadmap item #9. Before: ``is_staff`` / ``is_superuser`` /
``role == ROLE_SUPERADMIN`` were checked ad-hoc across
``admin_views.py``, ``accounts/middleware.py``,
``accounts/context_processors.py``, ``accounts/views.py``,
``ameli_web/urls.py`` and ``accounts/services.py``. Each callsite
re-derived the authz decision from raw Django flags — a refactor
that desyncs the flags from the semantic role would have silently
shifted gates.

After: every authz decision routes through
``accounts.permissions``. These tests pin the truth table for
each predicate and serve as the contract for future role
additions (e.g. an intermediate ``ROLE_OPERATOR``): adding a
role should require updating BOTH the relevant predicate AND the
corresponding test row here, in lockstep.
"""
from __future__ import annotations

import pytest

from ameli_web.accounts.models import User
from ameli_web.accounts.permissions import (
    can_access_admin_panel,
    can_delete_user,
    can_self_delete,
    can_view_avatar,
    is_authenticated,
    is_protected_account,
    is_superadmin,
)

# ---------------------------------------------------------------------------
# Lightweight fakes — predicates only touch ``role`` and
# ``is_authenticated`` so we do not need real ORM objects.
# ---------------------------------------------------------------------------

class _FakeUser:
    def __init__(self, *, role=User.ROLE_PUBLIC, is_authenticated=True, username="someone"):
        self.role = role
        self.is_authenticated = is_authenticated
        self.username = username


_SUPER = _FakeUser(role=User.ROLE_SUPERADMIN, username="root")
_PUBLIC = _FakeUser(role=User.ROLE_PUBLIC, username="alice")
_ANON = _FakeUser(role=User.ROLE_PUBLIC, is_authenticated=False, username="")


# ---------------------------------------------------------------------------
# is_authenticated — null-safety
# ---------------------------------------------------------------------------

def test_is_authenticated_handles_none():
    assert is_authenticated(None) is False


def test_is_authenticated_handles_anonymous():
    assert is_authenticated(_ANON) is False


def test_is_authenticated_handles_logged_in_user():
    assert is_authenticated(_PUBLIC) is True


# ---------------------------------------------------------------------------
# is_superadmin
# ---------------------------------------------------------------------------

def test_is_superadmin_true_for_superadmin():
    assert is_superadmin(_SUPER) is True


def test_is_superadmin_false_for_public_role():
    assert is_superadmin(_PUBLIC) is False


def test_is_superadmin_false_for_anonymous():
    assert is_superadmin(_ANON) is False


def test_is_superadmin_false_for_none():
    assert is_superadmin(None) is False


def test_is_superadmin_does_not_trust_is_staff_alone():
    """A row whose ``is_staff`` desyncs from ``role`` must NOT be
    treated as superadmin — the role bit is the source of truth.
    Mirrors the invariant kept by ``User.save``.
    """
    rogue = _FakeUser(role=User.ROLE_PUBLIC)
    rogue.is_staff = True  # only matters if the predicate trusts it
    assert is_superadmin(rogue) is False


# ---------------------------------------------------------------------------
# can_access_admin_panel — currently == is_superadmin, but the
# tests assert the SEMANTIC contract so a future intermediate role
# can be added without rewriting them.
# ---------------------------------------------------------------------------

def test_can_access_admin_panel_allows_superadmin():
    assert can_access_admin_panel(_SUPER) is True


def test_can_access_admin_panel_rejects_public_user():
    assert can_access_admin_panel(_PUBLIC) is False


def test_can_access_admin_panel_rejects_anonymous():
    assert can_access_admin_panel(_ANON) is False


# ---------------------------------------------------------------------------
# can_view_avatar — IDOR check
# ---------------------------------------------------------------------------

def test_owner_can_view_own_avatar():
    # ``is_owner`` is decided by the caller via an exact avatar.name match.
    assert can_view_avatar(_PUBLIC, is_owner=True) is True


def test_other_public_user_cannot_view_someone_elses_avatar():
    assert can_view_avatar(_PUBLIC, is_owner=False) is False


def test_superadmin_can_view_any_avatar():
    assert can_view_avatar(_SUPER, is_owner=False) is True


def test_anonymous_cannot_view_any_avatar_even_as_owner():
    """Anonymous request must fail even when flagged owner — callers should
    have gated by authentication first; this is defence in depth."""
    assert can_view_avatar(_ANON, is_owner=True) is False


# ---------------------------------------------------------------------------
# is_protected_account — TARGET of delete/disable
# ---------------------------------------------------------------------------

def test_protected_account_blocks_superadmin():
    assert is_protected_account(_SUPER) is True


def test_protected_account_lets_public_user_be_deleted():
    assert is_protected_account(_PUBLIC) is False


def test_protected_account_handles_none():
    assert is_protected_account(None) is False


# ---------------------------------------------------------------------------
# can_delete_user — composite: actor superadmin AND target not protected
# ---------------------------------------------------------------------------

def test_superadmin_can_delete_public_user():
    assert can_delete_user(_SUPER, _PUBLIC) is True


def test_superadmin_cannot_delete_another_superadmin():
    other_super = _FakeUser(role=User.ROLE_SUPERADMIN, username="other_root")
    assert can_delete_user(_SUPER, other_super) is False


def test_public_user_cannot_delete_anyone():
    assert can_delete_user(_PUBLIC, _PUBLIC) is False
    assert can_delete_user(_PUBLIC, _SUPER) is False


def test_anonymous_cannot_delete_anyone():
    assert can_delete_user(_ANON, _PUBLIC) is False


# ---------------------------------------------------------------------------
# can_self_delete — last-operator lockout
# ---------------------------------------------------------------------------

def test_public_user_can_self_delete():
    assert can_self_delete(_PUBLIC) is True


def test_superadmin_cannot_self_delete():
    assert can_self_delete(_SUPER) is False


def test_anonymous_cannot_self_delete():
    assert can_self_delete(_ANON) is False


# ---------------------------------------------------------------------------
# Integration: predicates against a real ORM User
# ---------------------------------------------------------------------------

@pytest.mark.django_db
def test_real_superadmin_user_passes_predicates():
    user = User.objects.create_user(
        username="real_root", password="x", role=User.ROLE_SUPERADMIN,
    )
    assert is_superadmin(user) is True
    assert can_access_admin_panel(user) is True
    assert is_protected_account(user) is True
    assert can_self_delete(user) is False


@pytest.mark.django_db
def test_real_public_user_predicates():
    user = User.objects.create_user(
        username="real_alice", password="x", role=User.ROLE_PUBLIC,
    )
    assert is_superadmin(user) is False
    assert can_access_admin_panel(user) is False
    assert is_protected_account(user) is False
    assert can_self_delete(user) is True
