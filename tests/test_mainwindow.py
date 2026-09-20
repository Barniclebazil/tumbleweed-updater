"""Window lifecycle: returning to a clean state after an update.

The app hides to the tray rather than quitting, so the embedded terminal keeps
the last update's transcript for the life of the process unless something
clears it. These cover when that happens and when it must not.
"""

import os
from datetime import date, timedelta

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtCore import QEventLoop, QObject, QTimer, Signal
from PySide6.QtWidgets import QApplication, QMessageBox

from tumbleweed_updater.mainwindow import MainWindow
from tumbleweed_updater.tray import TrayState
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
    SettingsStore().set_deferred_until(None)


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


def _apply(win, snapshots_ok=True, **zypper_kwargs):
    status = UpdateStatus(
        zypper=ZypperResult(**zypper_kwargs), snapshots_ok=snapshots_ok
    )
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
    assert "The other 43 updates were checked as usual." in text
    assert "keep working" in text
    # Not a promise that they will install: zypper refuses the upgrade outright
    # once it has no usable details left for the missing source, and says the
    # source has to be switched off. So does this.
    assert "can still be installed" not in text
    # What to do about it is the button's job now, not another sentence's.
    assert "switch" not in text.lower()
    # None of the vocabulary the user would have to look up.
    for jargon in ("repository", "metadata", "refresh", "zypper", "exit"):
        assert jargon not in text.lower(), jargon
    # The alias is internal; only the display name is shown.
    assert "vlc" not in text.replace("VLC", "")


def test_one_unreachable_source_offers_the_upgrade_without_it(window):
    """It used to offer to switch the source off for good. On a real machine
    that broke the app outright: the packages installed from VLC were orphaned,
    and the next check got a solver question per orphan, answered none, and
    computed nothing, leaving "Could not check for system updates" and no way
    forward. What the banner offers has to be reversible."""
    _apply(window, packages=_some_packages(43), failed_repos=[("vlc", "VLC")])

    assert _banner_button(window) == "Update without VLC"


def test_nothing_is_offered_when_there_is_no_upgrade_to_run(window):
    _apply(window, failed_repos=[("vlc", "VLC")])

    assert _banner_button(window) == ""


def test_the_banner_button_waits_for_the_windows_own_check(window, monkeypatch):
    """Everything the banner offers ends in a helper that needs zypper's lock,
    and this window is the thing most likely to be holding it: a check starts
    by itself the moment an update run ends, and takes half a minute. Clicking
    through that window reached zypper and came back with its refusal, which
    reads as the app being broken rather than as two of its own jobs meeting.
    """
    _apply(window, packages=_some_packages(43), failed_repos=[("vlc", "VLC")])
    assert window._banner_btn.isEnabled()

    monkeypatch.setattr(
        type(window._privileged), "check_running", property(lambda self: True)
    )
    window._set_busy(True, "")
    assert not window._banner_btn.isEnabled()

    # A click that was already on its way finds the door shut too.
    window._on_switch_source_back_on("vlc", "VLC")
    assert window._privileged.repo_calls == []


def test_the_banner_button_comes_back_when_the_check_ends(window):
    _apply(window, packages=_some_packages(43), failed_repos=[("vlc", "VLC")])
    window._set_busy(True, "")
    window._set_busy(False, "")
    assert window._banner_btn.isEnabled()


def test_several_unreachable_sources_are_counted_and_named(window):
    text = _apply(
        window,
        packages=_some_packages(43),
        failed_repos=[("vlc", "VLC"), ("packman", "Packman")],
    )

    assert "2 of your software sources" in text
    # One button covers them all: the helper leaves out whatever its own
    # refresh could not reach, so there is no per-source decision to make.
    assert _banner_button(window) == "Update without them"


def test_a_reachable_system_shows_no_banner(window):
    _apply(window, packages=_some_packages(3))
    assert not _banner_showing(window)


