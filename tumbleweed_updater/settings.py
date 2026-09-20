"""User-facing configuration, persisted with QSettings.

Only preferences that belong to the logged-in user live here. The *system*
check cadence is enforced by a systemd timer; this module just remembers which
cadence the user picked. The label->schedule mapping lives in
:mod:`tumbleweed_updater.intervals` so the privileged helper can share it.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date

from PySide6.QtCore import QSettings

from . import APP_ID
from .dupargs import VALUED
from .intervals import DEFAULT_INTERVAL, INTERVALS, oncalendar_for

__all__ = [
    "Prefs",
    "SettingsStore",
    "INTERVALS",
    "DEFAULT_INTERVAL",
    "oncalendar_for",
    "DEFAULT_TERM_BG",
    "DEFAULT_TERM_FG",
    "DEFAULT_TERM_FONT_SIZE",
    "ICON_STYLES",
    "DEFAULT_ICON_STYLE",
    "REBOOT_ACTIONS",
    "RESET_AFTER_UPDATE",
    "dup_args_from_prefs",
]

# What to do when an upgrade reports that a reboot is needed.
REBOOT_ACTIONS = {
    "notify": "Just tell me",
    "offer": "Offer to reboot now",
}
DEFAULT_REBOOT_ACTION = "notify"

# When to put the window back into its just-launched state - terminal cleared,
# log panel collapsed. The app hides to the tray rather than quitting, so
# without this the last update's transcript stays on screen for the life of
# the process. A failed run keeps its log whatever this says: the transcript
# is the only record of why it failed.
RESET_AFTER_UPDATE = {
    "on_close": "When I close it to the tray",
    "on_finish": "As soon as the update finishes",
    "never": "Never — keep the log until I clear it",
}
DEFAULT_RESET_AFTER_UPDATE = "on_close"


# Terminal appearance defaults. An empty font family means "the system's
# fixed-width font".
DEFAULT_TERM_BG = "#1b1b1b"
DEFAULT_TERM_FG = "#f0f0f0"
DEFAULT_TERM_FONT_SIZE = 10

# Tray/window icon styles -> label. Each name has a matching
# data/icons/styles/<name>.svg (monochrome; currentColor as the stroke for the
# line-art styles, as the fill for the two openSUSE logos).
ICON_STYLES = {
    "tumbleweed": "Tumbleweed",
    "opensuse": "openSUSE",
    "refresh": "Refresh arrows",
    "arrow": "Up arrow",
    "shield": "Shield",
    "package": "Package box",
}
DEFAULT_ICON_STYLE = "tumbleweed"


@dataclass
class Prefs:
    check_interval: str = DEFAULT_INTERVAL
    check_on_launch: bool = True
    notify_on_updates: bool = True
    # Extra arguments appended to ``zypper dup`` (advanced; empty by default).
    zypper_dup_args: str = ""
    include_flatpak: bool = True
    # Update behaviour toggles (all map to well-known zypper dup options).
    dup_allow_vendor_change: bool = False
    dup_non_interactive: bool = False
    dup_download_in_advance: bool = False
    cleanup_after_update: bool = True
    reboot_action: str = DEFAULT_REBOOT_ACTION  # key of REBOOT_ACTIONS
    # When the window returns to its clean state (key of RESET_AFTER_UPDATE).
    reset_after_update: str = DEFAULT_RESET_AFTER_UPDATE
    # Embedded-terminal appearance.
    term_font_family: str = ""
    term_font_size: int = DEFAULT_TERM_FONT_SIZE
    term_bg: str = DEFAULT_TERM_BG
    term_fg: str = DEFAULT_TERM_FG
    # Tray/window icon style (key of ICON_STYLES).
    icon_style: str = DEFAULT_ICON_STYLE
    # Whether the one-time question about Plasma's own update notifier has been
    # answered. Whether it is actually switched off is not stored here - that
    # is read from the autostart override on disk, since the user can also
    # change it from Plasma's own settings.
    plasma_notifier_asked: bool = False


class SettingsStore:
    def __init__(self) -> None:
        self._s = QSettings(APP_ID, "tumbleweed-updater")

    def load(self) -> Prefs:
        d = Prefs()
        s = self._s
        interval = s.value("check/interval", d.check_interval, str)
        if interval not in INTERVALS:
            interval = d.check_interval
        return Prefs(
            check_interval=interval,
            check_on_launch=_as_bool(s.value("check/onLaunch", d.check_on_launch)),
            notify_on_updates=_as_bool(s.value("ui/notify", d.notify_on_updates)),
            zypper_dup_args=s.value("zypper/dupArgs", d.zypper_dup_args, str),
            include_flatpak=_as_bool(s.value("flatpak/include", d.include_flatpak)),
            term_font_family=s.value("term/fontFamily", d.term_font_family, str),
            term_font_size=_as_int(
                s.value("term/fontSize", d.term_font_size), d.term_font_size
            ),
            term_bg=s.value("term/bg", d.term_bg, str) or d.term_bg,
            term_fg=s.value("term/fg", d.term_fg, str) or d.term_fg,
            icon_style=_one_of(
                s.value("ui/iconStyle", d.icon_style, str), ICON_STYLES, d.icon_style
            ),
            dup_allow_vendor_change=_as_bool(
                s.value("zypper/allowVendorChange", d.dup_allow_vendor_change)
            ),
            dup_non_interactive=_as_bool(
                s.value("zypper/nonInteractive", d.dup_non_interactive)
            ),
            dup_download_in_advance=_as_bool(
                s.value("zypper/downloadInAdvance", d.dup_download_in_advance)
            ),
            cleanup_after_update=_as_bool(
                s.value("update/cleanup", d.cleanup_after_update)
            ),
            reboot_action=_one_of(
                s.value("update/rebootAction", d.reboot_action, str),
                REBOOT_ACTIONS,
                d.reboot_action,
            ),
            reset_after_update=_one_of(
                s.value("update/resetAfter", d.reset_after_update, str),
                RESET_AFTER_UPDATE,
                d.reset_after_update,
            ),
            plasma_notifier_asked=_as_bool(
                s.value("ui/plasmaNotifierAsked", d.plasma_notifier_asked)
            ),
        )

    def save(self, p: Prefs) -> None:
        s = self._s
        s.setValue("check/interval", p.check_interval)
        s.setValue("check/onLaunch", p.check_on_launch)
        s.setValue("ui/notify", p.notify_on_updates)
        s.setValue("zypper/dupArgs", p.zypper_dup_args)
        s.setValue("flatpak/include", p.include_flatpak)
        s.setValue("term/fontFamily", p.term_font_family)
        s.setValue("term/fontSize", p.term_font_size)
        s.setValue("term/bg", p.term_bg)
        s.setValue("term/fg", p.term_fg)
        s.setValue("ui/iconStyle", p.icon_style)
        s.setValue("zypper/allowVendorChange", p.dup_allow_vendor_change)
        s.setValue("zypper/nonInteractive", p.dup_non_interactive)
        s.setValue("zypper/downloadInAdvance", p.dup_download_in_advance)
        s.setValue("update/cleanup", p.cleanup_after_update)
        s.setValue("update/rebootAction", p.reboot_action)
        s.setValue("update/resetAfter", p.reset_after_update)
        s.setValue("ui/plasmaNotifierAsked", p.plasma_notifier_asked)
        s.sync()

    # Software sources this app switched off, by zypper alias.
    #
    # Deliberately not a Prefs field: the settings dialog rebuilds Prefs field
    # by field from its widgets, so anything without a widget has to be carried
    # across by hand and resets silently the day someone forgets. This list is
    # written from the main window, never from the dialog, so it gets its own
    # pair of accessors instead.
    #
    # It exists so the window only offers to switch a source back on if this
    # app is the reason it is off. Most systems have sources that were disabled
    # on purpose long ago (the debug and source repositories, the installation
    # medium), and nagging about those would be wrong.
    def disabled_sources(self) -> list[str]:
        value = self._s.value("sources/disabledByUs", [])
        if isinstance(value, str):
            # A one-element list comes back as a bare string on some backends.
            return [value] if value else []
        if isinstance(value, (list, tuple)):
            return [str(v) for v in value if str(v)]
        return []

    def set_disabled_sources(self, aliases: list[str]) -> None:
        # Sorted and de-duplicated so the stored value does not churn.
        self._s.setValue("sources/disabledByUs", sorted(set(aliases)))
        self._s.sync()

    # -- how long a source has been unreachable --------------------------- #
    #
    # A source that cannot be reached for an afternoon is somebody else's
    # server having a bad day and the window says so. One that has been gone
    # for days is a different thing to be told, so the first day each source
    # failed is remembered here and the window changes what it says once that
    # is old enough.
    #
    # Stored as "<alias>|<ISO date>" strings, the same plain-list shape as
    # disabled_sources() above and for the same reason: QSettings hands a
    # one-element list back as a bare string, and this is the shape that copes.

    def _unreachable_raw(self) -> list[str]:
        value = self._s.value("sources/unreachableSince", [])
        if isinstance(value, str):
            return [value] if value else []
        if isinstance(value, (list, tuple)):
            return [str(v) for v in value if str(v)]
        return []

    def note_unreachable_sources(self, aliases: list[str]) -> None:
        """Record today for sources newly unreachable; forget the rest.

        An alias already listed keeps the day it was first seen - that is the
        whole point of the record. One that is not in *aliases* is dropped,
        because the check just reached it. An empty list therefore clears
        everything, which is what a clean check should do.
        """
        wanted = set(aliases)
        known = {}
        for entry in self._unreachable_raw():
            alias, _, day = entry.partition("|")
            if alias in wanted:
                known[alias] = day
        today = date.today().isoformat()
        kept = sorted(
            f"{alias}|{known.get(alias) or today}" for alias in wanted
        )
        if kept:
            self._s.setValue("sources/unreachableSince", kept)
        else:
            self._s.remove("sources/unreachableSince")
        self._s.sync()

    def unreachable_since(self, alias: str) -> date | None:
        """The day *alias* was first found unreachable, if it is on record."""
        for entry in self._unreachable_raw():
            name, _, day = entry.partition("|")
            if name != alias:
                continue
            try:
                return date.fromisoformat(day)
            except ValueError:
                return None
        return None

    # -- putting the check off for a day ---------------------------------- #
    #
    # A source that cannot be reached is usually somebody else's server having
    # a bad afternoon. Until it comes back there is nothing useful to do, so
    # the window offers to stop asking until tomorrow. A date, not a timestamp,
    # because a date is what the window shows the user.

    def deferred_until(self) -> date | None:
        """The day the check is deferred until, or None if it is not.

        None for unset, unparseable, and - the case that does the work - a day
        that has already arrived. An expired deferral is deleted here rather
        than left to rot in the config file, so the first read after midnight
        both reports the truth and tidies up.
        """
        raw = self._s.value("check/deferredUntil", "", str)
        try:
            day = date.fromisoformat(str(raw))
        except (TypeError, ValueError):
            if raw:
                self.set_deferred_until(None)
            return None
        if day <= date.today():
            self.set_deferred_until(None)
            return None
        return day

    def set_deferred_until(self, day: date | None) -> None:
        if day is None:
            self._s.remove("check/deferredUntil")
        else:
            self._s.setValue("check/deferredUntil", day.isoformat())
        self._s.sync()


def _as_bool(value: object) -> bool:
    # QSettings round-trips bools as the strings "true"/"false" on some backends.
    if isinstance(value, str):
        return value.lower() in ("1", "true", "yes", "on")
    return bool(value)


def _as_int(value: object, default: int) -> int:
    try:
        return int(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return default


def _one_of(value: object, choices, default: str) -> str:
    return value if isinstance(value, str) and value in choices else default


def dup_args_from_prefs(p: Prefs) -> list[str]:
    """Turn the update-behaviour toggles + free-text field into ``zypper dup`` args.

    Tokens already produced by the toggles are dropped from the free-text field
    so the two cannot contradict each other, but only whole options: a value
    following an option (``--download in-advance``) is always kept, or dropping
    a duplicate ``in-advance`` would leave a bare ``--download`` behind.
    """
    args: list[str] = []
    if p.dup_non_interactive:
        args += ["-y", "--auto-agree-with-licenses"]
    if p.dup_allow_vendor_change:
        args.append("--allow-vendor-change")
    if p.dup_download_in_advance:
        args += ["--download", "in-advance"]

    skip_value = False
    for token in p.zypper_dup_args.split():
        if skip_value:
            skip_value = False
            continue
        if token in args:
            # Drop this option, and its value too if it takes one.
            skip_value = token in VALUED
            continue
        args.append(token)
    return args
