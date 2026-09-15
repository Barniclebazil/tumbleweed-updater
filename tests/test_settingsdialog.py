"""Preferences dialog: the parts with rules behind them."""

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest

from PySide6.QtCore import QObject, Signal
from PySide6.QtWidgets import QApplication, QMessageBox

from tumbleweed_updater.settings import SettingsStore
from tumbleweed_updater.settingsdialog import SettingsDialog, _desktop_exec


class _StubRunner(QObject):
    intervalFinished = Signal(bool, str)

    def set_interval(self, label: str) -> bool:
        return True


@pytest.fixture(scope="module")
def app():
    return QApplication.instance() or QApplication([])


@pytest.fixture(autouse=True)
def isolated_config_home(tmp_path, monkeypatch):
    # Both variables, for the reason spelled out in test_settings.py: Qt
    # prefers XDG_CONFIG_HOME, so patching HOME alone leaves QSettings writing
    # to the real file. The autostart entry follows the same two variables.
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))


@pytest.fixture
def store(isolated_config_home):
    return SettingsStore()


def test_an_option_the_helper_would_refuse_is_caught_at_save(app, store, monkeypatch):
    """helper/run-update rejects anything outside its allow-list. Saying so
    here names the offending word while the user can still fix it."""
    warned = []
    monkeypatch.setattr(
        QMessageBox, "warning", staticmethod(lambda *a, **k: warned.append(a[2]))
    )
    dialog = SettingsDialog(store, _StubRunner())
    dialog._dup_args.setText("--root /")

    dialog._save()

    assert warned and "--root" in warned[0]
    assert dialog.result() == 0, "the dialog must stay open"
    assert store.load().zypper_dup_args == "", "nothing may be saved"
    dialog.close()


def test_an_allowed_option_saves(app, store):
    dialog = SettingsDialog(store, _StubRunner())
    dialog._dup_args.setText("--no-recommends")

    dialog._save()

    assert store.load().zypper_dup_args == "--no-recommends"
    dialog.close()


def test_reset_after_update_saves_the_key_not_the_label(app, store):
    """The combo shows a sentence; what is persisted has to be the key that
    MainWindow compares against."""
    dialog = SettingsDialog(store, _StubRunner())
    idx = dialog._reset_after.findData("on_finish")
    assert idx >= 0, "every RESET_AFTER_UPDATE key must be offered"
    dialog._reset_after.setCurrentIndex(idx)

    dialog._save()

    assert store.load().reset_after_update == "on_finish"
    dialog.close()


def test_autostart_exec_is_quoted_when_it_has_to_be():
    assert _desktop_exec("/usr/bin/tumbleweed-updater") == "/usr/bin/tumbleweed-updater"
    assert _desktop_exec("/home/a b/tw") == '"/home/a b/tw"'
    assert _desktop_exec("/opt/$x/tw") == '"/opt/\\$x/tw"'


def test_autostart_entry_follows_xdg_config_home(app, store, tmp_path, monkeypatch):
    """Writing it must go through XDG_CONFIG_HOME, not a ~/.config pinned at
    import time - otherwise a test run rewrites the real user's entry."""
    monkeypatch.setattr(
        "tumbleweed_updater.settingsdialog.shutil.which", lambda _n: "/usr/bin/tw"
    )
    target = tmp_path / "autostart" / "tumbleweed-updater.desktop"

    SettingsDialog._apply_autostart(True)
    assert "Exec=/usr/bin/tw --tray" in target.read_text(encoding="utf-8")

    SettingsDialog._apply_autostart(False)
    assert not target.exists()
