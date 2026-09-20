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
# This is what the helper used to do: `zypper refresh` returned non-zero
# because one third-party source was unreachable, and the whole dup was
# abandoned before it started. zypper itself skips the source and carries on
# from the metadata already on disk, which is what its exit code 106 is for.
#
# Whether the dup then succeeds is zypper's decision. Measured against a real
# unreachable source: with usable metadata still on disk it upgrades normally,
# and with none it refuses ("dist-upgrade ... must not continue if enabled
# repositories fail to refresh"), exit 4. So the helper always tries, and
# explains the refusal in plain words if one comes back.
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
    monkeypatch.setattr(
        helper_run_update, "_missing_sources", lambda out: [("vlc", "VLC")]
    )
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
    assert "Trying the upgrade anyway" in out
    # Nothing is promised about the outcome: that is zypper's to decide.
    assert "can still be installed" not in out


def test_a_dup_refused_over_the_missing_source_is_explained(monkeypatch, capsys):
    """zypper's own refusal is a paragraph about orphaned packages and
    repository setup. The last word here is what to do about it."""
    _record_runs(monkeypatch, refresh_rc=4, dup_rc=4)
    monkeypatch.setattr("sys.argv", ["run-update"])

    assert helper_run_update.main() == 4
    out = capsys.readouterr().out
    assert "Switch VLC off" in out
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


# --------------------------------------------------------------------------- #
# --without-unreachable: switch the source off, upgrade, switch it back on.
#
# The temporary part is the point. What the user agreed to is one upgrade, not
# a change to their machine, so every ending has to put the source back.
# --------------------------------------------------------------------------- #


def test_the_helpers_own_options_parse_in_any_order():
    for order in (
        ["--cleanup", "--no-wait-for-packagekit", "--without-unreachable"],
        ["--without-unreachable", "--cleanup"],
        ["--no-wait-for-packagekit", "--without-unreachable", "--cleanup"],
    ):
        mine, rest = helper_run_update._split_own_options(order + ["-y"])
        assert mine == set(order)
        assert rest == ["-y"]


def test_an_option_of_ours_after_a_dup_option_is_left_for_the_allow_list():
    """They are stripped only while they lead, so a later one is not silently
    honoured. dupargs then refuses it, which is the safe answer."""
    mine, rest = helper_run_update._split_own_options(["-y", "--cleanup"])
    assert mine == set()
    assert rest == ["-y", "--cleanup"]


class _Sources:
    """Stands in for the two dry runs _upgrade_without() relies on."""

    def __init__(self, before, after):
        self.before = before
        self.after = after
        self.calls = 0

    def __call__(self, *a, **k):
        from tumbleweed_updater.sources import Action, Package, ZypperResult

        self.calls += 1
        names = self.before if self.calls == 1 else self.after
        return ZypperResult(
            packages=[Package(n, Action.REMOVE, "", "1.0", "x86_64") for n in names]
        )


def _leave_out_run(monkeypatch, tmp_path, before, after, dup_rc=0):
    """Drive one --without-unreachable run and report what it did."""
    from tumbleweed_updater import repos, statusfile

    seen = {"enabled": [], "dup": None}
    monkeypatch.setattr(helper_run_update, "_run_teed", lambda argv: (4, "out"))
    monkeypatch.setattr(
        helper_run_update,
        "_run",
        lambda argv: seen.__setitem__("dup", argv) or dup_rc,
    )
    monkeypatch.setattr(
        helper_run_update, "_missing_sources", lambda out: [("vlc", "VLC")]
    )
    monkeypatch.setattr(
        repos,
        "set_enabled",
        lambda alias, enabled, **k: seen["enabled"].append((alias, enabled)),
    )
    # No status file: the baseline is then the first of the two dry runs.
    monkeypatch.setattr(statusfile, "read", lambda *a, **k: None)
    monkeypatch.setattr(
        helper_run_update.sources, "check_zypper", _Sources(before, after)
    )
    monkeypatch.setattr(
        repos, "SOURCES_TO_RESTORE", str(tmp_path / "restore.json")
    )
    monkeypatch.setattr("sys.argv", ["run-update", "--without-unreachable", "-y"])
    seen["rc"] = helper_run_update.main()
    return seen


