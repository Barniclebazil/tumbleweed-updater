import os
from datetime import date, timedelta

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtWidgets import QApplication

from tumbleweed_updater.settings import (
    REBOOT_ACTIONS,
    RESET_AFTER_UPDATE,
    Prefs,
    SettingsStore,
    appearance_from_prefs,
    dup_args_from_prefs,
    interactive_dup_args,
)
from tumbleweed_updater import settings as settings_module
from tumbleweed_updater.konsole import KonsoleLook
from tumbleweed_updater.termthemes import THEMES


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
    SettingsStore().set_deferred_until(None)
    SettingsStore().note_unreachable_sources([])


def test_dup_args_default_empty():
    assert dup_args_from_prefs(Prefs()) == []


def test_dup_args_all_toggles():
    p = Prefs(
        dup_non_interactive=True,
        dup_allow_vendor_change=True,
    )
    assert dup_args_from_prefs(p) == [
        "-y",
        "--auto-agree-with-licenses",
        "--allow-vendor-change",
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
        cleanup_after_update=False,
        reboot_action="offer",
        icon_style="shield",
    )
    store.save(original)
    loaded = store.load()
    assert loaded.dup_allow_vendor_change is True
    assert loaded.dup_non_interactive is True
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
        cleanup_after_update=False,
        reboot_action="offer",
        reset_after_update="never",
        term_font_family="Fira Code",
        term_font_size=14,
        term_bg="#112233",
        term_fg="#eeeeee",
        term_theme="custom",
        term_palette="nord",
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


def test_saving_forgets_the_old_download_first_setting(app):
    """The "Download all packages before installing" tickbox is gone: libzypp
    downloads everything first by itself. Its key goes at the next save."""
    store = SettingsStore()
    store._s.setValue("zypper/downloadInAdvance", True)
    store.save(store.load())
    assert not store._s.contains("zypper/downloadInAdvance")
    assert "--download" not in dup_args_from_prefs(store.load())


def test_free_text_options_do_not_duplicate_the_toggles(app):
    """A duplicate option is dropped with its value, or a bare --download would
    be left behind to swallow the next argument. A typed value is never
    taken for a duplicate."""
    only_typed = Prefs(zypper_dup_args="--download in-advance")
    assert dup_args_from_prefs(only_typed) == ["--download", "in-advance"]

    flag = Prefs(dup_non_interactive=True, zypper_dup_args="-y --details")
    assert dup_args_from_prefs(flag) == ["-y", "--auto-agree-with-licenses", "--details"]


def test_packagekit_and_notifier_defaults(app):
    store = SettingsStore()
    p = store.load()
    # The notifier question starts unanswered. Waiting for PackageKit is no
    # longer a preference at all - it is what the helpers do.
    assert not hasattr(p, "wait_for_packagekit")
    assert p.plasma_notifier_asked is False


def test_packagekit_and_notifier_round_trip(app):
    store = SettingsStore()
    p = store.load()
    p.plasma_notifier_asked = True
    store.save(p)

    # QSettings hands booleans back as the strings "false"/"true" here, which
    # is what _as_bool exists for.
    assert store.load().plasma_notifier_asked is True


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


# --------------------------------------------------------------------------- #
# How long a software source has been unreachable.
#
# A source that is missing for an afternoon and one that has been missing for a
# fortnight need different things said about them, and the only way to tell
# them apart is to have written down when the first failed check was.
# --------------------------------------------------------------------------- #


def test_nothing_is_on_record_to_begin_with(app):
    assert SettingsStore().unreachable_since("vlc") is None


def test_a_newly_unreachable_source_is_dated_today(app):
    SettingsStore().note_unreachable_sources(["vlc"])
    assert SettingsStore().unreachable_since("vlc") == date.today()


def test_the_first_day_survives_later_checks(app):
    """The point of the record. Re-dating it on every check would mean it never
    grew older than a few hours."""
    store = SettingsStore()
    store._s.setValue("sources/unreachableSince", ["vlc|2026-09-16"])
    store._s.sync()

    store.note_unreachable_sources(["vlc", "packman"])

    assert store.unreachable_since("vlc") == date(2026, 9, 16)
    assert store.unreachable_since("packman") == date.today()


def test_a_source_that_came_back_is_forgotten(app):
    store = SettingsStore()
    store.note_unreachable_sources(["vlc", "packman"])
    store.note_unreachable_sources(["packman"])

    assert store.unreachable_since("vlc") is None
    assert store.unreachable_since("packman") == date.today()


def test_a_clean_check_clears_the_lot(app):
    store = SettingsStore()
    store.note_unreachable_sources(["vlc"])
    store.note_unreachable_sources([])

    assert store.unreachable_since("vlc") is None


def test_one_unreachable_source_reads_back_as_a_list(app):
    """The same QSettings quirk the disabled-sources list has to cope with."""
    SettingsStore().note_unreachable_sources(["vlc"])
    assert SettingsStore().unreachable_since("vlc") == date.today()


def test_an_unreadable_date_is_not_a_date(app):
    store = SettingsStore()
    store._s.setValue("sources/unreachableSince", ["vlc|not a date"])
    store._s.sync()
    assert store.unreachable_since("vlc") is None


def test_the_settings_dialog_cannot_clobber_the_dates(app):
    store = SettingsStore()
    store.note_unreachable_sources(["vlc"])
    store.save(Prefs())
    assert store.unreachable_since("vlc") == date.today()


# --------------------------------------------------------------------------- #
# Putting the check off for a day.
# --------------------------------------------------------------------------- #


def test_no_deferral_by_default(app):
    assert SettingsStore().deferred_until() is None


