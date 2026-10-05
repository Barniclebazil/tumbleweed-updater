"""Colour themes for the update terminal and the list above it.

Qt-free on purpose (see the conventions in CLAUDE.md), so the themes and the
Konsole reader in konsole.py can be tested without a display.

A theme is a background, a text colour and the 16 colours a program can ask
for by number (ANSI colours 0-7 and their bright versions). The terminal looks
those up by the names pyte gives them, in ``ANSI_NAMES`` order.
"""

from __future__ import annotations

from dataclasses import dataclass

# pyte's names for colours 30-37 and 90-97, in that order. "brown" is pyte's
# word for yellow.
ANSI_NAMES = (
    "black", "red", "green", "brown", "blue", "magenta", "cyan", "white",
    "brightblack", "brightred", "brightgreen", "brightbrown",
    "brightblue", "brightmagenta", "brightcyan", "brightwhite",
)


@dataclass(frozen=True)
class Theme:
    label: str
    bg: str
    fg: str
    colours: tuple[str, ...]  # 16, in ANSI_NAMES order


@dataclass(frozen=True)
class Appearance:
    """Everything the terminal and the update list need to draw themselves."""

    font_family: str  # "" for the system fixed-width font
    font_size: int | None  # None for the system fixed-width font's own size
    bg: str
    fg: str
    colours: tuple[str, ...]
    # A plain sentence when something had to be substituted, such as a
    # Konsole colour scheme that cannot be read. None when all is as asked.
    note: str | None = None


# Theme keys that are not in THEMES: one read from Konsole each time, and one
# made by changing a theme's background or text colour.
KONSOLE = "konsole"
CUSTOM = "custom"

THEMES: dict[str, Theme] = {
    # openSUSE's colours: its green, cyan and blue, on a dark shade of its
    # dark blue.
    "tumbleweed": Theme(
        "Tumbleweed", "#102a33", "#e8f1e4",
        (
            "#173f4f", "#e2574c", "#73ba25", "#e8b03a",
            "#21a4df", "#a97bd1", "#35b9ab", "#cfdcd6",
            "#5f7f89", "#ff7a6e", "#9bd458", "#ffd166",
            "#5ec2ef", "#c9a0ea", "#6fd9cc", "#ffffff",
        ),
    ),
    # Ubuntu's Terminal as it ships (24.04): the aubergine background and
    # white text come from Ubuntu's Yaru theme (gtk-3.0/apps/
    # _gnome-terminal.scss), and the 16 colours are GNOME Terminal's own
    # defaults (org.gnome.Terminal.gschema.xml), which Ubuntu does not patch.
    "ubuntu": Theme(
        "Ubuntu", "#300a24", "#ffffff",
        (
            "#171421", "#c01c28", "#26a269", "#a2734c",
            "#12488b", "#a347ba", "#2aa1b3", "#d0cfcc",
            "#5e5c64", "#f66151", "#33da7a", "#e9ad0c",
            "#2a7bde", "#c061cb", "#33c7de", "#ffffff",
        ),
    ),
    # Konsole's default scheme. These 16 were the terminal's only colours
    # before there were themes.
    "breeze": Theme(
        "Breeze", "#232627", "#fcfcfc",
        (
            "#232627", "#ed1515", "#11d116", "#f67400",
            "#1d99f3", "#9b59b6", "#1abc9c", "#fcfcfc",
            "#7f8c8d", "#c0392b", "#1cdc9a", "#fdbc4b",
            "#3daee9", "#8e44ad", "#16a085", "#ffffff",
        ),
    ),
    "gruvbox": Theme(
        "Gruvbox", "#282828", "#ebdbb2",
        (
            "#282828", "#cc241d", "#98971a", "#d79921",
            "#458588", "#b16286", "#689d6a", "#a89984",
            "#928374", "#fb4934", "#b8bb26", "#fabd2f",
            "#83a598", "#d3869b", "#8ec07c", "#ebdbb2",
        ),
    ),
    "nord": Theme(
        "Nord", "#2e3440", "#d8dee9",
        (
            "#3b4252", "#bf616a", "#a3be8c", "#ebcb8b",
            "#81a1c1", "#b48ead", "#88c0d0", "#e5e9f0",
            "#4c566a", "#bf616a", "#a3be8c", "#ebcb8b",
            "#81a1c1", "#b48ead", "#8fbcbb", "#eceff4",
        ),
    ),
    "solarized-light": Theme(
        "Solarized Light", "#fdf6e3", "#657b83",
        (
            "#073642", "#dc322f", "#859900", "#b58900",
            "#268bd2", "#d33682", "#2aa198", "#eee8d5",
            "#002b36", "#cb4b16", "#586e75", "#657b83",
            "#839496", "#6c71c4", "#93a1a1", "#fdf6e3",
        ),
    ),
}

DEFAULT_THEME = "tumbleweed"
