from __future__ import annotations

from types import SimpleNamespace

import pytest
from django.conf import settings as django_settings
from django.test import override_settings

from ameli_web.accounts.views import _build_public_base_url


class _FakeRequest:
    """Stand-in for an HttpRequest whose Host header would be attacker-controlled."""

    def build_absolute_uri(self, path: str = "/") -> str:
        return f"http://attacker.com{path}"


def _patch_cfg(monkeypatch, *, environment, public_url_base):
    """Swap ``settings.CFG`` with a fake whose two attributes drive the helper."""
    fake_cfg = SimpleNamespace(
        environment=environment,
        public_url_base=public_url_base,
    )
    monkeypatch.setattr(django_settings, "CFG", fake_cfg)
    monkeypatch.setattr(django_settings, "ENV_NAME", environment, raising=False)


@override_settings(DEBUG=True)
def test_dev_falls_back_to_request_host_when_no_public_url_base(monkeypatch):
    _patch_cfg(monkeypatch, environment="dev", public_url_base="")

    result = _build_public_base_url(_FakeRequest())

    # In dev we tolerate the fallback (operator may not have configured it yet).
    assert result == "http://attacker.com"


@override_settings(DEBUG=False)
def test_non_dev_raises_without_public_url_base(monkeypatch):
    _patch_cfg(monkeypatch, environment="prod", public_url_base="")

    with pytest.raises(RuntimeError, match="public_url_base"):
        _build_public_base_url(_FakeRequest())


@override_settings(DEBUG=False)
def test_non_dev_uses_public_url_base_not_host_header(monkeypatch):
    _patch_cfg(monkeypatch, environment="prod",
               public_url_base="https://canonical.example.com")

    result = _build_public_base_url(_FakeRequest())

    assert result == "https://canonical.example.com"


@override_settings(DEBUG=False)
def test_non_dev_strips_trailing_slash(monkeypatch):
    _patch_cfg(monkeypatch, environment="prod",
               public_url_base="https://canonical.example.com/")

    assert _build_public_base_url(_FakeRequest()) == "https://canonical.example.com"
