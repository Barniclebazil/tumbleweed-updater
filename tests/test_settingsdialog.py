"""Preferences dialog: the parts with rules behind them."""

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest

from PySide6.QtCore import QObject, Signal
from PySide6.QtWidgets import QApplication, QMessageBox

from tumbleweed_updater import autostart
from tumbleweed_updater.settings import SettingsStore
from tumbleweed_updater.settingsdialog import SettingsDialog


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


def _fake_plasma_entry(tmp_path, monkeypatch):
    system = tmp_path / "xdg-autostart"
    system.mkdir(exist_ok=True)
    (system / autostart.PLASMA_NOTIFIER_ENTRY).write_text(
        "[Desktop Entry]\nType=Application\nName=Discover\n"
        "Exec=/usr/libexec/DiscoverNotifier --check-delay 20\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(autostart, "SYSTEM_AUTOSTART_DIRS", (str(system),))
    # Nothing in the tests may signal a real process.
    monkeypatch.setattr(autostart, "stop_notifier", lambda *a, **k: 0)


def test_notifier_row_is_absent_without_a_system_entry(app, store, tmp_path, monkeypatch):
    monkeypatch.setattr(autostart, "SYSTEM_AUTOSTART_DIRS", (str(tmp_path / "none"),))
    dialog = SettingsDialog(store, _StubRunner())
    assert dialog._no_notifier is None
    dialog._save()  # must not blow up on the missing widget
    dialog.close()


def test_notifier_tickbox_mirrors_the_override_on_disk(app, store, tmp_path, monkeypatch):
    _fake_plasma_entry(tmp_path, monkeypatch)
    autostart.set_hidden(autostart.PLASMA_NOTIFIER_ENTRY, True)

    dialog = SettingsDialog(store, _StubRunner())
    assert dialog._no_notifier.isChecked() is True
    dialog.close()


def test_saving_writes_and_removes_the_override(app, store, tmp_path, monkeypatch):
    _fake_plasma_entry(tmp_path, monkeypatch)
    override = tmp_path / "autostart" / autostart.PLASMA_NOTIFIER_ENTRY

    dialog = SettingsDialog(store, _StubRunner())
    dialog._no_notifier.setChecked(True)
    dialog._save()
    assert "Hidden=true" in override.read_text(encoding="utf-8")
    assert store.load().plasma_notifier_asked is True
    dialog.close()

    dialog = SettingsDialog(store, _StubRunner())
    dialog._no_notifier.setChecked(False)
    dialog._save()
    assert not override.exists()
    dialog.close()


def test_saving_does_not_reset_the_one_time_question(app, store, tmp_path, monkeypatch):
    """_save() rebuilds Prefs field by field, so a field with no widget is one
    typo away from being silently reset."""
    monkeypatch.setattr(autostart, "SYSTEM_AUTOSTART_DIRS", (str(tmp_path / "none"),))
    prefs = store.load()
    prefs.plasma_notifier_asked = True
    store.save(prefs)

    dialog = SettingsDialog(store, _StubRunner())
    dialog._save()
    assert store.load().plasma_notifier_asked is True
    dialog.close()


def test_packagekit_wait_round_trips(app, store, tmp_path, monkeypatch):
    monkeypatch.setattr(autostart, "SYSTEM_AUTOSTART_DIRS", (str(tmp_path / "none"),))

    dialog = SettingsDialog(store, _StubRunner())
    dialog._wait_for_pk.setChecked(False)
    dialog._save()
    assert store.load().wait_for_packagekit is False
    dialog.close()

    dialog = SettingsDialog(store, _StubRunner())
    assert dialog._wait_for_pk.isChecked() is False
    dialog._wait_for_pk.setChecked(True)
    dialog._save()
    assert store.load().wait_for_packagekit is True
    dialog.close()
