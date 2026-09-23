"""helper/set-interval has to say when systemctl failed.

It used to ignore every systemctl exit code and return 0, so the settings
dialog took a schedule change the timer never adopted as a success.
"""

import importlib.machinery
import importlib.util
import subprocess
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
_loader = importlib.machinery.SourceFileLoader(
    "helper_set_interval", str(REPO_ROOT / "helper" / "set-interval")
)
_spec = importlib.util.spec_from_loader("helper_set_interval", _loader)
helper = importlib.util.module_from_spec(_spec)
_loader.exec_module(helper)


@pytest.fixture
def env(monkeypatch, tmp_path):
    """Point the drop-in at a temporary file and record every systemctl call."""
    dropin = tmp_path / "timer.d" / "override.conf"
    monkeypatch.setattr(helper, "CHECK_TIMER_DROPIN", str(dropin))
    calls = []
    failing = set()

    def fake_run(argv, check=False):
        calls.append(argv)
        rc = 1 if argv[1] in failing else 0
        return subprocess.CompletedProcess(argv, rc)

    monkeypatch.setattr(helper.subprocess, "run", fake_run)
    return calls, failing, dropin


def _main(monkeypatch, label):
    monkeypatch.setattr(helper.sys, "argv", ["set-interval", label])
    return helper.main()


def test_a_working_systemctl_is_success(monkeypatch, env):
    calls, _failing, dropin = env
    assert _main(monkeypatch, "daily") == 0
    assert "OnCalendar=daily" in dropin.read_text()
    assert ["systemctl", "enable", "--now", helper.CHECK_TIMER] in calls


@pytest.mark.parametrize("verb", ["daemon-reload", "enable"])
def test_a_failing_systemctl_is_reported(monkeypatch, env, capsys, verb):
    _calls, failing, _dropin = env
    failing.add(verb)
    assert _main(monkeypatch, "daily") == 1
    err = capsys.readouterr().err
    # The dialog shows this line as it is, so it follows the house rule.
    assert err.startswith("The system would not")
    assert "exit" not in err and "systemctl" not in err


def test_switching_to_manual_reports_a_failed_disable(monkeypatch, env):
    _calls, failing, _dropin = env
    failing.add("disable")
    assert _main(monkeypatch, "manual") == 1


def test_an_unknown_label_is_refused(monkeypatch, env):
    calls, _failing, _dropin = env
    assert _main(monkeypatch, "every minute") == 2
    assert calls == []
