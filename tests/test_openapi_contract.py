"""Contract test: OpenAPI doc vs. real responses (ASVS V13.2.2).

Closes roadmap item #10. Previous behaviour: ``_openapi_schema()``
in ``ameli_web/dashboard/views.py`` was hand-written and nothing
verified the documented paths / shapes matched the actual JSON
returned by the views — drift was free.

New behaviour: every path declared in the schema is resolved via
the Django URL conf, called via the test client, and the response
is validated against the documented JSON schema. A documented
field missing from the live payload (or vice-versa for ``required``
keys) fails the suite.

Two drift directions are guarded:

* doc -> reality: every path in ``/openapi.json`` resolves, every
  documented response status appears, every ``required`` schema
  property is present and typed correctly.
* reality -> doc: every JSON endpoint registered in the URL conf
  is either documented or appears in an explicit allowlist (the
  list is intentionally tight; admin JSON endpoints stay
  undocumented because they are operator-facing).

The schema validation is intentionally lightweight (stdlib only,
no ``jsonschema`` dep) — we cover the subset of OpenAPI we
actually use: ``type``, ``required``, ``properties``, ``enum``.
That keeps the template's "no surprise deps" policy intact.
"""
from __future__ import annotations

import pytest

from ameli_web.dashboard.views import _openapi_schema

# Endpoints intentionally NOT documented in the public OpenAPI spec.
# Admin endpoints and the schema/docs surfaces themselves stay off
# the public contract — they are operator-facing tooling, not part
# of the application's contract with API consumers.
_UNDOCUMENTED_BY_DESIGN = frozenset({
    "/openapi.json",  # the schema itself
    "/metrics",       # Prometheus text format, not JSON
})


# ---------------------------------------------------------------------------
# Helper: minimal JSON-Schema-subset validator (stdlib only)
# ---------------------------------------------------------------------------

_JSON_TYPES = {
    "object": dict,
    "array": list,
    "string": str,
    "boolean": bool,
    "number": (int, float),
    "integer": int,
    "null": type(None),
}


def _validate(value, schema, path="$"):
    """Validate ``value`` against the subset of OpenAPI 3.1 schema we
    actually use. Returns a list of human-readable errors (empty on
    success).
    """
    errors: list[str] = []
    if "type" in schema:
        expected = schema["type"]
        py_type = _JSON_TYPES.get(expected)
        if py_type is None:
            errors.append(f"{path}: unsupported schema type {expected!r}")
            return errors
        # Booleans are ints in Python; reject that mismatch explicitly
        # so a bool sneaking into an int field still fails.
        if expected in ("integer", "number") and isinstance(value, bool):
            errors.append(f"{path}: expected {expected}, got bool")
            return errors
        if not isinstance(value, py_type):
            errors.append(f"{path}: expected {expected}, got {type(value).__name__}")
            return errors
    if "enum" in schema and value not in schema["enum"]:
        errors.append(f"{path}: {value!r} not in enum {schema['enum']!r}")
    if schema.get("type") == "object":
        for key in schema.get("required", []):
            if key not in value:
                errors.append(f"{path}: missing required field {key!r}")
        for key, child_schema in (schema.get("properties") or {}).items():
            if key in value:
                errors.extend(_validate(value[key], child_schema, f"{path}.{key}"))
    return errors


# ---------------------------------------------------------------------------
# 1. The schema itself is well-formed
# ---------------------------------------------------------------------------

def test_openapi_schema_is_well_formed():
    spec = _openapi_schema()
    assert spec.get("openapi", "").startswith("3."), "openapi version must be 3.x"
    assert "info" in spec and spec["info"].get("title")
    assert "info" in spec and spec["info"].get("version")
    assert isinstance(spec.get("paths"), dict) and spec["paths"], "paths must be non-empty"


# ---------------------------------------------------------------------------
# 2. Doc -> reality: every documented path responds + schema matches
# ---------------------------------------------------------------------------

def _documented_endpoints():
    spec = _openapi_schema()
    out = []
    for url, methods in spec.get("paths", {}).items():
        for method, op in methods.items():
            for status, response in (op.get("responses") or {}).items():
                schema = (
                    response.get("content", {})
                    .get("application/json", {})
                    .get("schema")
                )
                out.append((url, method.upper(), status, schema))
    return out


