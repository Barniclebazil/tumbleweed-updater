import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtWidgets import QApplication

from tumbleweed_updater.settings import (
    REBOOT_ACTIONS,
    RESET_AFTER_UPDATE,
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
    # Setting these is not enough on its own: Qt resolves the config directory
    # once per process and caches it, so every test after the first keeps
    # writing to the first one's file. Tests that write before they read are
    # unaffected, but anything checking a default has to start from a known
    # state, so the keys that are not written by every test are cleared here.
    SettingsStore().set_disabled_sources([])


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
        notify_on_updates=False,
        zypper_dup_args="--no-recommends",
        include_flatpak=False,
        dup_allow_vendor_change=True,
        dup_non_interactive=True,
        dup_download_in_advance=True,
        cleanup_after_update=False,
        reboot_action="offer",
        reset_after_update="never",
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


def test_reset_after_update_falls_back_on_junk(app):
    store = SettingsStore()
    p = Prefs()
    p.reset_after_update = "not-a-real-mode"
    store.save(p)
    assert store.load().reset_after_update in RESET_AFTER_UPDATE


def test_reset_after_update_defaults_to_clearing_on_close():
    """The app hides to the tray rather than quitting, so out of the box the
    window must not reopen still showing the last update's transcript."""
    assert Prefs().reset_after_update == "on_close"
    assert "on_close" in RESET_AFTER_UPDATE


def test_cleanup_default_is_on():
    assert Prefs().cleanup_after_update is True
    assert Prefs().dup_allow_vendor_change is False
    assert Prefs().dup_non_interactive is False
    assert Prefs().dup_download_in_advance is False


def test_free_text_options_do_not_duplicate_the_toggles(app):
    """A duplicate option is dropped with its value, or a bare --download would
    be left behind to swallow the next argument."""
    both = Prefs(dup_download_in_advance=True, zypper_dup_args="--download in-advance --details")
    assert dup_args_from_prefs(both) == ["--download", "in-advance", "--details"]

    only_typed = Prefs(zypper_dup_args="--download in-advance")
    assert dup_args_from_prefs(only_typed) == ["--download", "in-advance"]

    flag = Prefs(dup_non_interactive=True, zypper_dup_args="-y --details")
    assert dup_args_from_prefs(flag) == ["-y", "--auto-agree-with-licenses", "--details"]


def test_packagekit_and_notifier_defaults(app):
    store = SettingsStore()
    p = store.load()
    # Both features are on out of the box; the notifier question is unanswered.
    assert p.wait_for_packagekit is True
    assert p.plasma_notifier_asked is False


def test_packagekit_and_notifier_round_trip(app):
    store = SettingsStore()
    p = store.load()
    p.wait_for_packagekit = False
    p.plasma_notifier_asked = True
    store.save(p)

    # QSettings hands booleans back as the strings "false"/"true" here, which
    # is what _as_bool exists for.
    loaded = store.load()
    assert loaded.wait_for_packagekit is False
    assert loaded.plasma_notifier_asked is True


# --------------------------------------------------------------------------- #
# Software sources this app switched off.
#
# Kept off Prefs on purpose: the settings dialog rebuilds Prefs field by field
# from its widgets, so a field with no widget resets the day someone forgets to
# carry it across. These tests pin the accessors down instead.
# --------------------------------------------------------------------------- #


def test_disabled_sources_default_to_none(app):
    assert SettingsStore().disabled_sources() == []


def test_disabled_sources_round_trip(app):
    store = SettingsStore()
    store.set_disabled_sources(["vlc", "packman"])
    assert SettingsStore().disabled_sources() == ["packman", "vlc"]


def test_a_single_disabled_source_reads_back_as_a_list(app):
    """QSettings hands a one-element list back as a bare string on some
    backends, which would otherwise be read as a list of characters."""
    store = SettingsStore()
    store.set_disabled_sources(["vlc"])
    assert SettingsStore().disabled_sources() == ["vlc"]


def test_disabled_sources_are_deduplicated(app):
    store = SettingsStore()
    store.set_disabled_sources(["vlc", "vlc", "packman"])
    assert store.disabled_sources() == ["packman", "vlc"]


def test_the_settings_dialog_cannot_clobber_the_disabled_sources(app):
    """save() writes every Prefs field; this list is not one of them, so a
    round trip through the dialog leaves it alone."""
    store = SettingsStore()
    store.set_disabled_sources(["vlc"])
    store.save(Prefs())
    assert store.disabled_sources() == ["vlc"]
