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
    NEEDS_A_DECISION,
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
    SettingsStore().note_unreachable_sources([])


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
    text = window._banner_label.text()
    assert "using the package system" in text
    # zypper's own words for this name a pid, and it is usually one of ours.
    assert "3719" not in text


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


def test_one_unreachable_source_offers_nothing_but_the_deferral(window):
    """The banner has offered two things here over time, and both were traps:
    switching the source off for good, which orphaned everything installed from
    it, and leaving it out of one update, which does the same thing for the
    length of that update. Neither could work, because a source zypper has no
    usable details for is already equivalent to a disabled one. The update gets
    past it by itself now, so the only thing left to offer is waiting."""
    _apply(window, packages=_some_packages(43), failed_repos=[("vlc", "VLC")])

    assert _banner_button(window) == ""
    assert window._banner_btn_alt.text() == "Try again tomorrow"


def test_a_source_that_has_only_just_gone_is_a_passing_problem(window):
    text = _apply(
        window, packages=_some_packages(43), failed_repos=[("vlc", "VLC")]
    )

    assert "worth trying again tomorrow" in text
    assert "YaST" not in text


def _gone_since(days: int) -> str:
    return (date.today() - timedelta(days=days)).isoformat()


def test_a_source_that_has_been_gone_for_days_stops_being_one(window):
    """"Try again tomorrow" has by then been tried and did not work. The only
    thing that will help is changing the source, so the banner says so."""
    store = SettingsStore()
    store._s.setValue("sources/unreachableSince", [f"vlc|{_gone_since(4)}"])
    store._s.sync()

    text = _apply(
        window, packages=_some_packages(43), failed_repos=[("vlc", "VLC")]
    )

    assert "worth trying again tomorrow" not in text
    assert "not been reachable since" in text
    assert "replace or remove" in text
    assert "YaST → Software Repositories" in text
    # The first half is unchanged: the other updates are still fine.
    assert "The other 43 updates were checked as usual." in text


def test_the_wording_stays_patient_when_no_date_is_known(window):
    """Nothing on record - a fresh install, or an upgrade from a version that
    did not keep the dates. "Try again tomorrow" is the right thing to say when
    you do not know."""
    window._settings.note_unreachable_sources = lambda aliases: None
    text = _apply(
        window, packages=_some_packages(43), failed_repos=[("vlc", "VLC")]
    )

    assert "worth trying again tomorrow" in text


def test_the_oldest_of_several_sources_decides(window):
    store = SettingsStore()
    store._s.setValue(
        "sources/unreachableSince",
        [f"vlc|{_gone_since(9)}", f"packman|{_gone_since(0)}"],
    )
    store._s.sync()

    text = _apply(
        window,
        packages=_some_packages(43),
        failed_repos=[("vlc", "VLC"), ("packman", "Packman")],
    )

    assert "have not been reachable since" in text


def test_a_check_that_worked_out_nothing_at_all_names_the_source(window):
    """The one case the update cannot get itself past: the source is gone and
    the details on disk for it have gone stale too, so the solver has nothing
    to offer for the programs that came from it. sources.py can only say "a
    software source that is switched off or can't be reached"; here the window
    knows which one, and since when."""
    store = SettingsStore()
    store._s.setValue("sources/unreachableSince", [f"vlc|{_gone_since(11)}"])
    store._s.sync()

    text = _apply(
        window,
        error=NEEDS_A_DECISION,
        failed_repos=[("vlc", "VLC")],
    )

    assert NEEDS_A_DECISION not in text
    assert "VLC" in text
    assert "not been reachable since" in text
    assert "Replace or remove it in YaST → Software Repositories" in text
    # It is a real problem with this computer's software sources, so it keeps
    # the orange.
    assert "#f67400" in window._banner.styleSheet()


def test_a_stuck_check_says_nothing_about_the_other_updates(window):
    """The ordinary paragraph would claim "everything else was checked as
    usual", which is exactly what did not happen."""
    text = _apply(window, error=NEEDS_A_DECISION, failed_repos=[("vlc", "VLC")])

    assert "checked as usual" not in text
    assert "Try again tomorrow" not in text


def test_a_check_that_failed_for_its_own_reasons_keeps_its_message(window):
    """Only a check that came back with nothing *and* a missing source is
    rewritten. Anything else says what it says."""
    text = _apply(window, error="zypper is not installed")

    assert text == "zypper is not installed"


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
    assert "Packman" in text and "VLC" in text


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

    assert "using the package system" in text
    assert "5899" not in text
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
# Nothing is asked and nothing is offered, because there is no decision left to
# make: helper/run-update refreshes first and then runs the dup with
# --no-refresh, so the details already on this computer stand in for the source
# that is missing. The question that used to live here offered to switch that
# source off for the length of the upgrade, and could not work - see
# helper/run-update and tests/test_dupargs.py.
# --------------------------------------------------------------------------- #


def _ready_to_update(win, **kwargs):
    _apply(win, packages=_some_packages(43), **kwargs)
    win._chk_system.setChecked(True)


def _start_update(win, monkeypatch):
    """Press "Update now" and return the argv of the zypper step."""
    started = {}
    monkeypatch.setattr(
        type(win._runner), "start", lambda self, steps: started.setdefault(
            "steps", steps
        )
    )

    def never(self):
        raise AssertionError("asked the user a question")

    monkeypatch.setattr(QMessageBox, "exec", never)
    win._btn_update.click()
    steps = started.get("steps")
    return steps[0].argv if steps else None


