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
from tumbleweed_updater.repos import Repo, ReposResult
from tumbleweed_updater.runner import Step
from tumbleweed_updater.settings import Prefs, SettingsStore
from tumbleweed_updater.sources import (
    Action,
    Package,
    UpdateStatus,
    ZypperResult,
)


class _StubPrivileged(QObject):
    """Just enough of PrivilegedRunner for MainWindow to wire itself up."""

    checkFinished = Signal(bool, str)
    reposFinished = Signal(bool, str)

    def __init__(self) -> None:
        super().__init__()
        self.repo_calls = []

    @property
    def check_running(self) -> bool:
        return False

    @property
    def repos_running(self) -> bool:
        return False

    def run_check(self, wait_for_packagekit: bool = True) -> bool:
        return True

    def set_repo_enabled(self, alias: str, enabled: bool) -> bool:
        self.repo_calls.append((alias, enabled))
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
    # Setting these is not enough on its own: Qt resolves the config directory
    # once per process and caches it, so every test after the first keeps
    # writing to the first one's file. Tests that write before they read are
    # unaffected, but anything checking a default has to start from a known
    # state, so the keys that are not written by every test are cleared here.
    SettingsStore().set_disabled_sources([])


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


# --------------------------------------------------------------------------- #
# The banner for a software source that could not be reached.
#
# The wording is checked here rather than left to review: this is the one place
# the app has to explain a package-manager failure to somebody who has never
# heard of a repository, and the words are the feature.
# --------------------------------------------------------------------------- #


def _apply(win, **zypper_kwargs):
    status = UpdateStatus(zypper=ZypperResult(**zypper_kwargs), snapshots_ok=True)
    win.apply_zypper_status(status)
    return win._banner_label.text()


def _banner_showing(win) -> bool:
    # isVisible() is False for everything in a window that was never shown, so
    # ask the question relative to the parent, as _log_is_showing does.
    return not win._banner.isHidden()


def _banner_button(win) -> str:
    return win._banner_btn.text() if not win._banner_btn.isHidden() else ""


def _some_packages(n=3):
    return [
        Package(f"pkg{i}", Action.UPGRADE, "2.0", "1.0", "x86_64") for i in range(n)
    ]


def test_one_unreachable_source_is_explained_in_plain_language(window):
    text = _apply(
        window, packages=_some_packages(43), failed_repos=[("vlc", "VLC")]
    )

    assert "VLC" in text
    assert "left out" in text
    assert "The other 43 updates can still be installed." in text
    assert "keep working" in text
    # None of the vocabulary the user would have to look up.
    for jargon in ("repository", "metadata", "refresh", "zypper", "exit"):
        assert jargon not in text.lower(), jargon
    # The alias is internal; only the display name is shown.
    assert "vlc" not in text.replace("VLC", "")


def test_one_unreachable_source_offers_to_switch_it_off(window):
    _apply(window, packages=_some_packages(43), failed_repos=[("vlc", "VLC")])

    assert _banner_button(window) == "Stop using VLC"


def test_several_unreachable_sources_are_counted_and_named(window):
    text = _apply(
        window,
        packages=_some_packages(43),
        failed_repos=[("vlc", "VLC"), ("packman", "Packman")],
    )

    assert "2 of your software sources" in text
    assert "VLC, Packman" in text
    # No button: which one to switch off is not a decision the app can make.
    assert _banner_button(window) == ""


def test_a_reachable_system_shows_no_banner(window):
    _apply(window, packages=_some_packages(3))
    assert not _banner_showing(window)


def test_an_unreachable_source_is_a_warning_not_an_error(window):
    """The headline still counts the updates: they can all still be installed,
    which is the whole point of the change underneath this."""
    _apply(window, packages=_some_packages(43), failed_repos=[("vlc", "VLC")])

    assert "43 update(s) available" in window._headline.text()


def test_a_check_failure_still_wins_over_a_missing_source(window):
    text = _apply(
        window,
        error="System management is locked by pid 5899",
        locked=True,
        failed_repos=[("vlc", "VLC")],
    )

    assert "5899" in text
    assert "VLC" in text, "both are said, rather than one hiding the other"
    assert _banner_button(window) == "Wait for it and retry"


