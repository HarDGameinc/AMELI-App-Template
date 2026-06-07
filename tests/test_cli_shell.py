from __future__ import annotations

import pytest

from ameli_app.cli import main


@pytest.fixture()
def example_config_path(tmp_path, monkeypatch):
    # Reuse the bundled example config via the env var consulted by load_settings.
    from tests.conftest import CONFIG_PATH

    return CONFIG_PATH


def test_shell_command_executes_python_snippet(example_config_path, capsys):
    result = main([
        "--config", str(example_config_path),
        "shell", "-c", "print('hello from shell')",
    ])
    captured = capsys.readouterr()

    assert result == 0
    assert "hello from shell" in captured.out


def test_shell_command_can_access_django_models(example_config_path, capsys):
    result = main([
        "--config", str(example_config_path),
        "shell", "-c", "print(User._meta.app_label)",
    ])
    captured = capsys.readouterr()

    assert result == 0
    assert "accounts" in captured.out


def test_shell_command_propagates_runtime_errors(example_config_path):
    with pytest.raises(NameError):
        main([
            "--config", str(example_config_path),
            "shell", "-c", "undefined_symbol_here",
        ])


def test_shell_script_executes_file_when_provided(example_config_path, tmp_path, capsys):
    script = tmp_path / "snippet.py"
    script.write_text("print('script ran:', User.__name__)\n", encoding="utf-8")

    result = main([
        "--config", str(example_config_path),
        "shell", str(script),
    ])
    captured = capsys.readouterr()

    assert result == 0
    assert "script ran: User" in captured.out


def test_shell_script_missing_file_returns_error(example_config_path, tmp_path, capsys):
    result = main([
        "--config", str(example_config_path),
        "shell", str(tmp_path / "does_not_exist.py"),
    ])
    captured = capsys.readouterr()

    assert result == 2
    assert "script not found" in captured.err


def test_shell_namespace_includes_expected_objects(example_config_path, capsys):
    """End-to-end check via -c that the populated namespace works."""
    code_snippet = (
        "available = [User, AuditEvent, UserSession, MFAEmailChallenge, MFARecoveryCode];"
        " print('count:', len(available))"
    )
    result = main([
        "--config", str(example_config_path),
        "shell", "-c", code_snippet,
    ])
    captured = capsys.readouterr()

    assert result == 0
    assert "count: 5" in captured.out
