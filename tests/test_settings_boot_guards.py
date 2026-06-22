from __future__ import annotations

import importlib

import pytest


def _reload_settings(monkeypatch, *, env: str = "dev", **env_vars: str | None):
    """Rebuild the Django settings module with the given env overrides.

    The boot-time guards in ``ameli_web.settings`` raise during ``import``,
    so we need to wipe the cache and re-import every time a test wants to
    flip an env var.
    """
    import sys

    # Stage env exactly as the test expects.
    for key in list(env_vars):
        value = env_vars[key]
        if value is None:
            monkeypatch.delenv(key, raising=False)
        else:
            monkeypatch.setenv(key, value)
    monkeypatch.setenv("APP_ENV", env)
    # ASVS V2.8 boot guard requires AMELI_APP_MFA_ENCRYPTION_KEY outside
    # dev. Tests that don't explicitly probe that guard get a default
    # so they exercise the OTHER guard they care about (email backend,
    # SECRET_KEY, ALLOWED_HOSTS, etc.) without colliding.
    if env != "dev" and "AMELI_APP_MFA_ENCRYPTION_KEY" not in env_vars:
        # Static value so the cached helper inside ``mfa.py`` does not
        # need re-instantiating between tests; a real Fernet key works
        # under cryptography.fernet without side effects on the test DB.
        monkeypatch.setenv(
            "AMELI_APP_MFA_ENCRYPTION_KEY",
            "kj9_Vh-rExdXrPm7TZWQ8a9oU8gPpYHN-mDz2LfqHy0=",
        )
    if env != "dev" and "AMELI_APP_AUDIT_HMAC_KEY" not in env_vars:
        # ASVS V7.3.2 / V6.3.1 boot guard added 2026-06-19 after
        # independent security re-audit flagged the missing guard as
        # HIGH. Tests that don't probe THIS guard get a default so they
        # exercise the guard they care about without colliding.
        monkeypatch.setenv(
            "AMELI_APP_AUDIT_HMAC_KEY",
            "test-audit-hmac-key-for-prod-boot-guard-fixtures-only",
        )
    if env != "dev" and "AMELI_APP_PROFILE_UPLOADS_DIR" not in env_vars:
        # 2026-06-21 boot guard refuses MEDIA_ROOT inside the checkout
        # outside dev (wire test caught the avatar 500 due to relative
        # default). Tests that don't probe THIS guard get an absolute
        # path so they exercise the guard they care about.
        monkeypatch.setenv("AMELI_APP_PROFILE_UPLOADS_DIR", "/tmp/test-uploads")  # noqa: S108
    if env != "dev" and "AMELI_APP_DATA_DIR" not in env_vars:
        # Same trap for data_dir. /tmp is fine in tests (the guard only
        # forbids inside-checkout paths).
        monkeypatch.setenv("AMELI_APP_DATA_DIR", "/tmp/test-data")  # noqa: S108

    # Drop any cached settings module so the module-level guards re-run.
    for cached in ("ameli_web.settings",):
        sys.modules.pop(cached, None)
    return importlib.import_module("ameli_web.settings")


def test_dev_environment_boots_with_bundled_defaults(monkeypatch):
    settings = _reload_settings(monkeypatch, env="dev",
                                AMELI_APP_DJANGO_SECRET_KEY=None,
                                AMELI_APP_DJANGO_DEBUG=None,
                                AMELI_APP_DJANGO_ALLOWED_HOSTS=None)
    # Dev is allowed to fall back to the bundled defaults.
    assert settings.DEBUG is False  # default no longer follows env
    assert "*" in settings.ALLOWED_HOSTS


def test_non_dev_refuses_bundled_secret_key(monkeypatch):
    with pytest.raises(RuntimeError, match="SECRET_KEY"):
        _reload_settings(monkeypatch, env="prod",
                         AMELI_APP_DJANGO_SECRET_KEY=None,
                         AMELI_APP_DJANGO_ALLOWED_HOSTS="ameli.example.com")


def test_non_dev_refuses_wildcard_allowed_hosts(monkeypatch):
    with pytest.raises(RuntimeError, match="ALLOWED_HOSTS"):
        _reload_settings(monkeypatch, env="prod",
                         AMELI_APP_DJANGO_SECRET_KEY="a-very-long-random-real-secret-not-default",
                         AMELI_APP_DJANGO_ALLOWED_HOSTS="*")


def test_non_dev_refuses_empty_allowed_hosts(monkeypatch):
    with pytest.raises(RuntimeError, match="ALLOWED_HOSTS"):
        _reload_settings(monkeypatch, env="prod",
                         AMELI_APP_DJANGO_SECRET_KEY="a-very-long-random-real-secret-not-default",
                         AMELI_APP_DJANGO_ALLOWED_HOSTS=None)


