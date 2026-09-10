"""Smoke tests for the PTY session and terminal widget.

Run headless via the offscreen Qt platform plugin.
"""

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest

from PySide6.QtCore import QCoreApplication, QEventLoop, QTimer
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
