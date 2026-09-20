import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtCore import QEventLoop, QTimer
from PySide6.QtWidgets import QApplication

from tumbleweed_updater.runner import Step, UpdateRunner
from tumbleweed_updater.terminal import TerminalWidget


@pytest.fixture(scope="module")
def app():
    return QApplication.instance() or QApplication([])


def _wait(pred, timeout=5000):
    loop = QEventLoop()
    t = QTimer()
    t.setInterval(20)
    t.timeout.connect(lambda: loop.quit() if pred() else None)
    t.start()
    g = QTimer()
    g.setSingleShot(True)
    g.timeout.connect(loop.quit)
    g.start(timeout)
    loop.exec()
    return pred()


def test_queue_runs_all_steps_in_order(app):
    term = TerminalWidget()
    term.resize(600, 300)
    runner = UpdateRunner(term)
    results = []
    runner.finished.connect(lambda ok, msg: results.append((ok, msg)))

    runner.start([
        Step("first", ["/bin/sh", "-c", "echo AAA"]),
        Step("second", ["/bin/sh", "-c", "echo BBB"]),
    ])
    assert _wait(lambda: results != [])
    assert results[0][0] is True
    text = term.buffer_text()
    assert "AAA" in text and "BBB" in text
    assert text.index("AAA") < text.index("BBB")
    # Painting after the queue finished must not touch the freed PtySession.
    term.grab()
    assert not runner.is_running


def test_zypper_reboot_exit_codes_count_as_success(app):
    term = TerminalWidget()
    term.resize(600, 300)
    runner = UpdateRunner(term)
    results = []
    runner.finished.connect(lambda ok, msg: results.append((ok, msg)))

    # 102 = ZYPPER_EXIT_INF_REBOOT_NEEDED
    runner.start([
        Step("upgrade", ["/bin/sh", "-c", "echo upgraded; exit 102"]),
        Step("flatpak", ["/bin/sh", "-c", "echo flatpak-ran"]),
    ])
    assert _wait(lambda: results != [])
    assert results[0][0] is True
    assert "flatpak-ran" in term.buffer_text()


def test_cleanup_flag_added_to_argv(app):
    term = TerminalWidget()
    runner = UpdateRunner(term)
    with_cleanup = runner.build_queue(do_zypper=True, dup_args=["--x"], cleanup=True)
    without = runner.build_queue(do_zypper=True, dup_args=["--x"], cleanup=False)
    assert "--cleanup" in with_cleanup[0].argv
    assert with_cleanup[0].argv.index("--cleanup") < with_cleanup[0].argv.index("--x")
    assert "--cleanup" not in without[0].argv


def test_packagekit_wait_opt_out_added_to_argv(app):
    # The helper waits by default, so only the opt-out is ever passed - which
    # is also why the systemd timer (no arguments) always waits.
    term = TerminalWidget()
    runner = UpdateRunner(term)
    default = runner.build_queue(do_zypper=True, dup_args=["--x"])
    opted_out = runner.build_queue(
        do_zypper=True, dup_args=["--x"], wait_for_packagekit=False
    )
    flag = "--no-wait-for-packagekit"
    assert flag not in default[0].argv
    assert flag in opted_out[0].argv
    # It has to reach the helper before dupargs sees the rest.
    assert opted_out[0].argv.index(flag) < opted_out[0].argv.index("--x")


def test_queue_stops_on_failure(app):
    term = TerminalWidget()
    term.resize(600, 300)
    runner = UpdateRunner(term)
    results = []
    runner.finished.connect(lambda ok, msg: results.append((ok, msg)))

    runner.start([
        Step("will fail", ["/bin/sh", "-c", "echo BOOM; exit 3"]),
        Step("never runs", ["/bin/sh", "-c", "echo SHOULD_NOT_APPEAR"]),
    ])
    assert _wait(lambda: results != [])
    assert results[0][0] is False
    assert "exit 3" in results[0][1]
    assert "SHOULD_NOT_APPEAR" not in term.buffer_text()
    assert not runner.is_running


def test_cancel_interrupts_rather_than_signalling(app):
    """The zypper step runs as root through pkexec, so os.kill() from here is
    refused with EPERM. Ctrl-C down the PTY reaches it regardless of who owns
    the process, so that is what Cancel must use."""
    term = TerminalWidget()
    term.resize(600, 300)
    runner = UpdateRunner(term)
    results = []
    runner.finished.connect(lambda ok, msg: results.append((ok, msg)))

    # trap makes the difference visible: SIGINT exits 42, SIGTERM exits 43.
    runner.start(
        [
            Step(
                "sleeping",
                ["/bin/sh", "-c", "trap 'exit 42' INT; trap 'exit 43' TERM; sleep 30"],
            )
        ]
    )
    assert _wait(lambda: runner.is_running)
    assert runner.cancel() is True
    assert _wait(lambda: results != [])
    assert results[0][0] is False
    assert "exit 42" in results[0][1]


def test_cancel_with_nothing_running_says_so(app):
    term = TerminalWidget()
    runner = UpdateRunner(term)
    assert runner.cancel() is False