def test_an_unreachable_source_is_a_warning_not_an_error(window):
    """The headline still counts the updates, and the message is written in the
    window's own text rather than an orange bar. Somebody else's server being
    down for the afternoon is not something wrong with this computer, and the
    "Update now" dialog offers a way straight past it."""
    _apply(window, packages=_some_packages(43), failed_repos=[("vlc", "VLC")])

    assert "43 update(s) available" in window._headline.text()
    assert "#f67400" not in window._banner.styleSheet()


def test_the_things_that_are_actually_wrong_keep_the_orange(window):
    for kwargs in (
        {"error": "System management is locked by pid 5899", "locked": True},
        {"error": "zypper is not installed"},
    ):
        _apply(window, **kwargs)
        assert "#f67400" in window._banner.styleSheet(), kwargs

    # And the one that is not an error but is still a problem.
    _apply(window, packages=_some_packages(3), snapshots_ok=False)
    assert "#f67400" in window._banner.styleSheet()


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


def test_a_source_we_switched_off_is_offered_back(window, monkeypatch):
    """Nothing in this app switches a source off for good any more, but an
    older version did, and the note it left in the preferences has to keep
    working - that button is the whole way back for anyone who pressed it."""
    SettingsStore().set_disabled_sources(["vlc"])
    monkeypatch.setattr(
        "tumbleweed_updater.mainwindow.list_repos",
        lambda: ReposResult(repos=[Repo(alias="vlc", name="VLC", enabled=False)]),
    )
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


# --------------------------------------------------------------------------- #
# "Update now" with a source that cannot be reached.
#
# The way past the problem, offered where the user is already trying to get
# past it. It is a change to the machine, however briefly, so it is asked
# rather than assumed.
# --------------------------------------------------------------------------- #


def _press_update(win, monkeypatch, answer):
    """Press "Update now" and answer the unreachable-source dialog.

    *answer* is "leave out", "anyway" or "cancel". Returns the argv of the
    zypper step, or None if nothing was started.
    """
    started = {}
    monkeypatch.setattr(
        type(win._runner), "start", lambda self, steps: started.setdefault(
            "steps", steps
        )
    )

    asked = {}

    def fake_exec(self):
        asked["text"] = self.text()
        asked["title"] = self.windowTitle()
        wanted = {
            "leave out": QMessageBox.AcceptRole,
            "anyway": QMessageBox.DestructiveRole,
            "cancel": QMessageBox.RejectRole,
        }[answer]
        for button in self.buttons():
            if self.buttonRole(button) == wanted:
                asked["labels"] = [b.text() for b in self.buttons()]
                self.setResult(0)
                # clickedButton() reads back what exec() would have recorded.
                self.done(0)
                self._clicked = button
                return 0
        raise AssertionError(f"no button with role {wanted}")

    monkeypatch.setattr(QMessageBox, "exec", fake_exec)
    monkeypatch.setattr(
        QMessageBox, "clickedButton", lambda self: getattr(self, "_clicked", None)
    )
    win._on_update_clicked()
    steps = started.get("steps")
    asked["argv"] = steps[0].argv if steps else None
    return asked


def _ready_to_update(win, **kwargs):
    _apply(win, packages=_some_packages(43), **kwargs)
    win._chk_system.setChecked(True)


def test_an_unreachable_source_offers_to_leave_it_out_of_this_update(
    window, monkeypatch
):
    _ready_to_update(window, failed_repos=[("vlc", "VLC")])
    asked = _press_update(window, monkeypatch, "leave out")

    assert "VLC" in asked["title"]
    assert "--without-unreachable" in asked["argv"]
    # The words that matter: temporary, and nothing else changes.
    assert "this one update" in asked["text"]
    assert "switched back on" in asked["text"]
    for jargon in ("repository", "metadata", "zypper", "exit"):
        assert jargon not in asked["text"].lower(), jargon


def test_trying_anyway_leaves_the_source_in(window, monkeypatch):
    """Worth keeping: when zypper still has usable details on disk the upgrade
    works with the source left in, and leaving it out is then needless."""
    _ready_to_update(window, failed_repos=[("vlc", "VLC")])
    asked = _press_update(window, monkeypatch, "anyway")

    assert "--without-unreachable" not in asked["argv"]