def test_the_source_is_switched_off_and_back_on_around_the_upgrade(
    monkeypatch, tmp_path, capsys
):
    seen = _leave_out_run(monkeypatch, tmp_path, before=set(), after=set())

    assert seen["rc"] == 0
    assert seen["enabled"] == [("vlc", False), ("vlc", True)]
    assert seen["dup"] == ["zypper", "dup", "-y"]
    out = capsys.readouterr().out
    assert "Leaving VLC out of this update" in out
    assert "Putting VLC back" in out


def test_the_source_goes_back_on_even_when_the_upgrade_fails(
    monkeypatch, tmp_path, capsys
):
    seen = _leave_out_run(
        monkeypatch, tmp_path, before=set(), after=set(), dup_rc=4
    )

    assert seen["rc"] == 4
    assert seen["enabled"][-1] == ("vlc", True)


def test_extra_removals_stop_the_upgrade_before_it_starts(
    monkeypatch, tmp_path, capsys
):
    """Leaving a source out orphans everything installed from it, and zypper
    removes orphans that block an upgrade without asking, since the app's
    default options include -y. So the dry run is compared first."""
    seen = _leave_out_run(
        monkeypatch, tmp_path, before={"old-thing"}, after={"old-thing", "vlc"}
    )

    assert seen["rc"] != 0
    assert seen["dup"] is None  # never got as far as the upgrade
    assert seen["enabled"] == [("vlc", False), ("vlc", True)]
    out = capsys.readouterr().out
    assert "would also remove" in out
    assert "nothing was changed" in out


def test_removals_that_were_already_planned_are_not_held_against_it(
    monkeypatch, tmp_path
):
    seen = _leave_out_run(
        monkeypatch, tmp_path, before={"old-thing"}, after={"old-thing"}
    )
    assert seen["rc"] == 0
    assert seen["dup"] == ["zypper", "dup", "-y"]


def test_nothing_is_switched_off_without_the_option(monkeypatch, tmp_path):
    from tumbleweed_updater import repos

    touched = []
    monkeypatch.setattr(helper_run_update, "_run_teed", lambda argv: (4, "out"))
    monkeypatch.setattr(helper_run_update, "_run", lambda argv: 0)
    monkeypatch.setattr(
        helper_run_update, "_missing_sources", lambda out: [("vlc", "VLC")]
    )
    monkeypatch.setattr(
        repos, "set_enabled", lambda *a, **k: touched.append(a) or None
    )
    monkeypatch.setattr("sys.argv", ["run-update", "-y"])

    assert helper_run_update.main() == 0
    assert touched == []


def test_a_dry_run_that_cannot_answer_stops_and_says_why(monkeypatch, tmp_path, capsys):
    """The usual reason it cannot answer is the thing being guarded against:
    with the source out, everything installed from it is an orphan and zypper
    asks what to do with each rather than computing a plan. Its explanation is
    already written for the user, so it is passed straight through."""
    from tumbleweed_updater import repos, sources, statusfile

    seen = {"enabled": [], "dup": None}
    monkeypatch.setattr(helper_run_update, "_run_teed", lambda argv: (4, "out"))
    monkeypatch.setattr(
        helper_run_update, "_run", lambda argv: seen.__setitem__("dup", argv) or 0
    )
    monkeypatch.setattr(
        helper_run_update, "_missing_sources", lambda out: [("vlc", "VLC")]
    )
    monkeypatch.setattr(
        repos, "set_enabled", lambda alias, enabled, **k: seen["enabled"].append(
            (alias, enabled)
        )
    )
    monkeypatch.setattr(repos, "SOURCES_TO_RESTORE", str(tmp_path / "restore.json"))
    monkeypatch.setattr(statusfile, "read", lambda *a, **k: None)

    calls = {"n": 0}

    def dry_runs(*a, **k):
        calls["n"] += 1
        if calls["n"] == 1:
            return sources.ZypperResult()  # the baseline, taken beforehand
        return sources.ZypperResult(error="Some of the programs you have…")

    monkeypatch.setattr(helper_run_update.sources, "check_zypper", dry_runs)
    monkeypatch.setattr("sys.argv", ["run-update", "--without-unreachable", "-y"])

    assert helper_run_update.main() == 1
    assert seen["dup"] is None
    assert seen["enabled"] == [("vlc", False), ("vlc", True)]
    out = capsys.readouterr().out
    assert "Some of the programs you have" in out
    assert "VLC has been put back" in out
