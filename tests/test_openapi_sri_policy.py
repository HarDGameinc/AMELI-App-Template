"""Regression coverage for ASVS V10.3.x — integrity protections on
third-party CDN bundles loaded by the docs panel.

Closes roadmap item #5. Previous behaviour: env vars
``AMELI_APP_SRI_*`` defaulted to empty strings; a deploy that did
not configure them silently served unsigned Swagger UI / ReDoc JS
from cdn.jsdelivr.net, breaking ASVS V10.3.x integrity protection.

New behaviour: ``/docs`` and ``/redoc`` refuse to render with HTTP
503 when ANY required SRI hash is missing AND the policy says SRI
is required (default: required outside ``dev``). Operator override
via ``settings.OPENAPI_SRI_REQUIRED`` (env
``AMELI_APP_OPENAPI_SRI_REQUIRED``). The escape hatch is documented
in the 503 body so an operator hitting the panel for the first time
in prod has a single-screen fix.

These tests pin every state-machine edge: dev pass-through, prod
refuse, prod with SRI configured renders, explicit opt-out renders,
explicit opt-in refuses even in dev, dev-with-partial-SRI still
renders, the 503 body names the missing keys, and the helper
``_docs_sri_ready`` reports correctly.
"""
from __future__ import annotations

import pytest

from ameli_web.dashboard.views import (
    _docs_sri_ready,
    _docs_sri_required,
)

# ---------------------------------------------------------------------------
# _docs_sri_ready helper
# ---------------------------------------------------------------------------

def test_sri_ready_returns_true_when_all_keys_present(settings):
    settings.CDN_SRI_HASHES = {
        "swagger_ui_css": "sha384-abc",
        "swagger_ui_bundle": "sha384-def",
        "swagger_ui_preset": "sha384-ghi",
        "redoc_bundle": "sha384-jkl",
    }
    ready, missing = _docs_sri_ready()
    assert ready is True
    assert missing == []


def test_sri_ready_lists_missing_keys(settings):
    settings.CDN_SRI_HASHES = {
        "swagger_ui_css": "sha384-abc",
        "swagger_ui_bundle": "",
        "swagger_ui_preset": "  ",
        "redoc_bundle": "sha384-jkl",
    }
    ready, missing = _docs_sri_ready()
    assert ready is False
    # Order preserved per _SRI_REQUIRED_KEYS.
    assert missing == ["swagger_ui_bundle", "swagger_ui_preset"]


# ---------------------------------------------------------------------------
# _docs_sri_required policy
# ---------------------------------------------------------------------------

def test_sri_required_is_false_in_dev(settings):
    settings.OPENAPI_SRI_REQUIRED = None
    settings.ENV_NAME = "dev"
    assert _docs_sri_required() is False


def test_sri_required_is_true_outside_dev(settings):
    settings.OPENAPI_SRI_REQUIRED = None
    settings.ENV_NAME = "prod"
    assert _docs_sri_required() is True


def test_explicit_opt_out_overrides_policy(settings):
    """``OPENAPI_SRI_REQUIRED=False`` lets the operator say "I know
    what I'm doing, render without SRI" even in prod (e.g. behind an
    air-gapped CDN mirror).
    """
    settings.OPENAPI_SRI_REQUIRED = False
    settings.ENV_NAME = "prod"
    assert _docs_sri_required() is False


def test_explicit_opt_in_overrides_dev_passthrough(settings):
    """The same flag set to True forces SRI even in dev — useful
    for an operator that wants to lint their config locally before
    deploying."""
    settings.OPENAPI_SRI_REQUIRED = True
    settings.ENV_NAME = "dev"
    assert _docs_sri_required() is True


# ---------------------------------------------------------------------------
# Endpoint behaviour
# ---------------------------------------------------------------------------

