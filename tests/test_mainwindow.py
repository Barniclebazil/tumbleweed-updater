"""Window lifecycle: returning to a clean state after an update.

The app hides to the tray rather than quitting, so the embedded terminal keeps
the last update's transcript for the life of the process unless something
clears it. These cover when that happens and when it must not.
"""

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtCore import QEventLoop, QObject, QTimer, Signal
from PySide6.QtWidgets import QApplication, QMessageBox

from tumbleweed_updater.mainwindow import MainWindow
from tumbleweed_updater.runner import Step
from tumbleweed_updater.settings import Prefs, SettingsStore


class _StubPrivileged(QObject):
    """Just enough of PrivilegedRunner for MainWindow to wire itself up."""

    checkFinished = Signal(bool, str)

    @property
    def check_running(self) -> bool:
        return False

    def run_check(self, wait_for_packagekit: bool = True) -> bool:
        return True


@pytest.fixture(scope="module")
def app():
    return QApplication.instance() or QApplication([])


@pytest.fixture(autouse=True)
def isolated_config_home(tmp_path, monkeypatch):
    # Both variables: Qt resolves QSettings through XDG_CONFIG_HOME first, so
    # patching HOME alone leaves a test writing to the real user's config.
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / ".config"))


@pytest.fixture
def window(app, isolated_config_home, monkeypatch):
    # The re-check that follows a run would otherwise shell out to flatpak.
    monkeypatch.setattr(
        "tumbleweed_updater.workers.FlatpakChecker.start", lambda self: None
    )
    win = MainWindow(SettingsStore(), _StubPrivileged())
    yield win
    win.close()


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


def _leave_a_finished_update_on_screen(win) -> None:
    """The state the window is in once an update has run: panel up, log in it."""
    win._terminal_box.show()
    win._update_log_controls()
    win._terminal.feed(b"Installing: qt6-declarative-tools ...[done]\r\n")
    assert "qt6-declarative-tools" in win._terminal.buffer_text()


def _log_is_showing(win) -> bool:
    return win._terminal_box.isVisibleTo(win._splitter)


def _save(prefs_kwargs) -> None:
    SettingsStore().save(Prefs(**prefs_kwargs))


def test_closing_to_the_tray_clears_the_log_by_default(window):
    """The default: dismiss the window and it reopens the way it launched."""
    _leave_a_finished_update_on_screen(window)

    window.close()

    assert not _log_is_showing(window)
    assert "qt6-declarative-tools" not in window._terminal.buffer_text()
    assert window.isHidden(), "closing still hides to the tray rather than quitting"


def test_never_keeps_the_log_across_a_close(window):
    _save({"reset_after_update": "never"})
    _leave_a_finished_update_on_screen(window)

    window.close()

    assert _log_is_showing(window)
    assert "qt6-declarative-tools" in window._terminal.buffer_text()


def test_on_finish_clears_as_soon_as_the_run_succeeds(window):
    _save({"reset_after_update": "on_finish"})
    _leave_a_finished_update_on_screen(window)

    window._on_run_finished(True, "All updates completed.")

    assert not _log_is_showing(window)
    assert "qt6-declarative-tools" not in window._terminal.buffer_text()


def test_a_failed_run_always_keeps_its_log(window):
    """Whatever the preference says: the transcript is the only record of what
    went wrong."""
    _save({"reset_after_update": "on_finish"})
    _leave_a_finished_update_on_screen(window)

    window._on_run_finished(False, "“Upgrading the system” failed (exit 3).")

    assert _log_is_showing(window)
    assert "qt6-declarative-tools" in window._terminal.buffer_text()


def test_a_run_still_in_flight_is_never_reset(window, monkeypatch):
    """Closing mid-update keeps it running in the background, and its log is
    the only view onto it."""
    monkeypatch.setattr(
        QMessageBox, "question", staticmethod(lambda *a, **k: QMessageBox.Yes)
    )
    window._terminal_box.show()
    window._runner.start([Step("sleeping", ["/bin/sh", "-c", "echo mid-run; sleep 30"])])
    assert _pump_until(lambda: "mid-run" in window._terminal.buffer_text())

    window.close()

    assert _log_is_showing(window)
    assert "mid-run" in window._terminal.buffer_text()
    assert window._runner.cancel() is True
    assert _pump_until(lambda: not window._runner.is_running)


def test_hide_log_button_follows_the_panel(window):
    assert not window._btn_hide_log.isVisibleTo(window), "nothing to hide at launch"

    _leave_a_finished_update_on_screen(window)
    assert window._btn_hide_log.isVisibleTo(window)

    window._btn_hide_log.click()
    assert not _log_is_showing(window)
    assert not window._btn_hide_log.isVisibleTo(window)
    assert window._terminal.buffer_text().strip() == ""


def test_clearing_from_the_terminal_collapses_the_panel(window):
    """The context-menu entry reaches the window through clearRequested."""
    _leave_a_finished_update_on_screen(window)

    assert window._terminal.clear() is True

    assert not _log_is_showing(window)
    assert "qt6-declarative-tools" not in window._terminal.buffer_text()


# -- the lock banner ------------------------------------------------------- #


def _status(**zypper_kwargs):
    from tumbleweed_updater.sources import UpdateStatus, ZypperResult

    return UpdateStatus(zypper=ZypperResult(**zypper_kwargs))


def test_a_lock_error_offers_a_way_out(window):
    window.apply_zypper_status(
        _status(error="System management is locked by pid 3719", locked=True)
    )
    assert window._banner.isVisibleTo(window)
    assert window._banner_btn.isVisibleTo(window._banner)
    assert "3719" in window._banner_label.text()


def test_an_ordinary_error_gets_no_button(window):
    # Nothing the user can do from here, so no button to imply otherwise.
    window.apply_zypper_status(_status(error="Repository 'foo' is invalid."))
    assert window._banner.isVisibleTo(window)
    assert not window._banner_btn.isVisibleTo(window._banner)


def test_the_snapshot_warning_still_has_no_button(window):
    from tumbleweed_updater.sources import Action, Package

    status = _status(packages=[Package("bash", Action.UPGRADE, "2", "1", "x86_64")])
    status.snapshots_ok = False
    window.apply_zypper_status(status)
    assert window._banner.isVisibleTo(window)
    assert not window._banner_btn.isVisibleTo(window._banner)


def test_waiting_disables_the_button_and_rechecks(window, monkeypatch):
    started = {"n": 0}
    monkeypatch.setattr(
        "tumbleweed_updater.workers.LockWaiter.start",
        lambda self: started.__setitem__("n", started["n"] + 1),
    )
    window.apply_zypper_status(_status(error="locked", locked=True))

    window._on_wait_for_lock_clicked()
    assert started["n"] == 1
    assert window._banner_btn.isEnabled() is False


def test_waiting_is_ignored_while_a_check_runs(window, monkeypatch):
    started = {"n": 0}
    monkeypatch.setattr(
        "tumbleweed_updater.workers.LockWaiter.start",
        lambda self: started.__setitem__("n", started["n"] + 1),
    )
    monkeypatch.setattr(
        type(window._privileged), "check_running", property(lambda self: True)
    )
    window.apply_zypper_status(_status(error="locked", locked=True))

    window._on_wait_for_lock_clicked()
    assert started["n"] == 0


def test_first_shown_fires_once(window):
    seen = {"n": 0}
    window.firstShown.connect(lambda: seen.__setitem__("n", seen["n"] + 1))
    window.show_and_raise()
    window.show_and_raise()
    assert seen["n"] == 1
