"""Preferences dialog: the parts with rules behind them."""

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest

from PySide6.QtCore import QObject, Signal
from PySide6.QtWidgets import QApplication, QCheckBox, QMessageBox

from tumbleweed_updater import autostart, dialogs
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


def test_there_is_no_packagekit_row(app, store, tmp_path, monkeypatch):
    """It was a switch whose only sensible setting was on, and one the
    scheduled check could not read anyway, since it runs as root from a timer
    with no session. Waiting is now what the helpers do, so there is nothing
    here to decide."""
    monkeypatch.setattr(autostart, "SYSTEM_AUTOSTART_DIRS", (str(tmp_path / "none"),))

    dialog = SettingsDialog(store, _StubRunner())
    labels = [box.text() for box in dialog.findChildren(QCheckBox)]
    assert not any("PackageKit" in text for text in labels), labels
    dialog.close()


class _RecordingRunner(_StubRunner):
    def __init__(self) -> None:
        super().__init__()
        self.calls = []

    def set_interval(self, label: str) -> bool:
        self.calls.append(label)
        return True


def test_a_refused_schedule_change_keeps_the_old_schedule(app, store, monkeypatch):
    """Everything else is saved before the helper is asked. When it then fails
    (a dismissed password prompt, say) the stored cadence must go back to the
    one the timer is still running, or Settings shows a schedule the system
    never adopted."""
    monkeypatch.setattr(dialogs, "show_failure", lambda *a, **k: None)
    before = store.load().check_interval
    runner = _RecordingRunner()
    dialog = SettingsDialog(store, runner)
    other = next(label for label in ("daily", "weekly") if label != before)
    dialog._interval.setCurrentIndex(dialog._interval.findData(other))

    dialog._save()
    assert runner.calls == [other]
    assert not dialog._buttons.isEnabled(), "no second Save while one is pending"

    runner.intervalFinished.emit(False, "Not authorised")

    assert store.load().check_interval == before


def test_an_accepted_schedule_change_is_kept(app, store):
    runner = _RecordingRunner()
    dialog = SettingsDialog(store, runner)
    wanted = "weekly" if store.load().check_interval != "weekly" else "daily"
    dialog._interval.setCurrentIndex(dialog._interval.findData(wanted))

    dialog._save()
    runner.intervalFinished.emit(True, "")

    assert store.load().check_interval == wanted


# --------------------------------------------------------------------------- #
# Terminal themes
# --------------------------------------------------------------------------- #

from tumbleweed_updater import settingsdialog as settingsdialog_module  # noqa: E402
from tumbleweed_updater.konsole import KonsoleLook  # noqa: E402
from tumbleweed_updater.termthemes import THEMES  # noqa: E402


@pytest.fixture
def konsole(monkeypatch):
    look = KonsoleLook("Ubuntu Breeze", THEMES["ubuntu"], "DejaVu Sans Mono", 13)
    monkeypatch.setattr(settingsdialog_module, "read_konsole", lambda: look)
    return look


def _choose(dialog, key):
    dialog._theme.setCurrentIndex(dialog._theme.findData(key))


def _buttons(dialog):
    return dialog._bg_btn.color_name(), dialog._fg_btn.color_name()


def test_the_theme_list_starts_with_konsole_and_ends_with_custom(app, store, konsole):
    dialog = SettingsDialog(store, _StubRunner())
    keys = [dialog._theme.itemData(i) for i in range(dialog._theme.count())]
    assert keys == ["konsole", *THEMES, "custom"]
    assert dialog._theme.itemText(0) == "Same as Konsole (Ubuntu Breeze)"
    dialog.close()


def test_choosing_a_theme_fills_in_the_colours_and_saves_it(app, store, konsole):
    dialog = SettingsDialog(store, _StubRunner())
    _choose(dialog, "nord")
    assert _buttons(dialog) == (THEMES["nord"].bg, THEMES["nord"].fg)
    assert dialog._theme.currentData() == "nord", "filling in is not a change"

    dialog._save()
    p = store.load()
    assert (p.term_theme, p.term_palette, p.term_bg) == ("nord", "nord", THEMES["nord"].bg)


