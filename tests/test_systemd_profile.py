"""Smoke tests for scripts/_common.sh systemd-profile resolution.

The profile that the installer picks decides which systemd units are
enabled on a fresh deploy. Item: the default profile
``api-worker-maintenance`` must include the notifier daemon so the
OutboundEmail retry queue actually drains without an operator running
``notify-once`` by hand.
"""
from __future__ import annotations

import subprocess
from pathlib import Path

import pytest


COMMON_SH = Path(__file__).resolve().parents[1] / "scripts" / "_common.sh"


def _resolve(profile: str) -> tuple[list[str], list[str]]:
    """Source _common.sh in a subshell, set the profile, call the
    resolver, and capture the enabled service + timer arrays."""
    script = (
        f"set +eu\n"
        f"APP_SLUG=test APP_ENV=dev\n"
        f"APP_SYSTEMD_PROFILE='{profile}'\n"
        f". '{COMMON_SH}'\n"
        f"UNIT_PREFIX=\"${{APP_SLUG}}-${{APP_ENV}}\"\n"
        f"resolve_systemd_profile\n"
        f"printf 'SERVICES=%s\\n' \"${{ENABLED_SERVICE_UNITS[*]}}\"\n"
        f"printf 'TIMERS=%s\\n' \"${{ENABLED_TIMER_UNITS[*]}}\"\n"
    )
    result = subprocess.run(
        ["bash", "-c", script],
        capture_output=True, text=True, check=True,
    )
    services: list[str] = []
    timers: list[str] = []
    for line in result.stdout.splitlines():
        if line.startswith("SERVICES="):
            services = line.removeprefix("SERVICES=").split()
        elif line.startswith("TIMERS="):
            timers = line.removeprefix("TIMERS=").split()
    return services, timers


@pytest.mark.parametrize(
    "profile",
    ["api-worker-maintenance", "api-web-worker-maintenance", "api-capture-notifier-maintenance"],
)
def test_profile_includes_notifier(profile):
    """Every profile that enables the api must also enable the
    notifier — without it the OutboundEmail retry queue never drains."""
    services, _ = _resolve(profile)
    assert any("notifier" in svc for svc in services), (
        f"profile {profile!r} does not enable the notifier: services={services}"
    )


def test_default_profile_is_api_worker_maintenance():
    """If anyone changes the default in _common.sh, this catches it
    so the operator notices in code review rather than after a deploy."""
    text = COMMON_SH.read_text(encoding="utf-8")
    assert 'APP_SYSTEMD_PROFILE="${APP_SYSTEMD_PROFILE:-api-worker-maintenance}"' in text