def test_switching_a_source_off_asks_first_and_calls_the_helper(window, monkeypatch):
    asked = {}

    def fake_question(parent, title, body, *a, **k):
        asked["title"] = title
        asked["body"] = body
        return QMessageBox.Yes

    monkeypatch.setattr(QMessageBox, "question", staticmethod(fake_question))
    _apply(window, packages=_some_packages(43), failed_repos=[("vlc", "VLC")])

    window._banner_btn.click()

    assert asked["title"] == "Stop using VLC?"
    assert "stays on your computer" in asked["body"]
    assert "switch it back on" in asked["body"]
    assert window._privileged.repo_calls == [("vlc", False)]


def test_declining_the_question_changes_nothing(window, monkeypatch):
    monkeypatch.setattr(
        QMessageBox, "question", staticmethod(lambda *a, **k: QMessageBox.No)
    )
    _apply(window, packages=_some_packages(43), failed_repos=[("vlc", "VLC")])

    window._banner_btn.click()

    assert window._privileged.repo_calls == []


def test_a_source_we_switched_off_is_remembered_and_offered_back(window, monkeypatch):
    monkeypatch.setattr(
        QMessageBox, "question", staticmethod(lambda *a, **k: QMessageBox.Yes)
    )
    monkeypatch.setattr(
        "tumbleweed_updater.mainwindow.list_repos",
        lambda: ReposResult(repos=[Repo(alias="vlc", name="VLC", enabled=False)]),
    )
    _apply(window, packages=_some_packages(43), failed_repos=[("vlc", "VLC")])
    window._banner_btn.click()
    window._privileged.reposFinished.emit(True, "")

    assert SettingsStore().disabled_sources() == ["vlc"]

    # A later check finds nothing wrong, and the note takes over.
    text = _apply(window, packages=_some_packages(3))
    assert text == "VLC is switched off, so its programs aren't being updated."
    assert _banner_button(window) == "Switch VLC back on"


def test_the_switched_off_note_is_not_styled_as_a_problem(window, monkeypatch):
    SettingsStore().set_disabled_sources(["vlc"])
    monkeypatch.setattr(
        "tumbleweed_updater.mainwindow.list_repos",
        lambda: ReposResult(repos=[Repo(alias="vlc", name="VLC", enabled=False)]),
    )
    _apply(window, packages=_some_packages(3))

    assert "#f67400" not in window._banner.styleSheet()


def test_a_source_the_user_switched_back_on_elsewhere_is_forgotten(window, monkeypatch):
    """The user can also re-enable it in YaST, and the note must not outlive
    that."""
    SettingsStore().set_disabled_sources(["vlc"])
    monkeypatch.setattr(
        "tumbleweed_updater.mainwindow.list_repos",
        lambda: ReposResult(repos=[Repo(alias="vlc", name="VLC", enabled=True)]),
    )
    _apply(window, packages=_some_packages(3))

    assert not _banner_showing(window)


def test_a_source_that_no_longer_exists_is_dropped_from_the_preference(
    window, monkeypatch
):
    SettingsStore().set_disabled_sources(["vlc", "gone"])
    monkeypatch.setattr(
        "tumbleweed_updater.mainwindow.list_repos",
        lambda: ReposResult(repos=[Repo(alias="vlc", name="VLC", enabled=False)]),
    )
    _apply(window, packages=_some_packages(3))

    assert SettingsStore().disabled_sources() == ["vlc"]


def test_sources_we_never_touched_are_left_alone(window, monkeypatch):
    """Most systems have sources disabled on purpose long ago. Offering to
    switch those back on would be noise."""
    called = {"n": 0}

    def counting_list_repos():
        called["n"] += 1
        return ReposResult(repos=[Repo(alias="repo-debug", enabled=False)])

    monkeypatch.setattr(
        "tumbleweed_updater.mainwindow.list_repos", counting_list_repos
    )
    _apply(window, packages=_some_packages(3))

    assert not _banner_showing(window)
    # Not even asked for: nothing was ever recorded, so there is nothing to
    # check against and no subprocess to spawn.
    assert called["n"] == 0
