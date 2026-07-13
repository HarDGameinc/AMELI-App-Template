"""Migration graph health — drift detection + reversibility.

Closes the "No Django migration tests (apply/rollback in CI)" gap noted in
``AGENTS.md`` → Testing gaps. CI already runs ``makemigrations --check``
(drift) and a forward ``migrate`` (see ``.github/workflows/ci.yml``), so what
was missing was **reversibility**: that every first-party migration — including
the three ``RunPython`` data migrations (``accounts.0004``/``0005`` no-op
reverse, ``0012`` Fernet decrypt reverse) — can actually be rolled back.

The reversibility test runs the round-trip on the shared test database
(``transaction=True`` so the DDL commits) and a ``finally`` always re-migrates
forward to head, so the database is left fully migrated for the rest of the
suite even if an assertion fails. It cannot use an isolated secondary database
because the data migrations query ``User.objects`` on the default connection
(they are single-DB migrations, not ``using()``-routed — correct for the app).
"""
from __future__ import annotations

from io import StringIO

import pytest
from django.apps import apps
from django.core.management import call_command
from django.db import connection

# First-party apps whose migrations we own and want to prove reversible.
# ``audit`` is listed first so it is rolled back before ``accounts`` (its
# ``AuditEvent`` references the user model).
FIRST_PARTY_APP_LABELS = ("audit", "accounts")


def _first_party_tables() -> set[str]:
    """DB table names for the concrete (managed, non-proxy) models of our
    first-party apps — derived from the model registry so the assertions do
    not hardcode a table list that drifts as models are added."""
    tables: set[str] = set()
    for app_label in FIRST_PARTY_APP_LABELS:
        for model in apps.get_app_config(app_label).get_models():
            if model._meta.managed and not model._meta.proxy:
                tables.add(model._meta.db_table)
    return tables


@pytest.mark.django_db
def test_no_missing_migrations():
    """Models and migration files must not have drifted apart. This mirrors
    the CI ``makemigrations --check`` gate but runs in every environment that
    runs the test suite (local, and every CI job), not just the one job."""
    out = StringIO()
    try:
        call_command("makemigrations", "--check", "--dry-run", stdout=out, stderr=out)
    except SystemExit as exc:  # ``--check`` exits non-zero when changes are pending
        if exc.code:
            pytest.fail(
                "Model changes are not reflected in a migration — run "
                "`python -m django makemigrations`:\n" + out.getvalue()
            )


@pytest.mark.django_db(transaction=True)
def test_first_party_migrations_reverse_and_reapply_cleanly():
    """Roll the first-party apps back to ``zero`` (exercising every reverse
    operation, including the ``RunPython`` reverses) and then forward again.
    An irreversible migration raises ``IrreversibleError`` here; a reverse that
    leaves a table behind, or a re-apply that does not restore one, fails the
    assertions. The ``finally`` guarantees the shared DB ends at head."""
    expected = _first_party_tables()
    assert "accounts_user" in expected, "sanity: the custom user table is first-party"

    def live_tables() -> set[str]:
        return set(connection.introspection.table_names())

    # Precondition: pytest-django built the test DB from migrations, so every
    # first-party table is present before we start.
    assert not (expected - live_tables()), "test DB was not fully migrated at start"

    try:
        # 1. Reverse each first-party app to zero (audit before accounts).
        for app_label in FIRST_PARTY_APP_LABELS:
            call_command("migrate", app_label, "zero", verbosity=0)
        leftover = expected & live_tables()
        assert not leftover, f"reverse to zero left tables behind: {sorted(leftover)}"

        # 2. Forward again — re-application must restore every table cleanly.
        call_command("migrate", verbosity=0)
        missing = expected - live_tables()
        assert not missing, f"re-apply did not restore: {sorted(missing)}"
    finally:
        # Always leave the shared test DB fully migrated for later tests, even
        # if an assertion above failed mid-round-trip.
        call_command("migrate", verbosity=0)
