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


def test_the_window_icon_follows_the_tray_style_and_the_theme_colour(app):
    """Not a fixed colour and, for a style with nothing special about it, not
    fixed artwork either: the same thing the tray shows when idle, so a dark
    theme gets a white mark and a light one a dark mark, and picking a
    different style in the settings moves this too."""
    for style in ICON_STYLES:
        assert not icons.window_icon(style).isNull(), style

    expected = icons.idle_icon("shield", icons.text_color())
    assert (
        icons.window_icon("shield").pixmap(32, 32).toImage()
        == expected.pixmap(32, 32).toImage()
    )


def test_the_title_bar_has_its_own_drawing_of_the_tumbleweed_mark(app):
    """The one exception. A decoration asks for 16px, where the openSUSE logo
    is a wide, thin lemniscate that arrives as a smudge, so the window icon
    takes tumbleweed-window.svg instead. The tray keeps the logo."""
    svg = Path(resources.style_icon_file("tumbleweed-window")).read_text()
    from_window_file = icons._render(svg, icons.text_color(), title_bar=True)
    assert (
        icons.window_icon("tumbleweed").pixmap(32, 32).toImage()
        == from_window_file.pixmap(32, 32).toImage()
    )
    assert (
        icons.window_icon("tumbleweed").pixmap(32, 32).toImage()
        != icons.idle_icon("tumbleweed", icons.text_color()).pixmap(32, 32).toImage()
    )


def test_the_colour_reaches_the_rendered_pixels(app):
    """What makes following the theme possible at all: the style SVGs paint in
    currentColor, and _render() substitutes it."""
    svg = Path(resources.style_icon_file("tumbleweed")).read_text()
    light = icons._render(svg, QColor("#232629")).pixmap(32, 32).toImage()
    dark = icons._render(svg, QColor("#fcfcfc")).pixmap(32, 32).toImage()

    assert light != dark


def test_the_style_icons_still_recolour_themselves():
    """The tray and the window tint these at runtime and must keep being able
    to. Every file in the directory, not just the ICON_STYLES keys, so the
    title-bar drawings are covered as well."""
    svgs = sorted((REPO_ROOT / "data" / "icons" / "styles").glob("*.svg"))
    assert len(svgs) > len(ICON_STYLES)
    for path in svgs:
        assert "currentColor" in path.read_text(), path.name


def test_small_sizes_are_drawn_solid(app):
    """What the title bar shows. The decoration asks for 16px, where the line
    art is about half a pixel wide: rendered straight it comes out a
    half-transparent grey smudge, so _one_size() deepens it. Compare the ink
    in the 16px pixmap against a plain rendering of the same SVG."""
    from PySide6.QtCore import QByteArray, QRectF, Qt
    from PySide6.QtGui import QPainter, QPixmap
    from PySide6.QtSvg import QSvgRenderer

    def average_alpha(image):
        total = sum(
            image.pixelColor(x, y).alpha()
            for y in range(image.height())
            for x in range(image.width())
        )
        return total / (image.width() * image.height())

    for style in ICON_STYLES:
        svg = Path(resources.style_icon_file(style)).read_text()
        svg = svg.replace("currentColor", "#ffffff")

        plain = QPixmap(16, 16)
        plain.fill(Qt.transparent)
        painter = QPainter(plain)
        QSvgRenderer(QByteArray(svg.encode())).render(painter, QRectF(0, 0, 16, 16))
        painter.end()

        deepened = icons._one_size(QSvgRenderer(QByteArray(svg.encode())), 16)

        assert average_alpha(deepened.toImage()) > average_alpha(plain.toImage()), style


def test_a_title_bar_drawing_has_hard_edges(app):
    """The finding this whole icon hunt turned on: a Breeze title bar draws a
    partly transparent pixel far darker than it should, so a smooth rendering
    arrives as a smudge. Every small pixmap of a title-bar drawing is
    therefore all or nothing, and the larger ones, which the task switcher
    uses, are left smooth."""
    icon = icons.window_icon("tumbleweed")

    for size in (14, 16, icons._HARDEN_UPTO):
        image = icon.pixmap(size, size).toImage()
        alphas = {
            image.pixelColor(x, y).alpha()
            for y in range(image.height())
            for x in range(image.width())
        }
        assert alphas <= {0, 255}, (size, sorted(alphas))

    big = icon.pixmap(48, 48).toImage()
    assert any(
        0 < big.pixelColor(x, y).alpha() < 255
        for y in range(big.height())
        for x in range(big.width())
    )


def test_a_title_bar_drawing_is_rendered_as_drawn(app):
    """It is drawn on a 14-unit grid for the 14px the decoration asks for, so
    the deepening, which is for artwork that was not, stays out of its way."""
    assert icons._passes(16, deepen=False) == 0
    assert icons._passes(16) == 2


def test_large_sizes_are_left_alone(app):
    """The deepening is for sub-pixel strokes only. At 32 and up the artwork
    already covers whole pixels, so nothing is laid over anything."""
    assert icons._passes(16) == 2
    assert icons._passes(24) == 1
    assert icons._passes(32) == 0
