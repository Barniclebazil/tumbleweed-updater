import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtWidgets import QApplication

from tumbleweed_updater.settings import (
    REBOOT_ACTIONS,
    Prefs,
    SettingsStore,
    dup_args_from_prefs,
)


@pytest.fixture(scope="module")
def app():
    return QApplication.instance() or QApplication([])


@pytest.fixture(autouse=True)
def isolated_config_home(tmp_path, monkeypatch):
    """Redirect QSettings into a throwaway directory for every test here.

    Qt resolves the config path via $XDG_CONFIG_HOME first and only falls
    back to $HOME/.config if that is unset - on a normal desktop session
    (this machine included) XDG_CONFIG_HOME is set independently of HOME, so
    patching HOME alone does *not* isolate QSettings: it silently keeps
    writing to the real ~/.config/org.opensuse.TumbleweedUpdater file. Both
    variables must be patched together.
    """
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / ".config"))


def test_dup_args_default_empty():
    assert dup_args_from_prefs(Prefs()) == []


def test_dup_args_all_toggles():
    p = Prefs(
        dup_non_interactive=True,
        dup_allow_vendor_change=True,
        dup_download_in_advance=True,
    )
    assert dup_args_from_prefs(p) == [
        "-y",
        "--auto-agree-with-licenses",
        "--allow-vendor-change",
        "--download",
        "in-advance",
    ]


def test_dup_args_dedupes_free_text():
    p = Prefs(dup_non_interactive=True, zypper_dup_args="-y --no-recommends")
    args = dup_args_from_prefs(p)
    assert args.count("-y") == 1
    assert "--no-recommends" in args


def test_settings_roundtrip(app):
    store = SettingsStore()
    original = Prefs(
        dup_allow_vendor_change=True,
        dup_non_interactive=True,
        dup_download_in_advance=True,
        cleanup_after_update=False,
        reboot_action="offer",
        icon_style="shield",
    )
    store.save(original)
    loaded = store.load()
    assert loaded.dup_allow_vendor_change is True
    assert loaded.dup_non_interactive is True
    assert loaded.dup_download_in_advance is True
    assert loaded.cleanup_after_update is False
    assert loaded.reboot_action == "offer"
    assert loaded.icon_style == "shield"


def test_settings_roundtrip_every_field(app):
    """Every Prefs field, not just a subset, must survive a save/load cycle."""
    store = SettingsStore()
    original = Prefs(
        check_interval="weekly",
        check_on_launch=False,
        start_in_tray=False,
        notify_on_updates=False,
        zypper_dup_args="--no-recommends",
        include_flatpak=False,
        dup_allow_vendor_change=True,
        dup_non_interactive=True,
        dup_download_in_advance=True,
        cleanup_after_update=False,
        reboot_action="offer",
        term_font_family="Fira Code",
        term_font_size=14,
        term_bg="#112233",
        term_fg="#eeeeee",
        icon_style="package",
    )
    store.save(original)
    loaded = store.load()
    assert loaded == original


def test_settings_persist_across_separate_stores(app):
    """A second, independent SettingsStore (as a later app launch would create)
    must see what an earlier one saved - this is the actual persistence
    guarantee the app relies on across restarts/upgrades."""
    original = Prefs(icon_style="arrow", term_font_size=16, notify_on_updates=False)
    SettingsStore().save(original)
    reloaded = SettingsStore().load()
    assert reloaded == original


def test_reboot_action_falls_back_on_junk(app):
    store = SettingsStore()
    p = Prefs()
    p.reboot_action = "not-a-real-action"
    store.save(p)
    assert store.load().reboot_action in REBOOT_ACTIONS


def test_cleanup_default_is_on():
    assert Prefs().cleanup_after_update is True
    assert Prefs().dup_allow_vendor_change is False
    assert Prefs().dup_non_interactive is False
    assert Prefs().dup_download_in_advance is False
