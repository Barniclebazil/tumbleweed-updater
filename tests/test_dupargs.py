"""The allow-list that helper/run-update checks its arguments against.

polkit matches only the path of the helper, never its arguments, and the update
action keeps its authorisation cached for a few minutes, so anything outside
this list must be refused before zypper sees it.
"""

import importlib.machinery
import importlib.util
from pathlib import Path

from tumbleweed_updater import dupargs

REPO_ROOT = Path(__file__).resolve().parent.parent
_loader = importlib.machinery.SourceFileLoader(
    "helper_run_update", str(REPO_ROOT / "helper" / "run-update")
)
_spec = importlib.util.spec_from_loader("helper_run_update", _loader)
helper_run_update = importlib.util.module_from_spec(_spec)
_loader.exec_module(helper_run_update)


def test_everything_the_settings_dialog_can_produce_is_allowed():
    from tumbleweed_updater.settings import Prefs, dup_args_from_prefs

    every_toggle = Prefs(
        dup_non_interactive=True,
        dup_allow_vendor_change=True,
        dup_download_in_advance=True,
    )
    assert dupargs.unknown_args(dup_args_from_prefs(every_toggle)) == []


def test_an_option_taking_a_path_is_refused():
    assert dupargs.unknown_args(["--root", "/"]) == ["--root", "/"]
    assert dupargs.unknown_args(["--download", "/tmp/evil"]) == ["/tmp/evil"]


def test_the_joined_spelling_of_a_valued_option_is_accepted():
    assert dupargs.unknown_args(["--download=in-advance"]) == []
    assert dupargs.unknown_args(["--download=/tmp"]) == ["--download=/tmp"]


def test_a_valued_option_with_nothing_after_it_is_refused():
    assert dupargs.unknown_args(["--download"]) == ["(missing value)"]


def test_helper_refuses_a_rejected_option_before_running_zypper(monkeypatch, capsys):
    ran = []
    monkeypatch.setattr(helper_run_update, "_run", lambda argv: ran.append(argv) or 0)
    monkeypatch.setattr("sys.argv", ["run-update", "--cleanup", "--root", "/"])

    assert helper_run_update.main() == 2
    assert ran == []
    assert "--root" in capsys.readouterr().err


def test_helper_passes_allowed_options_through(monkeypatch):
    ran = []
    monkeypatch.setattr(helper_run_update, "_run", lambda argv: ran.append(argv) or 0)
    # The refresh goes through _run_teed, which echoes zypper's output as it
    # arrives and keeps a copy for naming unreachable sources.
    monkeypatch.setattr(
        helper_run_update, "_run_teed", lambda argv: (ran.append(argv), (0, ""))[1]
    )
    monkeypatch.setattr(
        "sys.argv", ["run-update", "--cleanup", "-y", "--download", "in-advance"]
    )

    assert helper_run_update.main() == 0
    assert ran[0] == ["zypper", "refresh"]
    assert ran[1] == ["zypper", "dup", "-y", "--download", "in-advance"]
    assert ran[2] == ["zypper", "clean"]


def test_helper_treats_reboot_and_restart_exits_as_success(monkeypatch):
    monkeypatch.setattr(helper_run_update, "_run_teed", lambda argv: (0, ""))
    monkeypatch.setattr(helper_run_update, "_run", lambda argv: 102)
    monkeypatch.setattr("sys.argv", ["run-update"])
    assert helper_run_update.main() == 0


# --------------------------------------------------------------------------- #
# A software source that cannot be reached must not stop the upgrade *here*.
#
# `zypper dup` refuses to run when a repository fails to refresh during its own
# run - measured, exit 4, "dist-upgrade ... must not continue if enabled
# repositories fail to refresh". The helper therefore refreshes first itself
# and then, if anything could not be reached, runs the dup with --no-refresh:
# everything reachable is fresh from a moment ago, the missing source is
# described by what is already on disk, and there is no failed refresh in the
# dup's run for it to refuse over.
# --------------------------------------------------------------------------- #


