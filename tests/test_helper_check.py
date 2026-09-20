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


@pytest.fixture
def main_env(monkeypatch):
    """Isolate main(): no real argv, no real PackageKit, no real status file."""
    monkeypatch.setattr(helper_check.sys, "argv", ["check"])
    wait_calls = {"n": 0}

    def fake_wait(*args, **kwargs):
        wait_calls["n"] += 1
        return True, "the package lock is free"

    monkeypatch.setattr(helper_check.packagekit, "wait_for_lock", fake_wait)
    monkeypatch.setattr(helper_check, "_snapshots_ok", lambda: True)
    # Would otherwise shell out to `zypper repos`. The tests that care about it
    # override this again.
    monkeypatch.setattr(helper_check, "_failed_sources", lambda output: [])
    monkeypatch.setattr(helper_check.time, "sleep", lambda s: None)
    # Would otherwise look for the real note under /var/lib. The ordering test
    # below overrides this again.
    order = []
    monkeypatch.setattr(
        helper_check.repos,
        "restore_remembered",
        lambda *a, **k: order.append("restore") or [],
    )
    written = {}
    monkeypatch.setattr(
        helper_check.statusfile,
        "write",
        lambda status: written.__setitem__("status", status),
    )
    return {"written": written, "waits": wait_calls, "order": order}


def test_refresh_reports_locked_on_exit_code_7(monkeypatch):
    def fake_run(*args, **kwargs):
        return subprocess.CompletedProcess(
            args,
            returncode=sources.ZYPPER_EXIT_ZYPP_LOCKED,
            stdout="",
            stderr="System management is locked by the application with pid 5899.",
        )

    monkeypatch.setattr(helper_check.subprocess, "run", fake_run)
    error, locked, _output = helper_check._refresh()
    assert locked is True
    assert "locked" in error.lower()


def test_refresh_preserves_multiline_message(monkeypatch):
    def fake_run(*args, **kwargs):
        return subprocess.CompletedProcess(
            args, returncode=6, stdout="", stderr="line one\nline two"
        )

    monkeypatch.setattr(helper_check.subprocess, "run", fake_run)
    error, locked, _output = helper_check._refresh()
    assert locked is False
    assert "line one" in error and "line two" in error


def test_main_retries_then_succeeds(monkeypatch, main_env):
    calls = {"n": 0}

    def fake_refresh():
        calls["n"] += 1
        if calls["n"] < 2:
            return "System management is locked...", True, ""
        return None, False, ""

    results = iter(
        [
            sources.ZypperResult(error="System management is locked...", locked=True),
            sources.ZypperResult(),
        ]
    )

    monkeypatch.setattr(helper_check, "_refresh", fake_refresh)
    monkeypatch.setattr(helper_check.sources, "check_zypper", lambda: next(results))

    assert helper_check.main() == 0
    status = main_env["written"]["status"]
    assert status.zypper.error is None
    assert status.zypper.locked is False
    # Once per attempt, not once overall: PackageKit can be woken again in
    # between by whatever woke it the first time.
    assert main_env["waits"]["n"] == 2


def _always_locked(monkeypatch):
    monkeypatch.setattr(helper_check, "_refresh", lambda: ("locked", True, ""))
    monkeypatch.setattr(
        helper_check.sources,
        "check_zypper",
        lambda: sources.ZypperResult(
            error="System management is locked by pid 5899", locked=True
        ),
    )


def test_main_gives_up_after_max_attempts(monkeypatch, main_env):
    _always_locked(monkeypatch)

    assert helper_check.main() == 0
    status = main_env["written"]["status"]
    assert "5 automatic" in status.zypper.error
    assert "pid 5899" in status.zypper.error
    # The GUI needs this to know it may offer to free the lock.
    assert status.zypper.locked is True
    assert main_env["waits"]["n"] == helper_check._LOCK_MAX_ATTEMPTS


def test_no_wait_flag_suppresses_the_wait(monkeypatch, main_env):
    _always_locked(monkeypatch)
    monkeypatch.setattr(
        helper_check.sys, "argv", ["check", "--no-wait-for-packagekit"]
    )

    assert helper_check.main() == 0
    assert main_env["waits"]["n"] == 0


def test_main_refuses_an_unknown_argument(monkeypatch, main_env, capsys):
    # polkit pins the path of this helper but never its argv, so anything
    # unrecognised is rejected rather than passed on.
    monkeypatch.setattr(helper_check.sys, "argv", ["check", "--sneaky"])

    assert helper_check.main() == 2
    assert "--sneaky" in capsys.readouterr().err
    assert "status" not in main_env["written"]


