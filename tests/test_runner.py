import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtCore import QEventLoop, QTimer
from PySide6.QtWidgets import QApplication

from tumbleweed_updater import runner as runner_module
from tumbleweed_updater.progress import COUNTED_UPTO, CREEP_TO
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


def test_nothing_asks_the_helper_to_skip_the_packagekit_wait(app):
    """It used to be a preference, and the flag with it. The helper always
    waits now, and takes no option that says otherwise."""
    term = TerminalWidget()
    runner = UpdateRunner(term)
    argv = runner.build_queue(do_zypper=True, dup_args=["--x"])[0].argv

    assert "--no-wait-for-packagekit" not in argv


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
    # The exit code is the terminal's record; the window's message is plain.
    assert "exit 3" in term.buffer_text()
    assert "exit" not in results[0][1]
    assert "did not finish" in results[0][1]
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
                [
                    "/bin/sh",
                    "-c",
                    "trap 'exit 42' INT; trap 'exit 43' TERM; echo TRAPS_SET; sleep 30",
                ],
            )
        ]
    )
    # Not just is_running: a Ctrl-C that lands before the shell has installed
    # its trap kills it outright, which reads as "cancelled" rather than exit 42.
    assert _wait(lambda: "TRAPS_SET" in term.buffer_text())
    assert runner.cancel() is True
    assert _wait(lambda: results != [])
    assert results[0][0] is False
    assert "exit 42" in term.buffer_text()


def test_cancel_with_nothing_running_says_so(app):
    term = TerminalWidget()
    runner = UpdateRunner(term)
    assert runner.cancel() is False


# --------------------------------------------------------------------------- #
# The progress bar. The zypper-style lines are built from zypper's source, as
# in tests/test_progress.py, and printed by a shell so that they arrive through
# a real PTY in whatever chunks it delivers.
# --------------------------------------------------------------------------- #

# Two downloads, a redrawn install line with colour codes, the second install,
# then something after the last counter. The pauses let each line arrive on
# its own, as it does from zypper, rather than all in one read.
_ZYPPER_LIKE = "; sleep 0.1; ".join([
    r"printf 'Continue? [y/n/v/...? shows all options] (y): y\n'",
    r"printf 'Retrieving: a-1.0 (OSS)      (1/2),   1.0 MiB    \n'",
    r"printf 'Retrieving: b-1.0 (OSS)      (2/2),   1.0 MiB    \n'",
    r"printf '(1/2) Installing: a-1.0 ...[|]\r\033[K(1/2) Installing: a-1.0 \033[32m[done]\033[0m\n'",
    r"printf '(2/2) Installing: b-1.0 [done]\n'",
    r"printf 'Running post-transaction scripts ...[done]\n'",
])


def _progress_of(runner):
    seen = []
    runner.progressChanged.connect(lambda text, value, maximum: seen.append((text, value, maximum)))
    return seen


def test_the_zypper_step_reports_its_progress(app):
    term = TerminalWidget()
    term.resize(600, 300)
    runner = UpdateRunner(term)
    seen = _progress_of(runner)
    done = []
    runner.finished.connect(lambda ok, msg: done.append(ok))

    runner.start([Step("Updating the system", ["/bin/sh", "-c", _ZYPPER_LIKE], counts_packages=True)])
    assert _wait(lambda: done != [])

    texts = [text for text, _value, _maximum in seen]
    # One bar from start to end: empty while getting ready, never moving.
    assert seen[0] == ("Updating the system: getting ready", 0, 1000)
    assert "Updating the system: downloading 2 of 2 packages" in texts
    assert "Updating the system: installing 1 of 2 packages" in texts
    assert seen[-1] == ("Updating the system: finishing off", COUNTED_UPTO, 1000)
    assert all(maximum == 1000 for _text, _value, maximum in seen)
    counted = [value for _text, value, _maximum in seen]
    assert counted == sorted(counted), "the bar never goes backwards"
    assert len(seen) == len(set(seen)), "a redrawn line is not sent twice"


class _Clock:
    def __init__(self):
        self.now = 1000.0

    def monotonic(self):
        return self.now


