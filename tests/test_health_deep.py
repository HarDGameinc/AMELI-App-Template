"""Regression coverage for Phase 2 #5 — ``/health/deep`` endpoint.

Closes the gap where ``/health`` only inspected config (smtp
configured, queue not stalled, disk has free bytes, db.status
returns ok) but never actually wrote a row or a file. A deploy
with a read-only DB replica or a read-only data dir would pass
``/health`` and silently fail at the first user write.

``/health/deep`` actually exercises the write path inside a
rolled-back savepoint (DB) plus a real tmpfile write+read+unlink
(FS). Returns 200 with ok=true when both probes succeed, 503
when either fails. Each check reports its own ``ms`` latency
so external monitors can alert on regressions.
"""
from __future__ import annotations

import dataclasses
from pathlib import Path

import pytest


def _override_data_dir(monkeypatch, path) -> None:
    """``settings.CFG`` is a frozen dataclass — clone-then-replace
    instead of mutating in place. Pattern stolen from
    ``test_openapi_sri_policy.py``.
    """
    from django.conf import settings as django_settings

    new_cfg = dataclasses.replace(django_settings.CFG, data_dir=Path(path))
    monkeypatch.setattr(django_settings, "CFG", new_cfg)


@pytest.mark.django_db
def test_deep_health_returns_200_when_db_and_fs_write_ok(client):
    response = client.get("/health/deep")
    assert response.status_code == 200, response.content
    payload = response.json()
    assert payload["ok"] is True
    assert payload["status"] == "OPERATIVO"
    assert "checks" in payload
    for key in ("db_write", "fs_write"):
        assert key in payload["checks"], f"missing check: {key}"
        assert payload["checks"][key]["ok"] is True
        assert "ms" in payload["checks"][key], "each check reports its own latency"


@pytest.mark.django_db
def test_deep_health_endpoint_only_accepts_get(client):
    """ASVS V13.2.1 — HTTP verb discipline."""
    response = client.post("/health/deep")
    # require_GET returns 405 Method Not Allowed
    assert response.status_code == 405


@pytest.mark.django_db
def test_deep_health_in_openapi_schema(client):
    """The endpoint must appear in the OpenAPI spec or the
    drift detector in test_openapi_contract.py would flag it
    as an undocumented public JSON endpoint. Only the 200
    branch is in the spec — the 503 branch shares the schema
    but is described in the 200 entry's prose to keep the
    contract test from asserting 503 against a healthy deploy.
    """
    response = client.get("/openapi.json")
    spec = response.json()
    assert "/health/deep" in spec["paths"]
    op = spec["paths"]["/health/deep"]["get"]
    assert "200" in op["responses"]


@pytest.mark.django_db
def test_deep_health_db_check_leaves_no_state(client, transactional_db):
    """The probe writes inside a savepoint and rolls back. Running
    it 5 times in a row should NOT accumulate any row in any
    user-visible table.
    """
    from ameli_web.audit.models import AuditEvent

    before = AuditEvent.objects.count()
    for _ in range(5):
        response = client.get("/health/deep")
        assert response.status_code == 200
    after = AuditEvent.objects.count()
    assert before == after, "deep health probe leaked AuditEvent rows"


@pytest.mark.django_db
def test_deep_health_fs_check_leaves_no_state(client, tmp_path, monkeypatch):
    """Probe creates a tmpfile and unlinks it. After the call,
    DATA_DIR should not have any ``.health-probe-*.tmp`` lingering.
    """
    _override_data_dir(monkeypatch, tmp_path)
    response = client.get("/health/deep")
    assert response.status_code == 200
    assert response.json()["checks"]["fs_write"]["ok"] is True
    leftovers = list(tmp_path.glob(".health-probe-*.tmp"))
    assert not leftovers, f"deep health fs probe leaked files: {leftovers}"


@pytest.mark.django_db
def test_deep_health_503_when_fs_dir_does_not_exist(client, monkeypatch):
    """When the configured data dir is missing, the fs probe MUST
    fail (not silently succeed) and the overall response MUST be
    503.
    """
    _override_data_dir(monkeypatch, "/nonexistent/path/that/cannot/exist/12345")
    response = client.get("/health/deep")
    assert response.status_code == 503, response.content
    payload = response.json()
    assert payload["ok"] is False
    assert payload["status"] == "DEGRADADO"
    assert payload["checks"]["fs_write"]["ok"] is False
    # Class name surfaces (FileNotFoundError, etc) — never the
    # actual error message which could leak paths.
    assert "detail" in payload["checks"]["fs_write"]


@pytest.mark.django_db
def test_deep_health_probe_does_not_leak_exception_message(client, monkeypatch):
    """The probe catches Exception and surfaces only the class
    NAME, never the message — error messages can leak paths,
    table names, or connection strings.
    """
    _override_data_dir(monkeypatch, "/nonexistent/path/that/cannot/exist/12345")
    response = client.get("/health/deep")
    payload = response.json()
    detail = payload["checks"]["fs_write"]["detail"]
    # Class names are short identifiers; messages tend to carry
    # path strings with ``/`` or quotes.
    assert "/" not in detail, f"detail leaked a path-shaped string: {detail!r}"
    assert "'" not in detail
    assert '"' not in detail
