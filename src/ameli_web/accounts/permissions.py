"""Centralised authorization predicates (ASVS V1.4.4).

This module is the single source of truth for "is X allowed to do
Y?" decisions in the application. Callers ask
``is_superadmin(user)`` — they never inspect ``user.is_staff`` or
``user.role`` directly. If the role model evolves (e.g. a new
``ROLE_OPERATOR`` intermediate level), only this module changes
and every callsite picks up the new semantics for free.

Naming convention:

* ``is_*`` answers a categorical question about a single user
  (e.g. ``is_superadmin(user)``, ``is_protected_account(user)``).
* ``can_*`` answers an authorization question, often involving a
  target (e.g. ``can_view_avatar(requester, owner_slug,
  requester_slug)``, ``can_delete_user(actor, target)``).
* ``is_authenticated(user)`` is a defensive null-safe wrapper —
  callers should prefer it over ``user.is_authenticated`` so that
  ``None`` or anonymous-user shapes do not raise.

Side-effects (auditing, messaging) stay at the callsite. This
module returns booleans and nothing else; coupling audit-write
behaviour to a permission check would make tests painful and
would obscure the decision tree.
"""
from __future__ import annotations

from typing import Any


def is_authenticated(user: Any) -> bool:
    """True iff ``user`` is non-None and reports authenticated.

    Defensive against ``None`` and anonymous users so callers can
    drop the ``user is not None and`` boilerplate.
    """
    return bool(user) and bool(getattr(user, "is_authenticated", False))


def is_superadmin(user: Any) -> bool:
    """True iff ``user`` carries the SUPERADMIN role.

    The role bit is the source of truth — ``User.save`` keeps
    ``is_staff`` / ``is_superuser`` in lockstep with ``role``, but
    we read the semantic field directly so a future role change
    that desyncs the Django flags does not silently shift authz.
    """
    if not is_authenticated(user):
        return False
    # Local import: this module is imported very early (middleware,
    # context processors) and a top-level model import drags Django's
    # AppConfig machinery in before it is ready in some test paths.
    from ameli_web.accounts.models import User

    return getattr(user, "role", "") == User.ROLE_SUPERADMIN


def can_access_admin_panel(user: Any) -> bool:
    """Gate for ``/admin/`` UI + ``/admin/api/*`` JSON endpoints
    AND the framework-level ``/django-admin/``.

    Currently identical to ``is_superadmin`` — kept as a separate
    predicate so a future intermediate role (read-only operator,
    audit-only viewer) can be granted panel access without also
    being granted superadmin powers elsewhere.
    """
    return is_superadmin(user)


def can_view_avatar(requester: Any, *, is_owner: bool) -> bool:
    """IDOR check for ``/media/avatars/<slug>-<token>.<ext>``.

    Viewable by:

    * the owner — where ``is_owner`` is decided by the caller with an
      EXACT match of the requested path against the requester's stored
      ``avatar.name`` (which carries the unguessable random token), NOT a
      lossy username slug. The old slug comparison collided (``john.doe``,
      ``john_doe``, ``john@doe`` all slug to ``john-doe``), so a user who
      picked a slug-twin username could read another user's avatar despite
      this gate (L1 security review).
    * any superadmin (the operator may legitimately need to see the avatar
      in the user-list UI).

    Anonymous requesters get ``False`` even when ``is_owner`` — callers
    should have already enforced authentication; this is a second line of
    defence.
    """
    if not is_authenticated(requester):
        return False
    if is_owner:
        return True
    return is_superadmin(requester)


def is_protected_account(user: Any) -> bool:
    """True for accounts that the user-management flows must refuse
    to delete or disable.

    Currently: any superadmin. This keeps a "last operator" lockout
    from being one click away in the admin UI. The ``user`` argument
    here is the TARGET of the action, not the actor.
    """
    if user is None:
        return False
    from ameli_web.accounts.models import User

    return getattr(user, "role", "") == User.ROLE_SUPERADMIN


def can_delete_user(actor: Any, target: Any) -> bool:
    """Composite: actor must be a superadmin AND the target must
    not be a protected account.

    Used by the admin user-list UI to grey out the delete button on
    rows for superadmin accounts, AND by the service layer as the
    final authoritative check.
    """
    if not is_superadmin(actor):
        return False
    return not is_protected_account(target)


def can_self_delete(user: Any) -> bool:
    """A superadmin cannot self-delete (last-operator lockout).

    Distinct from ``can_delete_user`` because self-delete also
    needs an authenticated session of the user themselves — it is
    triggered from ``/profile/`` rather than the admin panel.
    """
    if not is_authenticated(user):
        return False
    return not is_protected_account(user)
