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
# A software source that cannot be reached must not stop the upgrade.
#
# This is what the helper used to do: `zypper refresh` returned non-zero
# because one third-party source was unreachable, and the whole dup was
# abandoned before it started. zypper itself skips the source and carries on
# from the metadata already on disk, which is what its exit code 106 is for.
# --------------------------------------------------------------------------- #


def _record_runs(monkeypatch, refresh_rc: int, refresh_output: str = ""):
    ran = []
    monkeypatch.setattr(
        helper_run_update,
        "_run_teed",
        lambda argv: (ran.append(argv), (refresh_rc, refresh_output))[1],
    )
    monkeypatch.setattr(helper_run_update, "_run", lambda argv: ran.append(argv) or 0)
    monkeypatch.setattr(helper_run_update, "_missing_sources", lambda out: ["VLC"])
    return ran


def test_an_unreachable_source_does_not_stop_the_upgrade(monkeypatch, capsys):
    # 4 is what zypper returned in the failure this was written for.
    ran = _record_runs(monkeypatch, refresh_rc=4)
    monkeypatch.setattr("sys.argv", ["run-update"])

    assert helper_run_update.main() == 0
    assert ran[0] == ["zypper", "refresh"]
    assert ran[1] == ["zypper", "dup"]
    out = capsys.readouterr().out
    assert "VLC" in out
    assert "Carrying on" in out


def test_repos_skipped_exit_code_also_continues(monkeypatch):
    ran = _record_runs(monkeypatch, refresh_rc=106)
    monkeypatch.setattr("sys.argv", ["run-update"])

    assert helper_run_update.main() == 0
    assert ran[1] == ["zypper", "dup"]


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
    assert ran[1] == ["zypper", "dup"]
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
