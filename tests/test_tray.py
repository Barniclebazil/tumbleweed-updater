"""What the status-area icon says, and when it says nothing.

Orange means exactly one thing: there are updates. A check used to turn it
orange too, which put a bright mark in the panel every few hours to announce
that the app was looking - attention asked for with nothing to say.
"""

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtWidgets import QApplication

from tumbleweed_updater.settings import SettingsStore
from tumbleweed_updater.tray import TrayIcon, TrayState


@pytest.fixture(scope="module")
def app():
    return QApplication.instance() or QApplication([])


@pytest.fixture
def tray(app, tmp_path, monkeypatch):
    # Both variables: Qt resolves QSettings through XDG_CONFIG_HOME first, so
    # patching HOME alone leaves this reading the real user's config.
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / ".config"))
    return TrayIcon(SettingsStore())


def _mark(tray) -> bytes:
    """The rendered icon, as something two states can be compared on."""
    image = tray.icon().pixmap(22, 22).toImage()
    return bytes(image.constBits())


def test_checking_does_not_change_a_quiet_icon(tray):
    tray.set_state(TrayState.IDLE, "Up to date")
    before = _mark(tray)

    tray.set_state(TrayState.CHECKING, "Checking for updates…")

    assert _mark(tray) == before


def test_checking_does_not_change_an_orange_icon_either(tray):
    """It keeps saying what it knew a moment ago, rather than resetting to
    "nothing to see" while the app confirms what it already found."""
    tray.set_state(TrayState.UPDATES, "42 update(s) available")
    before = _mark(tray)

    tray.set_state(TrayState.CHECKING, "Checking for updates…")

    assert _mark(tray) == before


def test_checking_still_says_so_in_the_tooltip(tray):
    tray.set_state(TrayState.UPDATES, "42 update(s) available")
    tray.set_state(TrayState.CHECKING, "Checking for updates…")

    assert "Checking for updates" in tray.toolTip()


def test_updates_and_installing_look_the_same(tray):
    """There are updates either way; during an install they are going in."""
    tray.set_state(TrayState.UPDATES, "42 update(s) available")
    orange = _mark(tray)

    tray.set_state(TrayState.INSTALLING, "Installing updates…")

    assert _mark(tray) == orange


def test_idle_does_not_look_like_updates(tray):
    tray.set_state(TrayState.UPDATES, "42 update(s) available")
    orange = _mark(tray)

    tray.set_state(TrayState.IDLE, "Up to date")

    assert _mark(tray) != orange


def test_the_menus_update_entry_is_dead_while_checking(tray):
    """It is what stops the tray menu starting an update while a check has
    zypper's lock - two of our own jobs reaching for it at once."""
    tray.set_state(TrayState.UPDATES, "42 update(s) available")
    assert tray.act_update.isEnabled()

    tray.set_state(TrayState.CHECKING, "Checking for updates…")
    assert not tray.act_update.isEnabled()

    # The window emits the real state when the check ends, which brings it back.
    tray.set_state(TrayState.UPDATES, "42 update(s) available")
    assert tray.act_update.isEnabled()


def test_the_menus_update_entry_is_dead_while_installing(tray):
    tray.set_state(TrayState.INSTALLING, "Installing updates…")
    assert not tray.act_update.isEnabled()