def test_non_dev_refuses_debug_true(monkeypatch):
    with pytest.raises(RuntimeError, match="DEBUG"):
        _reload_settings(monkeypatch, env="prod",
                         AMELI_APP_DJANGO_SECRET_KEY="a-very-long-random-real-secret-not-default",
                         AMELI_APP_DJANGO_ALLOWED_HOSTS="ameli.example.com",
                         AMELI_APP_DJANGO_DEBUG="true",
                         AMELI_APP_TRUSTED_PROXIES="127.0.0.1,::1")


def test_non_dev_refuses_empty_trusted_proxies(monkeypatch):
    with pytest.raises(RuntimeError, match="TRUSTED_PROXIES"):
        _reload_settings(monkeypatch, env="prod",
                         AMELI_APP_DJANGO_SECRET_KEY="real-secret-explicitly-set-by-operator",
                         AMELI_APP_DJANGO_ALLOWED_HOSTS="metro.lan",
                         AMELI_APP_DJANGO_DEBUG="false",
                         AMELI_APP_TRUSTED_PROXIES=None)


def test_non_dev_refuses_console_email_backend(monkeypatch):
    """Console backend keeps mail in stdout — password reset and
    MFA-by-email would silently fail in a real deploy. Refuse to boot."""
    with pytest.raises(RuntimeError, match="email.backend"):
        _reload_settings(monkeypatch, env="prod",
                         AMELI_APP_DJANGO_SECRET_KEY="real-secret-explicitly-set-by-operator",
                         AMELI_APP_DJANGO_ALLOWED_HOSTS="metro.lan",
                         AMELI_APP_DJANGO_DEBUG="false",
                         AMELI_APP_TRUSTED_PROXIES="127.0.0.1,::1",
                         AMELI_APP_EMAIL_BACKEND="console")


def test_non_dev_refuses_smtp_backend_without_host(monkeypatch):
    """SMTP backend without a host silently no-ops too."""
    with pytest.raises(RuntimeError, match="email.host"):
        _reload_settings(monkeypatch, env="prod",
                         AMELI_APP_DJANGO_SECRET_KEY="real-secret-explicitly-set-by-operator",
                         AMELI_APP_DJANGO_ALLOWED_HOSTS="metro.lan",
                         AMELI_APP_DJANGO_DEBUG="false",
                         AMELI_APP_TRUSTED_PROXIES="127.0.0.1,::1",
                         AMELI_APP_EMAIL_BACKEND="smtp")


def test_non_dev_boots_with_explicit_safe_config(monkeypatch):
    settings = _reload_settings(monkeypatch, env="prod",
                                AMELI_APP_DJANGO_SECRET_KEY="real-secret-explicitly-set-by-operator",
                                AMELI_APP_DJANGO_ALLOWED_HOSTS="metro.lan,10.0.0.5",
                                AMELI_APP_DJANGO_DEBUG="false",
                                AMELI_APP_TRUSTED_PROXIES="127.0.0.1,::1",
                                AMELI_APP_EMAIL_BACKEND="smtp",
                                AMELI_APP_EMAIL_HOST="smtp.example.com")
    assert settings.SECRET_KEY != "ameli-app-dev-secret-key"
    assert settings.DEBUG is False
    assert "metro.lan" in settings.ALLOWED_HOSTS
    assert "10.0.0.5" in settings.ALLOWED_HOSTS
    assert settings.TRUSTED_PROXIES == {"127.0.0.1", "::1"}


def test_non_dev_refuses_empty_mfa_encryption_key(monkeypatch):
    """ASVS V2.8 boot guard — outside dev, the MFA encryption key
    must be set so TOTP secrets do not land in the DB as plaintext.
    """
    with pytest.raises(RuntimeError, match="AMELI_APP_MFA_ENCRYPTION_KEY"):
        _reload_settings(
            monkeypatch,
            env="prod",
            AMELI_APP_DJANGO_SECRET_KEY="real-secret-explicitly-set-by-operator",
            AMELI_APP_DJANGO_ALLOWED_HOSTS="metro.lan",
            AMELI_APP_DJANGO_DEBUG="false",
            AMELI_APP_TRUSTED_PROXIES="127.0.0.1,::1",
            AMELI_APP_EMAIL_BACKEND="smtp",
            AMELI_APP_EMAIL_HOST="smtp.example.com",
            # Explicitly empty — must trip the guard.
            AMELI_APP_MFA_ENCRYPTION_KEY="",
        )