def test_after_the_last_package_the_bar_creeps_on_by_the_clock(app, monkeypatch):
    """zypper counts nothing while its scripts, snapshot and clean-up run, so
    the bar moves on by time, slowly, and stops short of full."""
    clock = _Clock()
    monkeypatch.setattr(runner_module, "time", clock)
    term = TerminalWidget()
    term.resize(600, 300)
    runner = UpdateRunner(term)
    seen = _progress_of(runner)
    done = []
    runner.finished.connect(lambda ok, msg: done.append(ok))

    script = "printf '(1/1) Installing: a-1.0 [done]\\n'; echo SCRIPTS; sleep 30"
    runner.start([Step("Updating the system", ["/bin/sh", "-c", script], counts_packages=True)])
    assert _wait(lambda: "SCRIPTS" in term.buffer_text())
    assert _wait(lambda: seen[-1] == ("Updating the system: finishing off", COUNTED_UPTO, 1000))

    clock.now += 60
    assert _wait(lambda: seen[-1][1] > COUNTED_UPTO)
    assert seen[-1][1] < CREEP_TO

    assert runner.cancel() is True
    assert not runner._creep.isActive()
    assert _wait(lambda: done != [])
    assert seen[-1] == ("Stopping the update", 0, 0)


def test_another_step_is_named_and_shows_a_moving_bar(app):
    term = TerminalWidget()
    term.resize(600, 300)
    runner = UpdateRunner(term)
    seen = _progress_of(runner)
    done = []
    runner.finished.connect(lambda ok, msg: done.append(ok))

    # Counters in a step whose output is not read change nothing.
    runner.start([Step("Updating your Flatpak apps", ["/bin/sh", "-c", "printf '(1/2) Installing: x\\n'"])])
    assert _wait(lambda: done != [])

    assert seen == [("Updating your Flatpak apps", 0, 0)]


def test_a_run_of_several_steps_says_which_step_it_is_on(app):
    term = TerminalWidget()
    term.resize(600, 300)
    runner = UpdateRunner(term)
    seen = _progress_of(runner)
    done = []
    runner.finished.connect(lambda ok, msg: done.append(ok))

    runner.start([
        Step("Updating the system", ["/bin/sh", "-c", "true"], counts_packages=True),
        Step("Updating your Flatpak apps", ["/bin/sh", "-c", "true"]),
    ])
    assert _wait(lambda: done != [])

    texts = [text for text, _value, _maximum in seen]
    assert "Updating the system: getting ready (step 1 of 2)" in texts
    assert "Updating your Flatpak apps (step 2 of 2)" in texts


def test_cancelling_stops_the_bar_moving(app):
    """zypper may finish the package it is on after Ctrl-C. Its counter must
    not move the bar on as though the update were carrying on."""
    term = TerminalWidget()
    term.resize(600, 300)
    runner = UpdateRunner(term)
    seen = _progress_of(runner)
    done = []
    runner.finished.connect(lambda ok, msg: done.append(ok))

    script = (
        "trap 'printf \"(2/2) Installing: b\\n\"; exit 42' INT; "
        "printf '(1/2) Installing: a\\n'; echo TRAPS_SET; sleep 30"
    )
    runner.start([Step("Updating the system", ["/bin/sh", "-c", script], counts_packages=True)])
    assert _wait(lambda: "TRAPS_SET" in term.buffer_text())
    assert _wait(lambda: any("installing 1 of 2" in text for text, _v, _m in seen))
    assert runner.cancel() is True
    assert _wait(lambda: done != [])

    assert seen[-1] == ("Stopping the update", 0, 0)
    assert not any("installing 2 of 2" in text for text, _v, _m in seen)


@pytest.mark.parametrize(
    "dup_args, download_only",
    [([], False), (["--download", "only"], True), (["--download=only"], True),
     (["--download", "in-advance"], False)],
)
def test_only_the_zypper_step_is_read_and_download_only_is_noticed(app, dup_args, download_only):
    runner = UpdateRunner(TerminalWidget())
    steps = runner.build_queue(
        do_zypper=True, dup_args=dup_args, do_flatpak_system=True, do_flatpak_user=True
    )
    assert [s.counts_packages for s in steps] == [True, False, False]
    assert steps[0].download_only is download_only