def test_main_does_not_retry_non_lock_errors(monkeypatch, main_env):
    calls = {"n": 0}

    def fake_refresh():
        calls["n"] += 1
        return None, False, ""

    monkeypatch.setattr(helper_check, "_refresh", fake_refresh)
    monkeypatch.setattr(
        helper_check.sources,
        "check_zypper",
        lambda: sources.ZypperResult(error="Repository 'foo' is invalid.", locked=False),
    )
    monkeypatch.setattr(
        helper_check.time, "sleep", lambda s: pytest.fail("should not sleep/retry")
    )

    helper_check.main()
    assert calls["n"] == 1
    assert main_env["written"]["status"].zypper.locked is False


# --------------------------------------------------------------------------- #
# Software sources that could not be reached.
#
# The refresh error used to be thrown away whenever the dry run still found
# packages, which is exactly the case the window most needs to warn about: 43
# updates listed, and no hint that one source was missing from them.
# --------------------------------------------------------------------------- #


def test_a_source_that_could_not_be_reached_is_recorded(monkeypatch, main_env):
    monkeypatch.setattr(
        helper_check, "_refresh", lambda: ("Repository 'VLC' is invalid.", False, "out")
    )
    monkeypatch.setattr(helper_check, "_failed_sources", lambda output: [("vlc", "VLC")])
    monkeypatch.setattr(
        helper_check.sources,
        "check_zypper",
        lambda: sources.ZypperResult(
            packages=[sources.Package(name="bash", action=sources.Action.UPGRADE)]
        ),
    )

    assert helper_check.main() == 0
    status = main_env["written"]["status"]
    assert status.zypper.failed_repos == [("vlc", "VLC")]
    # Not an error: the upgrade can still go ahead without that source, and the
    # window says so in its own words.
    assert status.zypper.error is None


def test_nothing_is_recorded_when_the_refresh_worked(monkeypatch, main_env):
    monkeypatch.setattr(helper_check, "_refresh", lambda: (None, False, "all fine"))
    monkeypatch.setattr(
        helper_check.sources, "check_zypper", lambda: sources.ZypperResult()
    )

    assert helper_check.main() == 0
    assert main_env["written"]["status"].zypper.failed_repos == []


def test_a_lock_is_not_reported_as_an_unreachable_source(monkeypatch, main_env):
    """A held lock fails the refresh too, but nothing was unreachable and the
    window has its own retry button for that case."""
    _always_locked(monkeypatch)
    monkeypatch.setattr(
        helper_check,
        "_failed_sources",
        lambda output: pytest.fail("should not look for sources while locked"),
    )

    assert helper_check.main() == 0
    status = main_env["written"]["status"]
    assert status.zypper.locked is True
    assert status.zypper.failed_repos == []


def test_failed_sources_only_trusts_aliases_zypper_knows(monkeypatch):
    """_failed_sources maps the output back through the real source list, so a
    name scraped out of a log line can never reach helper/repos on its own."""
    monkeypatch.setattr(
        helper_check.repos,
        "list_repos",
        lambda: helper_check.repos.ReposResult(
            repos=[helper_check.repos.Repo(alias="vlc", name="VLC")]
        ),
    )
    out = "[vlc|http://example.invalid/] Failed to retrieve new repository metadata.\n"
    assert helper_check._failed_sources(out) == [("vlc", "VLC")]

    other = "[ghost|http://example.invalid/] Failed to retrieve new repository metadata.\n"
    assert helper_check._failed_sources(other) == []


def test_failed_sources_gives_up_quietly_when_the_list_is_unreadable(monkeypatch):
    monkeypatch.setattr(
        helper_check.repos,
        "list_repos",
        lambda: helper_check.repos.ReposResult(error="zypper is not installed"),
    )
    assert helper_check._failed_sources("[vlc|http://x/] Failed") == []


def test_a_source_left_off_by_an_interrupted_upgrade_is_put_back_first(
    monkeypatch, main_env
):
    """helper/run-update switches an unreachable source off for the length of
    one upgrade. A power cut in the middle would leave it off for good, so the
    next check finishes the job - and does it before the refresh, or the
    refresh would report on the wrong set of sources."""
    order = main_env["order"]
    monkeypatch.setattr(
        helper_check,
        "_refresh",
        lambda: (order.append("refresh"), (None, False, ""))[1],
    )
    monkeypatch.setattr(
        helper_check.sources, "check_zypper", lambda: sources.ZypperResult()
    )

    assert helper_check.main() == 0
    assert order == ["restore", "refresh"]