def test_cancelling_the_question_starts_nothing(window, monkeypatch):
    _ready_to_update(window, failed_repos=[("vlc", "VLC")])
    asked = _press_update(window, monkeypatch, "cancel")

    assert asked["argv"] is None


def test_a_reachable_system_is_not_asked_anything(window, monkeypatch):
    _ready_to_update(window)
    started = {}
    monkeypatch.setattr(
        type(window._runner), "start", lambda self, steps: started.setdefault(
            "steps", steps
        )
    )

    def never(self):
        raise AssertionError("asked about sources when none were missing")

    monkeypatch.setattr(QMessageBox, "exec", never)
    window._on_update_clicked()
    assert "--without-unreachable" not in started["steps"][0].argv


def test_the_banner_button_runs_the_upgrade_without_the_source(window, monkeypatch):
    """No question this time: the button's own label already says what it will
    do, so asking again would be asking twice."""
    _ready_to_update(window, failed_repos=[("vlc", "VLC")])
    started = {}
    monkeypatch.setattr(
        type(window._runner), "start", lambda self, steps: started.setdefault(
            "steps", steps
        )
    )

    def never(self):
        raise AssertionError("asked again after the button already said so")

    monkeypatch.setattr(QMessageBox, "exec", never)
    window._banner_btn.click()

    assert "--without-unreachable" in started["steps"][0].argv


# --------------------------------------------------------------------------- #
# Two buttons offering an update have to say how they differ.
#
# Neither is greyed out. Leaving the source in is not a mistake: it is the one
# that works while zypper still has usable details for it on disk, and the app
# cannot tell in advance which case it is in.
# --------------------------------------------------------------------------- #


def test_the_window_button_says_it_keeps_the_source_in(window):
    _ready_to_update(window, failed_repos=[("vlc", "VLC")])

    assert _banner_button(window) == "Update without VLC"
    assert window._btn_update.text() == "Update with VLC anyway"
    assert window._btn_update.isEnabled()


def test_the_window_button_goes_back_to_normal_when_nothing_is_missing(window):
    _ready_to_update(window, failed_repos=[("vlc", "VLC")])
    _ready_to_update(window)

    assert window._btn_update.text() == "Update now…"


def test_several_missing_sources_get_the_plural_label(window):
    _ready_to_update(
        window, failed_repos=[("vlc", "VLC"), ("packman", "Packman")]
    )

    assert _banner_button(window) == "Update without them"
    assert window._btn_update.text() == "Update with them anyway"


def test_pressing_it_asks_nothing_and_keeps_the_source_in(window, monkeypatch):
    _ready_to_update(window, failed_repos=[("vlc", "VLC")])
    started = {}
    monkeypatch.setattr(
        type(window._runner), "start", lambda self, steps: started.setdefault(
            "steps", steps
        )
    )

    def never(self):
        raise AssertionError("asked again after the label already said so")

    monkeypatch.setattr(QMessageBox, "exec", never)
    window._btn_update.click()

    assert "--without-unreachable" not in started["steps"][0].argv


def test_the_question_survives_where_the_banner_is_saying_something_else(
    window, monkeypatch
):
    """A held package lock takes the banner's one button, so nothing has
    offered to leave the source out and the window's button still has the
    question to ask."""
    _apply(
        window,
        packages=_some_packages(43),
        failed_repos=[("vlc", "VLC")],
        error="System management is locked by pid 5899",
        locked=True,
    )
    window._chk_system.setChecked(True)

    assert _banner_button(window) == "Wait for it and retry"
    assert window._btn_update.text() == "Update now…"

    asked = _press_update(window, monkeypatch, "leave out")
    assert "--without-unreachable" in asked["argv"]


# --------------------------------------------------------------------------- #
# "Try again tomorrow".
#
# A source that cannot be reached is usually somebody else's server having a bad
# afternoon. Until it comes back there is nothing useful to do, so the user can
# stop being asked about it: the tray goes back to idle and the headline says
# when the app will look again.
# --------------------------------------------------------------------------- #


