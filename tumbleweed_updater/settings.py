"""User-facing configuration, persisted with QSettings.

Only preferences that belong to the logged-in user live here. The *system*
check cadence is enforced by a systemd timer; this module just remembers which
cadence the user picked. The label->schedule mapping lives in
:mod:`tumbleweed_updater.intervals` so the privileged helper can share it.
"""

from __future__ import annotations

from dataclasses import dataclass

from PySide6.QtCore import QSettings

from . import APP_ID
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
]


# Terminal appearance defaults. An empty font family means "the system's
# fixed-width font".
DEFAULT_TERM_BG = "#1b1b1b"
DEFAULT_TERM_FG = "#f0f0f0"
DEFAULT_TERM_FONT_SIZE = 10


@dataclass
class Prefs:
    check_interval: str = DEFAULT_INTERVAL
    check_on_launch: bool = True
    start_in_tray: bool = True
    notify_on_updates: bool = True
    # Extra arguments appended to ``zypper dup`` (advanced; empty by default).
    zypper_dup_args: str = ""
    include_flatpak: bool = True
    # Embedded-terminal appearance.
    term_font_family: str = ""
    term_font_size: int = DEFAULT_TERM_FONT_SIZE
    term_bg: str = DEFAULT_TERM_BG
    term_fg: str = DEFAULT_TERM_FG


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
            start_in_tray=_as_bool(s.value("ui/startInTray", d.start_in_tray)),
            notify_on_updates=_as_bool(s.value("ui/notify", d.notify_on_updates)),
            zypper_dup_args=s.value("zypper/dupArgs", d.zypper_dup_args, str),
            include_flatpak=_as_bool(s.value("flatpak/include", d.include_flatpak)),
            term_font_family=s.value("term/fontFamily", d.term_font_family, str),
            term_font_size=_as_int(
                s.value("term/fontSize", d.term_font_size), d.term_font_size
            ),
            term_bg=s.value("term/bg", d.term_bg, str) or d.term_bg,
            term_fg=s.value("term/fg", d.term_fg, str) or d.term_fg,
        )

    def save(self, p: Prefs) -> None:
        s = self._s
        s.setValue("check/interval", p.check_interval)
        s.setValue("check/onLaunch", p.check_on_launch)
        s.setValue("ui/startInTray", p.start_in_tray)
        s.setValue("ui/notify", p.notify_on_updates)
        s.setValue("zypper/dupArgs", p.zypper_dup_args)
        s.setValue("flatpak/include", p.include_flatpak)
        s.setValue("term/fontFamily", p.term_font_family)
        s.setValue("term/fontSize", p.term_font_size)
        s.setValue("term/bg", p.term_bg)
        s.setValue("term/fg", p.term_fg)
        s.sync()


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