def _record_runs(monkeypatch, refresh_rc: int, refresh_output: str = "", dup_rc=0):
    ran = []
    monkeypatch.setattr(
        helper_run_update,
        "_run_teed",
        lambda argv: (ran.append(argv), (refresh_rc, refresh_output))[1],
    )
    monkeypatch.setattr(
        helper_run_update, "_run", lambda argv: ran.append(argv) or dup_rc
    )
    monkeypatch.setattr(helper_run_update, "_missing_sources", lambda out: ["VLC"])
    return ran


def test_an_unreachable_source_makes_the_dup_skip_its_own_refresh(
    monkeypatch, capsys
):
    """The whole fix, in one assertion. 4 is what zypper returned in the
    failure this was written for."""
    ran = _record_runs(monkeypatch, refresh_rc=4)
    monkeypatch.setattr("sys.argv", ["run-update", "-y"])

    assert helper_run_update.main() == 0
    assert ran[0] == ["zypper", "refresh"]
    assert ran[1] == ["zypper", "--no-refresh", "dup", "-y"]
    out = capsys.readouterr().out
    assert "VLC" in out
    assert "details already on this computer" in out


def test_a_refresh_that_worked_leaves_the_dup_to_refresh_for_itself(
    monkeypatch
):
    """--no-refresh is for getting past a source that is not there. With
    everything reachable, zypper keeps its own safety net."""
    ran = _record_runs(monkeypatch, refresh_rc=0)
    monkeypatch.setattr("sys.argv", ["run-update", "-y"])

    assert helper_run_update.main() == 0
    assert ran[1] == ["zypper", "dup", "-y"]


def test_a_dup_refused_over_the_missing_source_is_explained(monkeypatch, capsys):
    """Reached only when --no-refresh was not enough either, which means the
    details on disk have gone stale too. Nothing in the window will fix that,
    so the last word is about the source itself."""
    _record_runs(monkeypatch, refresh_rc=4, dup_rc=4)
    monkeypatch.setattr("sys.argv", ["run-update"])

    assert helper_run_update.main() == 4
    out = capsys.readouterr().out
    assert "VLC" in out
    assert "replacing or removing" in out
    for jargon in ("repository", "metadata", "exit"):
        assert jargon not in out.lower(), jargon


def test_a_dup_that_fails_on_its_own_says_nothing_about_sources(
    monkeypatch, capsys
):
    """No source went missing, so the failure is not blamed on one."""
    _record_runs(monkeypatch, refresh_rc=0, dup_rc=4)
    monkeypatch.setattr("sys.argv", ["run-update"])

    assert helper_run_update.main() == 4
    assert "VLC" not in capsys.readouterr().out


def test_repos_skipped_exit_code_also_continues(monkeypatch):
    ran = _record_runs(monkeypatch, refresh_rc=106)
    monkeypatch.setattr("sys.argv", ["run-update"])

    assert helper_run_update.main() == 0
    assert ran[1] == ["zypper", "--no-refresh", "dup"]


def test_a_held_package_lock_still_stops_the_upgrade(monkeypatch):
    """The one refresh failure that is still fatal: if the lock is held, the
    dup cannot run either, so there is nothing to carry on with."""
    ran = _record_runs(monkeypatch, refresh_rc=7)
    monkeypatch.setattr("sys.argv", ["run-update"])

    assert helper_run_update.main() == 7
    assert ran == [["zypper", "refresh"]]


def test_the_warning_is_generic_when_no_source_can_be_named(monkeypatch, capsys):
    ran = _record_runs(monkeypatch, refresh_rc=4)
    monkeypatch.setattr(helper_run_update, "_missing_sources", lambda out: [])
    monkeypatch.setattr("sys.argv", ["run-update"])

    assert helper_run_update.main() == 0
    assert ran[1] == ["zypper", "--no-refresh", "dup"]
    assert "some of your software sources" in capsys.readouterr().out.lower()