def test_an_unreachable_source_asks_nothing_and_starts_the_upgrade(
    window, monkeypatch
):
    _ready_to_update(window, failed_repos=[("vlc", "VLC")])
    argv = _start_update(window, monkeypatch)

    assert argv is not None
    assert "--without-unreachable" not in argv


def test_the_window_button_keeps_its_ordinary_label(window):
    """It used to read "Update with VLC anyway", because the banner was
    offering the other half of a choice. There is no choice now."""
    _ready_to_update(window, failed_repos=[("vlc", "VLC")])

    assert window._btn_update.text() == "Update now…"
    assert window._btn_update.isEnabled()
    assert _banner_button(window) == ""


def test_a_reachable_system_is_not_asked_anything(window, monkeypatch):
    _ready_to_update(window)
    assert _start_update(window, monkeypatch) is not None


# --------------------------------------------------------------------------- #
# Two of our own jobs reaching for zypper's lock at once.
#
# Pressing "Update now" during a check used to start a second job wanting the
# same lock. One of them lost; when it was the check, it spent 40s on its
# retries and then replaced the window's list of updates with an orange bar
# naming our own zypper's pid.
# --------------------------------------------------------------------------- #


def _checking(win, monkeypatch, running=True):
    """Make the window believe a privileged check is in flight."""
    monkeypatch.setattr(
        type(win._privileged), "check_running", property(lambda self: running)
    )


def test_the_update_button_is_dead_while_a_check_runs(window, monkeypatch):
    _ready_to_update(window, failed_repos=[("vlc", "VLC")])
    assert window._btn_update.isEnabled()

    _checking(window, monkeypatch)
    window._set_busy(True, "Checking for updates…")

    assert not window._btn_update.isEnabled()


def test_the_update_button_comes_back_when_the_check_ends(window, monkeypatch):
    _ready_to_update(window)
    _checking(window, monkeypatch)
    window._set_busy(True, "")
    _checking(window, monkeypatch, running=False)
    window._set_busy(False, "")

    assert window._btn_update.isEnabled()


def test_a_press_that_got_through_anyway_starts_nothing(window, monkeypatch):
    """The button is not the only route here - the tray menu and a click
    already in flight both arrive at _on_update_clicked()."""
    _ready_to_update(window)
    started = {}
    monkeypatch.setattr(
        type(window._runner), "start", lambda self, steps: started.setdefault(
            "steps", steps
        )
    )
    _checking(window, monkeypatch)

    window._on_update_clicked()

    assert started == {}


# --------------------------------------------------------------------------- #
# A check that lost the lock keeps the list it could not replace.
# --------------------------------------------------------------------------- #


def _locked(win, **kwargs):
    return _apply(
        win,
        error="System management is locked by the application with pid 38917",
        locked=True,
        **kwargs,
    )


def test_a_locked_check_keeps_the_list_it_could_not_replace(window):
    _apply(window, packages=_some_packages(42))
    before = window._subline.text()

    text = _locked(window)

    assert window._headline.text() == "42 update(s) available"
    assert window._status.zypper.count == 42
    # "Last checked" belongs to the check that produced the list.
    assert window._subline.text() == before
    assert "42 updates below" in text
    assert "using the package system" in text


def test_a_locked_check_still_offers_the_way_out(window):
    _apply(window, packages=_some_packages(42))
    _locked(window)

    assert _banner_button(window) == "Wait for it and retry"
    assert "#f67400" in window._banner.styleSheet()


def test_a_locked_check_over_a_list_is_not_an_error_in_the_tray(window):
    seen = []
    _apply(window, packages=_some_packages(42))
    window.stateChanged.connect(lambda state, tip: seen.append((state, tip)))
    _locked(window)

    assert seen[-1] == (TrayState.UPDATES, "42 update(s) available")


def test_a_locked_check_with_nothing_to_keep_still_says_so(window):
    text = _locked(window)

    assert window._headline.text() == "Could not check for system updates"
    assert "Nothing on your computer has changed" in text


def test_any_other_failed_check_still_clears_the_list(window):
    """A lock says nothing about the system. Anything else means the app
    genuinely does not know what is installable."""
    _apply(window, packages=_some_packages(42))
    _apply(window, error="zypper is not installed")

    assert window._headline.text() == "Could not check for system updates"
    assert window._status.zypper.count == 0


def test_a_locked_check_does_not_restart_the_unreachable_clock(window):
    """It learnt nothing about the sources either, so taking its empty list
    would forget how long they had been away."""
    store = SettingsStore()
    store._s.setValue(
        "sources/unreachableSince",
        [f"vlc|{(date.today() - timedelta(days=9)).isoformat()}"],
    )
    store._s.sync()
    _apply(window, packages=_some_packages(42), failed_repos=[("vlc", "VLC")])

    _locked(window)

    assert SettingsStore().unreachable_since("vlc") == date.today() - timedelta(
        days=9
    )


def test_a_check_that_worked_replaces_the_kept_list(window):
    _apply(window, packages=_some_packages(42))
    _locked(window)
    _apply(window, packages=_some_packages(7))

    assert window._status.zypper.count == 7
    assert window._status.zypper.error is None
    assert not _banner_showing(window)


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
    # The only thing the banner offers now.
    assert _banner_button(window) == ""


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
    off a check that did not run at all. Set straight from the store rather
    than through the button, so the window has no earlier list to keep."""
    SettingsStore().set_deferred_until(date.today() + timedelta(days=1))

    _apply(
        window,
        failed_repos=[("vlc", "VLC")],
        error="System management is locked by pid 5899",
        locked=True,
    )

    assert window._headline.text() == "Could not check for system updates"
    assert "using the package system" in window._banner_label.text()