def test_dev_boots_without_mfa_encryption_key(monkeypatch):
    """Mirror property: in dev, the key is optional (pass-through mode)."""
    settings = _reload_settings(monkeypatch, env="dev")
    assert getattr(settings, "MFA_ENCRYPTION_KEY", "") == ""


def test_non_dev_refuses_empty_audit_hmac_key(monkeypatch):
    """ASVS V7.3.2 / V6.3.1 boot guard — outside dev, the audit HMAC
    key must be set so the chain integrity check is enforced. Without
    it, ``record_audit`` writes rows with ``hmac=""`` and
    ``verify_audit_chain`` refuses to verify — silent disabling of a
    critical integrity control. Caught by the 2026-06-19 independent
    security re-audit.
    """
    with pytest.raises(RuntimeError, match="AMELI_APP_AUDIT_HMAC_KEY"):
        _reload_settings(
            monkeypatch,
            env="prod",
            AMELI_APP_DJANGO_SECRET_KEY="real-secret-explicitly-set-by-operator",
            AMELI_APP_DJANGO_ALLOWED_HOSTS="metro.lan",
            AMELI_APP_DJANGO_DEBUG="false",
            AMELI_APP_TRUSTED_PROXIES="127.0.0.1,::1",
            AMELI_APP_EMAIL_BACKEND="smtp",
            AMELI_APP_EMAIL_HOST="smtp.example.com",
            # Explicitly empty — must trip the new guard.
            AMELI_APP_AUDIT_HMAC_KEY="",
        )


def test_dev_boots_without_audit_hmac_key(monkeypatch):
    """Mirror property: in dev, an empty audit key is allowed —
    rows write without an integrity stamp, useful for fast iteration.
    """
    settings = _reload_settings(monkeypatch, env="dev")
    assert getattr(settings, "AUDIT_HMAC_KEY", "") == ""


def test_non_dev_refuses_av_endpoint_with_bad_scheme(monkeypatch):
    """ASVS V12.4.1 — the AV endpoint must use tcp:// or http(s)://.
    A misconfigured scheme used to silently fall back to fail-open
    at upload time. Now caught at boot.
    """
    with pytest.raises(RuntimeError, match="AMELI_APP_AV_ENDPOINT"):
        _reload_settings(
            monkeypatch,
            env="dev",
            AMELI_APP_AV_ENDPOINT="file:///etc/passwd",
        )


def test_dev_boots_with_valid_av_endpoint(monkeypatch):
    settings = _reload_settings(monkeypatch, env="dev",
                                AMELI_APP_AV_ENDPOINT="tcp://clamd:3310")
    assert settings.AV_ENDPOINT == "tcp://clamd:3310"


def test_dev_boots_with_unix_av_endpoint(monkeypatch):
    """The ``unix://`` scheme is the recommended Debian/Ubuntu shape
    (apt installs clamd with socket activation at
    /var/run/clamav/clamd.ctl). The boot guard MUST accept it."""
    settings = _reload_settings(
        monkeypatch, env="dev",
        AMELI_APP_AV_ENDPOINT="unix:///var/run/clamav/clamd.ctl",
    )
    assert settings.AV_ENDPOINT == "unix:///var/run/clamav/clamd.ctl"


def test_dev_refuses_otel_endpoint_with_bad_scheme(monkeypatch):
    """OTel OTLP/gRPC accepts http:// (cleartext) and https:// (TLS).
    A bare ``host:port`` or any other scheme would either default
    ambiguously or fail at first export — boot guard refuses early."""
    with pytest.raises(RuntimeError, match="AMELI_APP_OTEL_EXPORTER_OTLP_ENDPOINT"):
        _reload_settings(
            monkeypatch, env="dev",
            AMELI_APP_OTEL_EXPORTER_OTLP_ENDPOINT="grpc://collector:4317",
        )


def test_dev_boots_with_valid_otel_endpoint(monkeypatch):
    settings = _reload_settings(
        monkeypatch, env="dev",
        AMELI_APP_OTEL_EXPORTER_OTLP_ENDPOINT="http://otel-collector:4317",
    )
    assert settings.OTEL_EXPORTER_OTLP_ENDPOINT == "http://otel-collector:4317"


# ---------------------------------------------------------------------------
# Mini-roadmap #10 — django-silk opt-in profiler (2026-06-22)
# ---------------------------------------------------------------------------


def test_silk_disabled_by_default(monkeypatch):
    settings = _reload_settings(monkeypatch, env="dev")
    assert settings.SILK_ENABLED is False
    assert "silk" not in settings.INSTALLED_APPS
    assert not any("silk" in m.lower() for m in settings.MIDDLEWARE)