def _tomorrow() -> str:
    return (date.today() + timedelta(days=1)).strftime("%d/%m/%Y")


def _defer(win):
    """Press "Try again tomorrow"."""
    win._banner_btn_alt.click()


def test_an_unreachable_source_offers_to_put_it_off(window):
    _apply(window, packages=_some_packages(42), failed_repos=[("vlc", "VLC")])

    assert window._banner_btn_alt.isVisible() or not window._banner_btn_alt.isHidden()
    assert window._banner_btn_alt.text() == "Try again tomorrow"
    # Beside the other one, not instead of it.
    assert _banner_button(window) == "Update without VLC"


def test_putting_it_off_stores_tomorrow_and_says_so(window):
    _apply(window, packages=_some_packages(42), failed_repos=[("vlc", "VLC")])
    _defer(window)

    assert SettingsStore().deferred_until() == date.today() + timedelta(days=1)
    assert window._headline.text() == f"Update check deferred until {_tomorrow()}"


def test_putting_it_off_takes_the_tray_back_to_idle(window):
    seen = []
    window.stateChanged.connect(lambda state, tip: seen.append((state, tip)))
    _apply(window, packages=_some_packages(42), failed_repos=[("vlc", "VLC")])
    _defer(window)

    state, tooltip = seen[-1]
    assert state is TrayState.IDLE
    assert tooltip == f"Update check deferred until {_tomorrow()}"


def test_the_banner_shrinks_to_one_line_once_it_is_put_off(window):
    _apply(window, packages=_some_packages(42), failed_repos=[("vlc", "VLC")])
    _defer(window)

    text = window._banner_label.text()
    assert text == (
        f"VLC could not be reached. This was put off until {_tomorrow()}."
    )
    # Nothing left to press: "Check now" is the way back.
    assert _banner_button(window) == ""
    assert window._banner_btn_alt.isHidden()
    # And the window's own button goes back to its ordinary label.
    assert window._btn_update.text() == "Update now…"


def test_several_sources_are_named_in_the_one_line(window):
    _apply(
        window,
        packages=_some_packages(42),
        failed_repos=[("vlc", "VLC"), ("packman", "Packman")],
    )
    _defer(window)

    assert "2 of your software sources (VLC, Packman)" in window._banner_label.text()


def test_checking_now_clears_it(window):
    _apply(window, packages=_some_packages(42), failed_repos=[("vlc", "VLC")])
    _defer(window)
    window._on_check_clicked()

    assert SettingsStore().deferred_until() is None


def test_a_clean_check_lifts_it_by_itself(window):
    """The background check keeps running. If the source comes back there is
    nothing left to hide from, so the updates stop being hidden."""
    _apply(window, packages=_some_packages(42), failed_repos=[("vlc", "VLC")])
    _defer(window)

    _apply(window, packages=_some_packages(42))

    assert SettingsStore().deferred_until() is None
    assert window._headline.text() == "42 update(s) available"


def test_a_check_that_still_fails_keeps_it(window):
    _apply(window, packages=_some_packages(42), failed_repos=[("vlc", "VLC")])
    _defer(window)

    _apply(window, packages=_some_packages(42), failed_repos=[("vlc", "VLC")])

    assert SettingsStore().deferred_until() is not None
    assert window._headline.text() == f"Update check deferred until {_tomorrow()}"


def test_a_failed_check_is_not_hidden_behind_a_deferral(window):
    """Putting off a source that cannot be reached is not the same as putting
    off a check that did not run at all."""
    _apply(window, packages=_some_packages(42), failed_repos=[("vlc", "VLC")])
    _defer(window)

    _apply(
        window,
        failed_repos=[("vlc", "VLC")],
        error="System management is locked by pid 5899",
        locked=True,
    )

    assert window._headline.text() == "Could not check for system updates"
    assert "5899" in window._banner_label.text()