def test_a_deferral_round_trips(app):
    tomorrow = date.today() + timedelta(days=1)
    SettingsStore().set_deferred_until(tomorrow)

    assert SettingsStore().deferred_until() == tomorrow


def test_a_deferral_that_has_arrived_is_over(app):
    """The date shown is the day the check comes back, so on that day the
    deferral is spent. Reading it also clears it, rather than leaving a stale
    date in the config file for ever."""
    store = SettingsStore()
    store.set_deferred_until(date.today())

    assert store.deferred_until() is None
    assert store._s.value("check/deferredUntil", "", str) == ""


def test_yesterdays_deferral_is_over_too(app):
    store = SettingsStore()
    store.set_deferred_until(date.today() - timedelta(days=30))

    assert store.deferred_until() is None


def test_clearing_a_deferral(app):
    store = SettingsStore()
    store.set_deferred_until(date.today() + timedelta(days=1))
    store.set_deferred_until(None)

    assert store.deferred_until() is None


def test_a_damaged_deferral_is_discarded_rather_than_raised(app):
    """It is read on every render, so it must not be able to take the window
    down however the file got mangled."""
    store = SettingsStore()
    store._s.setValue("check/deferredUntil", "next tuesday")

    assert store.deferred_until() is None
    assert store._s.value("check/deferredUntil", "", str) == ""


def test_an_interactive_run_drops_only_the_options_that_stop_zypper_asking():
    args = dup_args_from_prefs(
        Prefs(
            dup_non_interactive=True,
            zypper_dup_args="--download in-advance --no-confirm --details",
        )
    )
    assert "-y" in args and "--no-confirm" in args

    assert interactive_dup_args(args) == [
        "--auto-agree-with-licenses",
        "--download",
        "in-advance",
        "--details",
    ]


# --------------------------------------------------------------------------- #
# Terminal themes
# --------------------------------------------------------------------------- #

def _old_style_config(store, bg=None, fg=None):
    """A config saved before there were themes: colours, and no theme key."""
    for key in ("term/theme", "term/palette", "term/bg", "term/fg"):
        store._s.remove(key)
    if bg is not None:
        store._s.setValue("term/bg", bg)
    if fg is not None:
        store._s.setValue("term/fg", fg)


def test_a_fresh_install_gets_the_tumbleweed_theme(app):
    store = SettingsStore()
    _old_style_config(store)
    p = store.load()
    assert (p.term_theme, p.term_palette) == ("tumbleweed", "tumbleweed")
    assert (p.term_bg, p.term_fg) == (THEMES["tumbleweed"].bg, THEMES["tumbleweed"].fg)


def test_the_old_default_colours_become_the_tumbleweed_theme(app):
    store = SettingsStore()
    _old_style_config(store, "#1b1b1b", "#f0f0f0")
    assert store.load().term_theme == "tumbleweed"


def test_colours_chosen_before_themes_stay_exactly_as_they_look(app):
    store = SettingsStore()
    _old_style_config(store, "#300a24", "#f0f0f0")
    p = store.load()
    assert (p.term_theme, p.term_palette) == ("custom", "breeze")
    assert (p.term_bg, p.term_fg) == ("#300a24", "#f0f0f0")
    a = appearance_from_prefs(p)
    assert (a.bg, a.fg, a.colours) == ("#300a24", "#f0f0f0", THEMES["breeze"].colours)


def test_a_junk_theme_falls_back_and_a_named_theme_uses_its_own_colours(app):
    store = SettingsStore()
    store._s.setValue("term/theme", "no-such-theme")
    store._s.setValue("term/palette", "custom")
    p = store.load()
    assert (p.term_theme, p.term_palette) == ("tumbleweed", "tumbleweed")

    store._s.setValue("term/theme", "nord")
    store._s.setValue("term/bg", "#123456")
    p = store.load()
    assert p.term_bg == THEMES["nord"].bg


def test_a_theme_gives_its_colours_and_the_users_font():
    a = appearance_from_prefs(
        Prefs(term_theme="gruvbox", term_font_family="Hack", term_font_size=12)
    )
    g = THEMES["gruvbox"]
    assert (a.font_family, a.font_size, a.bg, a.fg, a.colours) == (
        "Hack", 12, g.bg, g.fg, g.colours,
    )


def test_custom_keeps_the_other_colours_of_its_theme():
    a = appearance_from_prefs(
        Prefs(term_theme="custom", term_palette="ubuntu", term_bg="#000000", term_fg="#ffffff")
    )
    assert (a.bg, a.fg, a.colours) == ("#000000", "#ffffff", THEMES["ubuntu"].colours)


def test_konsole_gives_its_colours_and_its_font(monkeypatch):
    look = KonsoleLook("DarkPastels", THEMES["nord"], "Ubuntu Mono", 13, "a note")
    monkeypatch.setattr(settings_module, "read_konsole", lambda: look)

    a = appearance_from_prefs(Prefs(term_theme="konsole", term_font_family="Hack"))
    assert (a.font_family, a.font_size, a.bg, a.colours, a.note) == (
        "Ubuntu Mono", 13, THEMES["nord"].bg, THEMES["nord"].colours, "a note",
    )

    # Custom on Konsole's colours: the user's own font and background.
    a = appearance_from_prefs(
        Prefs(term_theme="custom", term_palette="konsole", term_bg="#010203",
              term_font_family="Hack", term_font_size=9)
    )
    assert (a.font_family, a.font_size, a.bg, a.colours) == (
        "Hack", 9, "#010203", THEMES["nord"].colours,
    )
