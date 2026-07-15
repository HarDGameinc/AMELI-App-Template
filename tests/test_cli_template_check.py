from __future__ import annotations

import argparse
import json
import urllib.error

import pytest

from ameli_app import cli


def test_parse_semver():
    assert cli._parse_semver("v0.5.2-django") == (0, 5, 2)
    assert cli._parse_semver("1.2.3") == (1, 2, 3)
    assert cli._parse_semver("no-numbers") is None
    assert cli._parse_semver("") is None


@pytest.mark.parametrize(
    "current,latest,expected",
    [
        ("v0.5.2-django", "v0.5.2-django", "up-to-date"),
        ("v0.5.0-django", "v0.5.2-django", "behind"),
        ("v0.6.0-django", "v0.5.2-django", "ahead"),
        ("weird", "v0.5.2-django", "unknown"),
    ],
)
def test_lineage_status(current, latest, expected):
    assert cli._lineage_status(current, latest) == expected


def test_template_lineage_env_override(monkeypatch):
    monkeypatch.setenv("AMELI_APP_TEMPLATE_LINEAGE", "v0.4.0-django")
    assert cli._template_lineage() == "v0.4.0-django"


def test_template_lineage_falls_back_to_version(monkeypatch):
    monkeypatch.delenv("AMELI_APP_TEMPLATE_LINEAGE", raising=False)
    # The template repo has no TEMPLATE_LINEAGE file → the app's own VERSION.
    assert cli._template_lineage() == cli.__version__


class _FakeResp:
    def __init__(self, payload):
        self._data = json.dumps(payload).encode()

    def read(self, *_):
        return self._data

    def __enter__(self):
        return self

    def __exit__(self, *_):
        return False


def _args(repo="owner/name", timeout=5.0):
    return argparse.Namespace(repo=repo, timeout=timeout)


def test_template_check_up_to_date(monkeypatch, capsys):
    monkeypatch.setenv("AMELI_APP_TEMPLATE_LINEAGE", "v1.0.0-django")
    monkeypatch.setattr(
        "urllib.request.urlopen",
        lambda *a, **k: _FakeResp(
            {"tag_name": "v1.0.0-django", "html_url": "u", "body": "notes"}
        ),
    )
    rc = cli._handle_template_check(_args())
    out = json.loads(capsys.readouterr().out)
    assert rc == 0
    assert out["status"] == "up-to-date"
    assert out["latest"] == "v1.0.0-django"


def test_template_check_behind_exits_1(monkeypatch, capsys):
    monkeypatch.setenv("AMELI_APP_TEMPLATE_LINEAGE", "v0.5.0-django")
    monkeypatch.setattr(
        "urllib.request.urlopen",
        lambda *a, **k: _FakeResp({"tag_name": "v0.5.2-django", "body": "SECURITY: CVE fix"}),
    )
    rc = cli._handle_template_check(_args())
    out = json.loads(capsys.readouterr().out)
    assert rc == 1
    assert out["status"] == "behind"


def test_template_check_invalid_repo(capsys):
    rc = cli._handle_template_check(_args(repo="not-a-repo"))
    out = json.loads(capsys.readouterr().out)
    assert rc == 2
    assert out["ok"] is False


def test_template_check_404_hints_token(monkeypatch, capsys):
    def _raise(*_a, **_k):
        raise urllib.error.HTTPError("url", 404, "Not Found", {}, None)

    monkeypatch.setattr("urllib.request.urlopen", _raise)
    rc = cli._handle_template_check(_args())
    out = json.loads(capsys.readouterr().out)
    assert rc == 2
    assert "404" in out["error"]
    assert "GITHUB_TOKEN" in out["error"]


def test_template_check_403_rate_limit_is_actionable(monkeypatch, capsys):
    """An anonymous caller gets 60 req/hour per IP; when exhausted GitHub
    returns 403 with X-RateLimit-Remaining: 0. The message must name the cause
    and the fix, not just echo an opaque 'github api 403'.
    """
    def _raise(*_a, **_k):
        raise urllib.error.HTTPError(
            "url", 403, "Forbidden", {"X-RateLimit-Remaining": "0"}, None
        )

    monkeypatch.setattr("urllib.request.urlopen", _raise)
    rc = cli._handle_template_check(_args())
    out = json.loads(capsys.readouterr().out)
    assert rc == 2
    assert "rate-limited" in out["error"]
    assert "GITHUB_TOKEN" in out["error"]


def test_template_check_survives_non_ascii_release_notes(monkeypatch, capsys):
    """Regression: a release note with a non-ASCII char (the emoji in a
    security note) must not crash ``_json`` on a non-UTF-8 console. This is the
    channel a child app uses to LEARN about a security release, so a crash here
    hides exactly the update it is meant to surface.
    """
    monkeypatch.setenv("AMELI_APP_TEMPLATE_LINEAGE", "v1.0.0-django")
    monkeypatch.setattr(
        "urllib.request.urlopen",
        lambda *a, **k: _FakeResp(
            {"tag_name": "v1.0.0-django", "html_url": "u", "body": "🔴 SECURITY — actualizá"}
        ),
    )
    rc = cli._handle_template_check(_args())
    out = json.loads(capsys.readouterr().out)
    assert rc == 0
    assert "🔴" in out["notes_excerpt"]
