"""Smoke tests for the PTY session and terminal widget.

Run headless via the offscreen Qt platform plugin.
"""

import contextlib
import os
import signal

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest

from PySide6.QtCore import QEventLoop, QTimer
from PySide6.QtWidgets import QApplication

from tumbleweed_updater.pty_session import PtySession
from tumbleweed_updater.terminal import TerminalWidget


@pytest.fixture(scope="module")
def app():
    return QApplication.instance() or QApplication([])


def _pump_until(predicate, timeout_ms=5000):
    loop = QEventLoop()
    timer = QTimer()
    timer.setInterval(20)
    timer.timeout.connect(lambda: loop.quit() if predicate() else None)
    timer.start()
    guard = QTimer()
    guard.setSingleShot(True)
    guard.timeout.connect(loop.quit)
    guard.start(timeout_ms)
    loop.exec()
    timer.stop()
    return predicate()


def test_pty_runs_and_reports_exit(app):
    sess = PtySession()
    seen = bytearray()
    codes = []
    sess.output.connect(seen.extend)
    sess.finished.connect(codes.append)
    sess.start(["/bin/sh", "-c", "echo hello-pty; exit 7"], rows=10, cols=40)
    assert _pump_until(lambda: codes != [])
    assert b"hello-pty" in bytes(seen)
    assert codes == [7]
    assert not sess.is_running


def test_terminal_renders_output(app):
    term = TerminalWidget()
    term.resize(400, 200)
    sess = PtySession()
    term.attach(sess)
    sess.start(["/bin/sh", "-c", "printf 'line-one\\nline-two\\n'; sleep 0.1"],
               rows=24, cols=80)
    assert _pump_until(lambda: "line-two" in term.buffer_text())
    text = term.buffer_text()
    assert "line-one" in text and "line-two" in text


def test_appearance_applies_and_reflows(app):
    term = TerminalWidget(font_family="", font_size=9, bg="#101010", fg="#e0e0e0")
    term.resize(500, 300)
    assert term._palette_bg.name() == "#101010"
    small_cell = term._cell_h

    term.apply_appearance(font_family="", font_size=18, bg="#002b36", fg="#93a1a1")
    assert term._palette_bg.name() == "#002b36"
    assert term._palette_fg.name() == "#93a1a1"
    assert term._cell_h > small_cell  # bigger font -> taller cells
    rows_big, cols_big = term.grid_size()
    assert rows_big >= 4 and cols_big >= 20
    term.grab()  # must paint without error


def test_keypress_translates_and_sends(app):
    from PySide6.QtCore import Qt
    from PySide6.QtGui import QKeyEvent

    term = TerminalWidget()
    term.resize(400, 200)
    sess = PtySession()
    term.attach(sess)
    sess.start(["/bin/cat"], rows=24, cols=80)
    _pump_until(lambda: sess.is_running, 2000)

    for text in "yes":
        ev = QKeyEvent(QKeyEvent.KeyPress, getattr(Qt, f"Key_{text.upper()}"),
                       Qt.NoModifier, text)
        term.keyPressEvent(ev)
    enter = QKeyEvent(QKeyEvent.KeyPress, Qt.Key_Return, Qt.NoModifier, "\r")
    term.keyPressEvent(enter)
    assert _pump_until(lambda: "yes" in term.buffer_text())

    ctrl_d = QKeyEvent(QKeyEvent.KeyPress, Qt.Key_D, Qt.ControlModifier, "")
    term.keyPressEvent(ctrl_d)
    assert _pump_until(lambda: not sess.is_running)


def test_terminal_forwards_keystrokes(app):
    term = TerminalWidget()
    term.resize(400, 200)
    sess = PtySession()
    term.attach(sess)
    # `read` echoes nothing itself, but `cat` echoes back what we type.
    sess.start(["/bin/cat"], rows=24, cols=80)
    _pump_until(lambda: sess.is_running, 2000)
    sess.write(b"ping\r")
    assert _pump_until(lambda: "ping" in term.buffer_text())
    sess.write(b"\x04")  # Ctrl-D
    assert _pump_until(lambda: not sess.is_running)


def test_notice_lines_start_at_column_zero(app):
    """A bare line feed moves down without returning to column 0, so a
    multi-line notice would come out staircased."""
    term = TerminalWidget()
    term.resize(800, 400)
    term.append_notice("first line\nsecond line\nthird line")
    lines = [ln for ln in term.buffer_text().splitlines() if ln]
    assert lines == ["first line", "second line", "third line"]


def test_paste_sanitiser_keeps_text_and_drops_control_characters():
    """Pasted text is fed to a process running as root, so escape sequences in
    it must not be interpreted as terminal commands."""
    from tumbleweed_updater.terminal import _sanitise_paste

    assert _sanitise_paste("plain text") == "plain text"
    assert _sanitise_paste("a\x1b[31mb\x07c") == "a[31mbc"
    assert _sanitise_paste("one\r\ntwo\rthree") == "one\ntwo\nthree"
    assert _sanitise_paste("keep\tthe\ttabs") == "keep\tthe\ttabs"


def test_feed_survives_a_parser_error(app, monkeypatch):
    """feed() runs in the PTY notifier's slot, where an escaping exception
    aborts the process."""
    term = TerminalWidget()
    term.resize(400, 200)

    def boom(_data):
        raise RuntimeError("bad escape")

    monkeypatch.setattr(term._stream, "feed", boom)
    term.feed(b"anything")  # must not raise


def test_reaping_a_lingering_child_does_not_block_the_event_loop(app):
    """A child that closes the PTY without exiting used to hold the GUI in a
    blocking waitpid for as long as it lived."""
    sess = PtySession()
    done = []
    sess.finished.connect(lambda code: done.append(code))
    ticks = []

    # Closes its descriptors (so the master sees EOF), ignores the SIGHUP that
    # follows, and stays alive well past the reaper's patience.
    sess.start(
        ["/bin/sh", "-c", "trap '' HUP; exec 1>&- 2>&- 0<&-; sleep 20"],
        rows=24,
        cols=80,
    )

    heartbeat = QTimer()
    heartbeat.setInterval(50)
    heartbeat.timeout.connect(lambda: ticks.append(1))
    heartbeat.start()
    finished = _pump_until(lambda: done != [], timeout_ms=9000)
    heartbeat.stop()
    # kill() is a no-op once the session has given up on the child, so reach
    # for the pid directly rather than leaving a sleep behind.
    with contextlib.suppress(OSError):
        os.kill(sess._pid, signal.SIGKILL)

    assert finished, "the reaper never gave up"
    assert done[0] < 0, "a child that never exited is not a clean exit"
    assert len(ticks) > 10, "the event loop stalled while waiting"