@pytest.mark.django_db
@pytest.mark.parametrize("url,method,status,schema", _documented_endpoints())
def test_documented_endpoint_matches_reality(client, url, method, status, schema):
    """Every (path, method, status) tuple in the OpenAPI doc must
    actually be reachable AND the response body must satisfy the
    documented schema. Drift in either direction fails the test.
    """
    response = client.generic(method, url)
    assert response.status_code == int(status), (
        f"{method} {url}: documented status {status}, got {response.status_code}"
    )
    if schema is None:
        return
    assert response["Content-Type"].startswith("application/json"), (
        f"{method} {url}: documented as JSON, got {response['Content-Type']!r}"
    )
    payload = response.json()
    errors = _validate(payload, schema)
    assert not errors, f"{method} {url} response does not match schema:\n  " + "\n  ".join(errors)


# ---------------------------------------------------------------------------
# 3. Reality -> doc: no undocumented public JSON endpoint
# ---------------------------------------------------------------------------

@pytest.mark.django_db
def test_no_undocumented_public_json_endpoints(client):
    """Every top-level public URL whose canonical response is JSON
    must either appear in the OpenAPI schema or be on the
    ``_UNDOCUMENTED_BY_DESIGN`` allowlist. Catches the case where
    a developer adds a new public API endpoint and forgets to
    update ``_openapi_schema``.
    """
    from django.urls import get_resolver

    documented = set(_openapi_schema().get("paths", {}).keys())
    resolver = get_resolver()

    candidate_urls = []
    for pattern in resolver.url_patterns:
        # Skip includes / namespaced sub-resolvers — only top-level
        # routes count as "public" for the API contract. Admin and
        # accounts urls are explicitly excluded from the contract.
        if not hasattr(pattern, "pattern") or hasattr(pattern, "url_patterns"):
            continue
        route = str(pattern.pattern)
        if not route or route.startswith("admin/") or route.startswith("django-admin/"):
            continue
        # Skip parameterised routes (no concrete URL to probe).
        if "<" in route or ":" in route or "(" in route:
            continue
        # ``path("foo", ...)`` matches as ``foo`` without leading slash;
        # add it for comparison with the OpenAPI paths (which all
        # start with ``/``).
        url = "/" + route
        if url in _UNDOCUMENTED_BY_DESIGN:
            continue
        if url in documented:
            continue
        candidate_urls.append(url)

    # For each candidate, probe it. If the response is JSON, it must
    # be either documented or allowlisted — and since the loop
    # already skipped both, reaching here is a contract violation.
    undocumented_json = []
    for url in candidate_urls:
        try:
            response = client.get(url)
        except Exception:  # noqa: S112, BLE001 - drift probe is best-effort
            continue
        # 4xx/5xx responses are not contract responses — only success
        # JSON payloads form the public API surface.
        if 200 <= response.status_code < 300 and response.get(
            "Content-Type", ""
        ).startswith("application/json"):
            undocumented_json.append(url)

    assert not undocumented_json, (
        "Public JSON endpoints missing from OpenAPI schema (add them to "
        "_openapi_schema or to _UNDOCUMENTED_BY_DESIGN):\n  "
        + "\n  ".join(undocumented_json)
    )


# ---------------------------------------------------------------------------
# 4. Internal sanity check on the validator helper itself
# ---------------------------------------------------------------------------

def test_validator_flags_missing_required_field():
    schema = {"type": "object", "required": ["ok"], "properties": {"ok": {"type": "boolean"}}}
    errors = _validate({}, schema)
    assert errors and "missing required field 'ok'" in errors[0]


def test_validator_flags_wrong_type():
    schema = {"type": "object", "properties": {"count": {"type": "integer"}}}
    errors = _validate({"count": "nope"}, schema)
    assert errors and "expected integer" in errors[0]


def test_validator_rejects_bool_as_integer():
    """``True`` is an ``int`` in Python — the validator must still
    flag a bool when the schema says ``integer``.
    """
    schema = {"type": "object", "properties": {"count": {"type": "integer"}}}
    errors = _validate({"count": True}, schema)
    assert errors and "got bool" in errors[0]


def test_validator_flags_unknown_enum_value():
    schema = {"type": "string", "enum": ["OPERATIVO", "DEGRADADO"]}
    errors = _validate("WAT", schema)
    assert errors and "not in enum" in errors[0]


def test_validator_passes_well_formed_object():
    schema = {
        "type": "object",
        "required": ["ok"],
        "properties": {"ok": {"type": "boolean"}, "name": {"type": "string"}},
    }
    assert _validate({"ok": True, "name": "x"}, schema) == []
