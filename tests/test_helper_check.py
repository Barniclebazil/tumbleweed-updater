"""Tests for helper/check's zypp-lock retry loop.

helper/check is an extensionless script (not a package module), so it is
loaded directly via importlib rather than a normal import.
"""

import importlib.machinery
import importlib.util
import subprocess
from pathlib import Path

import pytest

from tumbleweed_updater import sources

REPO_ROOT = Path(__file__).resolve().parent.parent
_loader = importlib.machinery.SourceFileLoader(
    "helper_check", str(REPO_ROOT / "helper" / "check")
)
_spec = importlib.util.spec_from_loader("helper_check", _loader)
helper_check = importlib.util.module_from_spec(_spec)
_loader.exec_module(helper_check)


def test_refresh_reports_locked_on_exit_code_7(monkeypatch):
    def fake_run(*args, **kwargs):
        return subprocess.CompletedProcess(
            args,
            returncode=sources.ZYPPER_EXIT_ZYPP_LOCKED,
            stdout="",
            stderr="System management is locked by the application with pid 5899.",
        )

    monkeypatch.setattr(helper_check.subprocess, "run", fake_run)
    error, locked = helper_check._refresh()
    assert locked is True
    assert "locked" in error.lower()


def test_refresh_preserves_multiline_message(monkeypatch):
    def fake_run(*args, **kwargs):
        return subprocess.CompletedProcess(
            args, returncode=6, stdout="", stderr="line one\nline two"
        )

    monkeypatch.setattr(helper_check.subprocess, "run", fake_run)
    error, locked = helper_check._refresh()
    assert locked is False
    assert "line one" in error and "line two" in error


def test_main_retries_then_succeeds(monkeypatch):
    calls = {"n": 0}

    def fake_refresh():
        calls["n"] += 1
        if calls["n"] < 2:
            return "System management is locked...", True
        return None, False

    results = iter(
        [
            sources.ZypperResult(error="System management is locked...", locked=True),
            sources.ZypperResult(),
        ]
    )

    monkeypatch.setattr(helper_check, "_refresh", fake_refresh)
    monkeypatch.setattr(helper_check.sources, "check_zypper", lambda: next(results))
    monkeypatch.setattr(helper_check, "_snapshots_ok", lambda: True)
    monkeypatch.setattr(helper_check.time, "sleep", lambda s: None)
    written = {}
    monkeypatch.setattr(
        helper_check.statusfile, "write", lambda status: written.setdefault("status", status)
    )

    assert helper_check.main() == 0
    assert written["status"].zypper.error is None


def test_main_gives_up_after_max_attempts(monkeypatch):
    monkeypatch.setattr(helper_check, "_refresh", lambda: ("locked", True))
    monkeypatch.setattr(
        helper_check.sources,
        "check_zypper",
        lambda: sources.ZypperResult(
            error="System management is locked by pid 5899", locked=True
        ),
    )
    monkeypatch.setattr(helper_check, "_snapshots_ok", lambda: True)
    monkeypatch.setattr(helper_check.time, "sleep", lambda s: None)
    written = {}
    monkeypatch.setattr(
        helper_check.statusfile, "write", lambda status: written.setdefault("status", status)
    )

    assert helper_check.main() == 0
    err = written["status"].zypper.error
    assert "3 automatic" in err
    assert "pid 5899" in err


def test_main_does_not_retry_non_lock_errors(monkeypatch):
    calls = {"n": 0}

    def fake_refresh():
        calls["n"] += 1
        return None, False

    monkeypatch.setattr(helper_check, "_refresh", fake_refresh)
    monkeypatch.setattr(
        helper_check.sources,
        "check_zypper",
        lambda: sources.ZypperResult(error="Repository 'foo' is invalid.", locked=False),
    )
    monkeypatch.setattr(helper_check, "_snapshots_ok", lambda: True)
    monkeypatch.setattr(
        helper_check.time, "sleep", lambda s: pytest.fail("should not sleep/retry")
    )
    monkeypatch.setattr(helper_check.statusfile, "write", lambda status: None)

    helper_check.main()
    assert calls["n"] == 1