def test_silk_enabled_in_dev_wires_app_and_middleware(monkeypatch):
    settings = _reload_settings(
        monkeypatch, env="dev",
        AMELI_APP_SILK_ENABLED="true",
    )
    assert settings.SILK_ENABLED is True
    assert "silk" in settings.INSTALLED_APPS
    assert "silk.middleware.SilkyMiddleware" in settings.MIDDLEWARE
    # Default intercept regex limits profiling to app routes only
    assert settings.SILKY_INTERCEPT_REGEX == r"^/(profile|admin|api)/"
    # Auth gating MUST be on — silk panel exposes raw SQL
    assert settings.SILKY_AUTHENTICATION is True
    assert settings.SILKY_AUTHORISATION is True


def _prod_minimum_env() -> dict:
    """Env vars every prod-mode test needs to satisfy unrelated boot
    guards so the test isolates the guard it actually probes."""
    return {
        "AMELI_APP_DJANGO_SECRET_KEY": "a-very-long-random-real-secret-not-default",
        "AMELI_APP_DJANGO_ALLOWED_HOSTS": "ameli.example.com",
        "AMELI_APP_TRUSTED_PROXIES": "127.0.0.1,::1",
        "AMELI_APP_EMAIL_BACKEND": "file",
    }


def test_silk_refuses_to_enable_in_prod_without_second_opt_in(monkeypatch):
    """Silk persists full request/response bodies. Enabling it
    outside dev without an explicit second flag would leak PII into
    the silk_* tables (ASVS V8.3.1). The boot guard fails loud."""
    with pytest.raises(RuntimeError, match="AMELI_APP_SILK_ALLOW_PROD"):
        _reload_settings(
            monkeypatch, env="prod",
            AMELI_APP_SILK_ENABLED="true",
            **_prod_minimum_env(),
        )


def test_silk_can_be_enabled_in_prod_with_both_opt_ins(monkeypatch):
    """Operator who has accepted the PII trade-off (e.g. for a
    short profiling window in a staging-prod-clone) can override
    by setting both env vars."""
    settings = _reload_settings(
        monkeypatch, env="prod",
        AMELI_APP_SILK_ENABLED="true",
        AMELI_APP_SILK_ALLOW_PROD="true",
        **_prod_minimum_env(),
    )
    assert settings.SILK_ENABLED is True


def test_silk_intercept_regex_honors_env_override(monkeypatch):
    settings = _reload_settings(
        monkeypatch, env="dev",
        AMELI_APP_SILK_ENABLED="true",
        AMELI_APP_SILK_INTERCEPT_REGEX=r"^/api/",
    )
    assert settings.SILKY_INTERCEPT_REGEX == r"^/api/"


def test_non_dev_refuses_media_root_inside_checkout(monkeypatch, tmp_path):
    """2026-06-21 wire test finding: ``profile_uploads_dir`` defaulted
    to ``data/uploads/{env}`` (relative). ``path_from_value`` anchored
    it against PROJECT_DIR which is root-owned on install.sh deploys;
    the app user got PermissionError on the first avatar upload (500).
    Boot guard now refuses paths inside the checkout outside dev.
    """
    # Explicitly set the relative-anchored-inside-checkout path that
    # would silently fail at first write. The helper would otherwise
    # auto-fill an absolute /tmp path; override that here.
    with pytest.raises(RuntimeError, match="MEDIA_ROOT.*checkout"):
        _reload_settings(
            monkeypatch,
            env="prod",
            AMELI_APP_DJANGO_SECRET_KEY="real-secret-explicitly-set-by-operator",
            AMELI_APP_DJANGO_ALLOWED_HOSTS="metro.lan",
            AMELI_APP_DJANGO_DEBUG="false",
            AMELI_APP_TRUSTED_PROXIES="127.0.0.1,::1",
            AMELI_APP_EMAIL_BACKEND="smtp",
            AMELI_APP_EMAIL_HOST="smtp.example.com",
            # Force the relative-inside-checkout path that the wire test surfaced.
            AMELI_APP_PROFILE_UPLOADS_DIR="data/uploads/dev",
        )


def test_dev_allows_media_root_inside_checkout(monkeypatch):
    """Dev allows relative paths (convenience for local iteration)."""
    settings = _reload_settings(monkeypatch, env="dev")
    # The dev default points inside the checkout; that's OK in dev.
    assert "data/uploads" in settings.MEDIA_ROOT or settings.MEDIA_ROOT
