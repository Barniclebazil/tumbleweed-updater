"""The terminal's themes: complete, valid, and in the order the list shows."""

import re

from tumbleweed_updater.termthemes import ANSI_NAMES, DEFAULT_THEME, THEMES

_HEX = re.compile(r"^#[0-9a-f]{6}$")


def test_every_theme_has_a_background_a_text_colour_and_sixteen_colours():
    for key, theme in THEMES.items():
        assert _HEX.match(theme.bg), key
        assert _HEX.match(theme.fg), key
        assert len(theme.colours) == len(ANSI_NAMES) == 16, key
        assert all(_HEX.match(c) for c in theme.colours), key


def test_the_list_order_puts_tumbleweed_above_ubuntu():
    assert list(THEMES) == [
        "tumbleweed", "ubuntu", "breeze", "gruvbox", "nord", "solarized-light",
    ]
    assert DEFAULT_THEME == "tumbleweed"


def test_breeze_keeps_the_colours_the_terminal_had_before_themes():
    assert dict(zip(ANSI_NAMES, THEMES["breeze"].colours)) == {
        "black": "#232627", "red": "#ed1515", "green": "#11d116",
        "brown": "#f67400", "blue": "#1d99f3", "magenta": "#9b59b6",
        "cyan": "#1abc9c", "white": "#fcfcfc",
        "brightblack": "#7f8c8d", "brightred": "#c0392b",
        "brightgreen": "#1cdc9a", "brightbrown": "#fdbc4b",
        "brightblue": "#3daee9", "brightmagenta": "#8e44ad",
        "brightcyan": "#16a085", "brightwhite": "#ffffff",
    }


def test_ubuntu_is_the_terminal_ubuntu_ships():
    """Yaru's terminal background and text, GNOME Terminal's 16 colours."""
    ubuntu = THEMES["ubuntu"]
    assert (ubuntu.bg, ubuntu.fg) == ("#300a24", "#ffffff")
    assert ubuntu.colours == (
        "#171421", "#c01c28", "#26a269", "#a2734c",
        "#12488b", "#a347ba", "#2aa1b3", "#d0cfcc",
        "#5e5c64", "#f66151", "#33da7a", "#e9ad0c",
        "#2a7bde", "#c061cb", "#33c7de", "#ffffff",
    )