def test_changing_a_colour_makes_it_custom_and_keeps_the_other_colours(app, store, konsole):
    dialog = SettingsDialog(store, _StubRunner())
    _choose(dialog, "ubuntu")
    dialog._bg_btn.set_color("#000000")

    assert dialog._theme.currentData() == "custom"
    assert _buttons(dialog) == ("#000000", THEMES["ubuntu"].fg)
    dialog._save()
    p = store.load()
    assert (p.term_theme, p.term_palette, p.term_bg) == ("custom", "ubuntu", "#000000")


def test_konsole_shows_its_font_greyed_and_saves_the_users_own(app, store, konsole):
    dialog = SettingsDialog(store, _StubRunner())
    _choose(dialog, "breeze")
    dialog._use_system_font.setChecked(False)
    dialog._font_family.setCurrentFont(dialog._font_family.currentFont())
    own_family = dialog._chosen_font_family()
    dialog._font_size.setValue(9)

    _choose(dialog, "konsole")
    assert _buttons(dialog) == (THEMES["ubuntu"].bg, THEMES["ubuntu"].fg)
    assert dialog._font_size.value() == 13
    assert not dialog._font_size.isEnabled()
    assert not dialog._use_system_font.isEnabled()
    assert not dialog._font_family.isEnabled()

    dialog._save()
    p = store.load()
    assert p.term_theme == "konsole"
    assert (p.term_font_family, p.term_font_size) == (own_family, 9)

    # Leaving Konsole gives the user's own font back, ready to change.
    _choose(dialog, "tumbleweed")
    assert dialog._font_size.value() == 9
    assert dialog._font_size.isEnabled() and dialog._font_family.isEnabled()
    dialog.close()


def test_reset_goes_back_to_tumbleweed_and_the_system_font(app, store, konsole):
    dialog = SettingsDialog(store, _StubRunner())
    _choose(dialog, "konsole")
    dialog._reset_terminal()

    assert dialog._theme.currentData() == "tumbleweed"
    assert _buttons(dialog) == (THEMES["tumbleweed"].bg, THEMES["tumbleweed"].fg)
    assert dialog._use_system_font.isChecked()
    assert dialog._font_size.value() == 10
    assert dialog._font_size.isEnabled()
    dialog.close()


def test_the_preview_uses_the_themes_own_colours(app, store, konsole):
    dialog = SettingsDialog(store, _StubRunner())
    _choose(dialog, "gruvbox")
    assert THEMES["gruvbox"].colours[2] in dialog._preview_label.text()
    _choose(dialog, "konsole")
    assert THEMES["ubuntu"].colours[2] in dialog._preview_label.text()
    dialog.close()


@pytest.mark.parametrize("theme, palette", [("tumbleweed", "tumbleweed"), ("konsole", "konsole"), ("custom", "nord")])
def test_the_dialog_builds_without_an_error_from_any_saved_theme(app, store, konsole, monkeypatch, theme, palette):
    """An error in a slot is only printed by Qt, never raised, so it is caught
    here through sys.excepthook. The preview once ran before the dialog knew
    its palette."""
    import sys

    errors = []
    monkeypatch.setattr(sys, "excepthook", lambda *exc: errors.append(exc))
    store._s.setValue("term/theme", theme)
    store._s.setValue("term/palette", palette)
    dialog = SettingsDialog(store, _StubRunner())
    assert errors == []
    assert dialog._theme.currentData() == theme
    dialog.close()


def test_the_window_names_only_itself(app, store):
    """Qt adds " — Tumbleweed Updater" to the title on Linux, so a title that
    named the app as well showed it twice and was cut short."""
    dialog = SettingsDialog(store, _StubRunner())
    assert dialog.windowTitle() == "Settings"
    dialog.close()
