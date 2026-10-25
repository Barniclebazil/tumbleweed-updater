"""run-update's Flatpak mode: one allow-listed command, no zypper, no lock wait."""

import importlib.machinery
import importlib.util
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
_loader = importlib.machinery.SourceFileLoader(
    "helper_run_update", str(REPO_ROOT / "helper" / "run-update")
)
_spec = importlib.util.spec_from_loader("helper_run_update", _loader)
helper_run_update = importlib.util.module_from_spec(_spec)
_loader.exec_module(helper_run_update)


@pytest.fixture
def ran(monkeypatch):
    """Record every command; fail if zypper's lock or refresh is touched."""
    calls = []
    monkeypatch.setattr(helper_run_update, "_run", lambda argv: calls.append(argv) or 7)

    def forbidden(*_a, **_k):
        raise AssertionError("not for Flatpak mode")

    monkeypatch.setattr(helper_run_update, "_run_teed", forbidden)
    monkeypatch.setattr(helper_run_update.packagekit, "lock_holder", forbidden)
    monkeypatch.setattr(helper_run_update.packagekit, "wait_for_lock", forbidden)
    # main() writes to os.environ directly; give it a copy to scribble on.
    monkeypatch.setattr(helper_run_update.os, "environ", dict(helper_run_update.os.environ))
    return calls


def _main(monkeypatch, *args):
    monkeypatch.setattr(helper_run_update.sys, "argv", ["run-update", *args])
    return helper_run_update.main()


def test_flatpak_runs_the_system_update(monkeypatch, ran):
    assert _main(monkeypatch, "--flatpak") == 7
    assert ran == [["flatpak", "update", "--system"]]


def test_flatpak_passes_yes(monkeypatch, ran):
    assert _main(monkeypatch, "--flatpak", "-y") == 7
    assert ran == [["flatpak", "update", "--system", "-y"]]


@pytest.mark.parametrize("extra", [["--foo"], ["-y", "extra"]])
def test_flatpak_refuses_other_options(monkeypatch, ran, capsys, extra):
    assert _main(monkeypatch, "--flatpak", *extra) == 2
    assert ran == []
    assert "refusing unrecognised flatpak option(s)" in capsys.readouterr().err


def test_cleanup_before_flatpak_is_not_flatpak_mode(monkeypatch, ran):
    assert _main(monkeypatch, "--cleanup", "--flatpak") == 2
    assert ran == []


def test_flatpak_sets_the_data_dirs_when_unset(monkeypatch, ran):
    helper_run_update.os.environ.pop("XDG_DATA_DIRS", None)
    _main(monkeypatch, "--flatpak")
    assert "/var/lib/flatpak/exports/share" in helper_run_update.os.environ["XDG_DATA_DIRS"]


def test_flatpak_keeps_an_existing_data_dirs(monkeypatch, ran):
    helper_run_update.os.environ["XDG_DATA_DIRS"] = "/somewhere"
    _main(monkeypatch, "--flatpak")
    assert helper_run_update.os.environ["XDG_DATA_DIRS"] == "/somewhere"