def test_the_refresh_still_runs_on_a_terminal():
    """Capturing the refresh output must not cost zypper its terminal.

    On a plain pipe zypper drops its colour and progress line, and worse, a
    prompt that ends without a newline (the GPG key question a refresh can
    raise) would sit in the buffer unseen while the app looked hung.
    """
    rc, output = helper_run_update._run_teed(
        ["/bin/sh", "-c", "test -t 1 && echo yes || echo no"]
    )
    assert rc == 0
    assert output.strip() == "yes"


def test_the_refresh_output_is_captured_without_waiting_for_a_newline():
    rc, output = helper_run_update._run_teed(
        ["/bin/sh", "-c", "printf 'trust always? [r/t/a]: '; exit 4"]
    )
    assert rc == 4
    assert "trust always?" in output


def test_a_missing_zypper_does_not_raise_out_of_the_refresh():
    rc, output = helper_run_update._run_teed(["/definitely/not/here"])
    assert rc == 127
    assert output == ""


def test_the_helpers_own_option_is_stripped_before_the_allow_list():
    mine, rest = helper_run_update._split_own_options(["--cleanup", "-y"])
    assert mine == {"--cleanup"}
    assert rest == ["-y"]


def test_the_flag_that_used_to_skip_the_packagekit_wait_is_now_refused(
    monkeypatch, capsys
):
    """Waiting is what this helper does; there is no option that says
    otherwise, so the allow-list turns it down like any other stranger."""
    monkeypatch.setattr("sys.argv", ["run-update", "--no-wait-for-packagekit"])
    assert helper_run_update.main() == 2
    assert "--no-wait-for-packagekit" in capsys.readouterr().err


def test_an_option_of_ours_after_a_dup_option_is_left_for_the_allow_list():
    """They are stripped only while they lead, so a later one is not silently
    honoured. dupargs then refuses it, which is the safe answer."""
    mine, rest = helper_run_update._split_own_options(["-y", "--cleanup"])
    assert mine == set()
    assert rest == ["-y", "--cleanup"]


def test_the_removed_leave_it_out_option_is_refused_like_any_other(
    monkeypatch, capsys
):
    """--without-unreachable used to switch the unreachable source off for the
    length of the upgrade. It could not work - a source zypper has no usable
    details for is already equivalent to a disabled one, so switching it off
    only orphans everything installed from it - and it is gone. It must now
    fail the allow-list rather than being quietly ignored."""
    monkeypatch.setattr("sys.argv", ["run-update", "--without-unreachable"])
    assert helper_run_update.main() == 2
    assert "--without-unreachable" in capsys.readouterr().err


def test_the_upgrade_waits_for_this_apps_own_check(monkeypatch):
    """Our check's zypper is what lands in /run/zypp.pid, so without being
    told, wait_for_lock() reads it as a stranger's and gives up at once. The
    two then wreck each other's runs - see tests/test_packagekit.py."""
    seen = {}
    monkeypatch.setattr(
        helper_run_update.packagekit, "lock_holder", lambda: (38917, "zypper")
    )
    monkeypatch.setattr(
        helper_run_update.packagekit,
        "holder_is_ours",
        lambda holder, paths, *a, **k: True,
    )
    monkeypatch.setattr(
        helper_run_update.packagekit,
        "describe_holder",
        lambda holder, ours=(), *a, **k: "held by our check",
    )

    def fake_wait(**kwargs):
        seen["ours"] = kwargs.get("ours")
        return True, "released"

    monkeypatch.setattr(helper_run_update.packagekit, "wait_for_lock", fake_wait)
    _record_runs(monkeypatch, refresh_rc=0)
    monkeypatch.setattr("sys.argv", ["run-update"])

    assert helper_run_update.main() == 0
    assert any("check" in p for p in seen["ours"]), seen["ours"]


def test_the_check_helper_path_covers_installed_and_checkout():
    """The GUI may be running from a checkout while this helper is the
    installed copy, or the other way round."""
    assert helper_run_update._OUR_CHECK
    assert all(p.endswith("check") for p in helper_run_update._OUR_CHECK)
