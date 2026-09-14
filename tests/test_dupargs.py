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
    monkeypatch.setattr(
        "sys.argv", ["run-update", "--cleanup", "-y", "--download", "in-advance"]
    )

    assert helper_run_update.main() == 0
    assert ran[0] == ["zypper", "refresh"]
    assert ran[1] == ["zypper", "dup", "-y", "--download", "in-advance"]
    assert ran[2] == ["zypper", "clean"]


def test_helper_treats_reboot_and_restart_exits_as_success(monkeypatch):
    codes = iter([0, 102])
    monkeypatch.setattr(helper_run_update, "_run", lambda argv: next(codes))
    monkeypatch.setattr("sys.argv", ["run-update"])
    assert helper_run_update.main() == 0