@pytest.mark.django_db
def test_docs_renders_in_dev_without_sri(client, settings):
    """DX preservation: a fresh checkout boots into dev and ``/docs``
    works without any operator config. The compliance gap closes
    outside dev only.
    """
    settings.ENV_NAME = "dev"
    settings.OPENAPI_SRI_REQUIRED = None
    settings.CDN_SRI_HASHES = {
        "swagger_ui_css": "",
        "swagger_ui_bundle": "",
        "swagger_ui_preset": "",
        "redoc_bundle": "",
    }
    response = client.get("/docs")
    assert response.status_code == 200
    assert b"SwaggerUIBundle" in response.content


@pytest.mark.django_db
def test_docs_refuses_in_prod_without_sri(client, settings):
    settings.ENV_NAME = "prod"
    settings.OPENAPI_SRI_REQUIRED = None
    settings.CDN_SRI_HASHES = {
        "swagger_ui_css": "",
        "swagger_ui_bundle": "",
        "swagger_ui_preset": "",
        "redoc_bundle": "",
    }
    response = client.get("/docs")
    assert response.status_code == 503
    body = response.json()
    assert body["ok"] is False
    # Body names every missing key so the operator does not play
    # whack-a-mole through env vars.
    assert set(body["missing_sri_keys"]) == {
        "swagger_ui_css", "swagger_ui_bundle",
        "swagger_ui_preset", "redoc_bundle",
    }
    # Body contains the fix path (env vars + helper script).
    assert "tools/sri_compute.py" in body["fix"]
    assert "AMELI_APP_SRI_SWAGGER_UI_CSS" in body["fix"]


@pytest.mark.django_db
def test_redoc_refuses_in_prod_without_sri(client, settings):
    settings.ENV_NAME = "prod"
    settings.OPENAPI_SRI_REQUIRED = None
    settings.CDN_SRI_HASHES = {
        "swagger_ui_css": "",
        "swagger_ui_bundle": "",
        "swagger_ui_preset": "",
        "redoc_bundle": "",
    }
    response = client.get("/redoc")
    assert response.status_code == 503
    body = response.json()
    assert body["view"] == "redoc"


@pytest.mark.django_db
def test_docs_renders_in_prod_with_full_sri(client, settings):
    settings.ENV_NAME = "prod"
    settings.OPENAPI_SRI_REQUIRED = None
    settings.CDN_SRI_HASHES = {
        "swagger_ui_css": "sha384-x" * 1,
        "swagger_ui_bundle": "sha384-y" * 1,
        "swagger_ui_preset": "sha384-z" * 1,
        "redoc_bundle": "sha384-w" * 1,
    }
    response = client.get("/docs")
    assert response.status_code == 200
    # The integrity attribute reaches the rendered HTML — the
    # operator's hash is actually exposed to the browser.
    assert b"integrity=" in response.content


@pytest.mark.django_db
def test_docs_renders_in_prod_with_explicit_opt_out(client, settings):
    """Operator behind an air-gapped CDN mirror opts out explicitly.
    The docs panel renders without SRI, which is the operator's
    informed risk acceptance.
    """
    settings.ENV_NAME = "prod"
    settings.OPENAPI_SRI_REQUIRED = False
    settings.CDN_SRI_HASHES = {
        "swagger_ui_css": "",
        "swagger_ui_bundle": "",
        "swagger_ui_preset": "",
        "redoc_bundle": "",
    }
    response = client.get("/docs")
    assert response.status_code == 200


@pytest.mark.django_db
def test_docs_disabled_returns_404_before_sri_check(client, settings, monkeypatch):
    """``docs_enabled=False`` 404s before the SRI check fires.
    Property: the operator's "no docs at all" decision wins.
    """
    settings.ENV_NAME = "prod"
    settings.OPENAPI_SRI_REQUIRED = None
    settings.CDN_SRI_HASHES = {k: "" for k in (
        "swagger_ui_css", "swagger_ui_bundle",
        "swagger_ui_preset", "redoc_bundle",
    )}
    # CFG is a frozen dataclass — patch a fresh copy with docs_enabled=False.
    import dataclasses

    new_cfg = dataclasses.replace(settings.CFG, docs_enabled=False)
    monkeypatch.setattr(settings, "CFG", new_cfg)
    response = client.get("/docs")
    assert response.status_code == 404
    body = response.json()
    assert "docs disabled" in body["error"]
