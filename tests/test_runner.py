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
