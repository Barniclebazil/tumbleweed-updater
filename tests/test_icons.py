import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtGui import QColor
from PySide6.QtWidgets import QApplication

from pathlib import Path

from tumbleweed_updater import icons, resources
from tumbleweed_updater.settings import ICON_STYLES

REPO_ROOT = Path(__file__).resolve().parent.parent
from tumbleweed_updater.tray import TrayIcon, TrayState


@pytest.fixture(scope="module")
def app():
    return QApplication.instance() or QApplication([])


def test_every_style_has_an_svg():
    for style in ICON_STYLES:
        assert resources.style_icon_file(style), f"missing SVG for style {style}"


@pytest.mark.parametrize("style", list(ICON_STYLES))
def test_icons_render_for_each_style(app, style):
    assert not icons.idle_icon(style, QColor("#202020")).isNull()
    assert not icons.updates_icon(style).isNull()


def test_unknown_style_falls_back(app):
    # Should not raise and should still produce a usable icon.
    assert not icons.idle_icon("does-not-exist", QColor("#202020")).isNull()


def test_tray_reload_picks_up_new_style(app, tmp_path, monkeypatch):
    # Qt resolves the config path via $XDG_CONFIG_HOME first, falling back to
    # $HOME/.config only if that's unset - on a normal desktop session it's
    # set independently of HOME, so both must be patched to actually isolate
    # QSettings from the real ~/.config file.
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / ".config"))

    from tumbleweed_updater.settings import SettingsStore

    store = SettingsStore()
    prefs = store.load()
    prefs.icon_style = "shield"
    store.save(prefs)

    tray = TrayIcon(store)
    tray.set_state(TrayState.IDLE, "ok")
    assert not tray.icon().isNull()

    prefs = store.load()
    prefs.icon_style = "package"
    store.save(prefs)
    tray.reload()
    assert not tray.icon().isNull()


def test_the_app_icon_carries_its_own_colour():
    """This file is handed to the launcher as it is, never tinted here, and
    outside a styling context currentColor resolves to black - which is what
    put a black mark in Kickoff."""
    import re

    svg = (REPO_ROOT / "data" / "icons" / "tumbleweed-updater.svg").read_text()
    markup = re.sub(r"<!--.*?-->", "", svg, flags=re.S)

    assert 'fill="#73ba25"' in markup
    assert "currentColor" not in markup


def test_the_window_icon_is_the_tray_style_in_the_theme_colour(app):
    """Not a fixed colour and not fixed artwork: the same thing the tray shows
    when idle, so a dark theme gets a white mark and a light one a dark mark,
    and picking a different style in the settings moves this too."""
    for style in ICON_STYLES:
        assert not icons.window_icon(style).isNull(), style

    expected = icons.idle_icon("tumbleweed", icons.text_color())
    assert (
        icons.window_icon("tumbleweed").pixmap(32, 32).toImage()
        == expected.pixmap(32, 32).toImage()
    )


def test_the_colour_reaches_the_rendered_pixels(app):
    """What makes following the theme possible at all: the style SVGs paint in
    currentColor, and _render() substitutes it."""
    svg = Path(resources.style_icon_file("tumbleweed")).read_text()
    light = icons._render(svg, QColor("#232629")).pixmap(32, 32).toImage()
    dark = icons._render(svg, QColor("#fcfcfc")).pixmap(32, 32).toImage()

    assert light != dark


def test_the_style_icons_still_recolour_themselves():
    """The tray tints these at runtime and must keep being able to."""
    for style in ICON_STYLES:
        path = resources.style_icon_file(style)
        assert "currentColor" in Path(path).read_text(), style
