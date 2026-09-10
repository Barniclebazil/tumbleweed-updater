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
    "ICON_STYLES",
    "DEFAULT_ICON_STYLE",
    "REBOOT_ACTIONS",
    "dup_args_from_prefs",
]

# What to do when an upgrade reports that a reboot is needed.
REBOOT_ACTIONS = {
    "notify": "Just tell me",
    "offer": "Offer to reboot now",
}
DEFAULT_REBOOT_ACTION = "notify"


# Terminal appearance defaults. An empty font family means "the system's
# fixed-width font".
DEFAULT_TERM_BG = "#1b1b1b"
DEFAULT_TERM_FG = "#f0f0f0"
DEFAULT_TERM_FONT_SIZE = 10

# Tray/window icon styles -> label. Each name has a matching
# data/icons/styles/<name>.svg (monochrome, currentColor stroke).
ICON_STYLES = {
    "tumbleweed": "Tumbleweed",
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
    start_in_tray: bool = True
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
    # Embedded-terminal appearance.
    term_font_family: str = ""
    term_font_size: int = DEFAULT_TERM_FONT_SIZE
    term_bg: str = DEFAULT_TERM_BG
    term_fg: str = DEFAULT_TERM_FG
    # Tray/window icon style (key of ICON_STYLES).
    icon_style: str = DEFAULT_ICON_STYLE


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
        s.setValue("ui/iconStyle", p.icon_style)
        s.setValue("zypper/allowVendorChange", p.dup_allow_vendor_change)
        s.setValue("zypper/nonInteractive", p.dup_non_interactive)
        s.setValue("zypper/downloadInAdvance", p.dup_download_in_advance)
        s.setValue("update/cleanup", p.cleanup_after_update)
        s.setValue("update/rebootAction", p.reboot_action)
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


def _one_of(value: object, choices, default: str) -> str:
    return value if isinstance(value, str) and value in choices else default


def dup_args_from_prefs(p: Prefs) -> list[str]:
    """Turn the update-behaviour toggles + free-text field into ``zypper dup`` args."""
    args: list[str] = []
    if p.dup_non_interactive:
        args += ["-y", "--auto-agree-with-licenses"]
    if p.dup_allow_vendor_change:
        args.append("--allow-vendor-change")
    if p.dup_download_in_advance:
        args += ["--download", "in-advance"]
    for token in p.zypper_dup_args.split():
        if token not in args:
            args.append(token)
    return args
