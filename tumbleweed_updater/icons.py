"""Tray/window icons.

Each icon *style* is a single monochrome SVG that paints itself in
``currentColor`` - the stroke for the line-art styles, the fill for the two
openSUSE logos.
In the tray, the idle state takes the current palette's text colour so it
follows a light or dark Plasma theme, and "updates available" takes an orange
that stands out regardless of theme.

The window, task manager and task switcher show the same idle icon as the tray,
so the app looks the same wherever it appears. See window_icon().

The launcher entry is the exception: data/icons/tumbleweed-updater.svg carries
a literal colour, because the launcher is handed that file as it is and has no
runtime to tint it in.
"""

from __future__ import annotations

from PySide6.QtCore import QByteArray, QRectF, Qt
from PySide6.QtGui import QColor, QIcon, QGuiApplication, QPainter, QPixmap
from PySide6.QtSvg import QSvgRenderer

from .resources import style_icon_file
from .settings import DEFAULT_ICON_STYLE

# 128 is on the end so that a size nobody anticipated is scaled *down*
# from a large rendering rather than up from a small one.
_SIZES = (16, 22, 24, 32, 48, 64, 128)
# Breeze's orange, not openSUSE's - picked to stand out in a Plasma panel
# whatever the theme, which is the tray's whole job here.
_ATTENTION = "#f67400"
# openSUSE green, as used by openSUSE-distributor-logo.svg, the Welcome app and
# the YaST icons. Nothing here paints with it: data/icons/tumbleweed-updater.svg
# carries the value itself, since the launcher is handed that file as it is and
# there is no runtime to tint it in. Kept as the one place the number is
# written down and explained.
APP_COLOR = "#73ba25"


def _read(path: str | None) -> str | None:
    if not path:
        return None
    try:
        with open(path, "r", encoding="utf-8") as fh:
            return fh.read()
    except OSError:
        return None


def _style_svg(style: str) -> str | None:
    return _read(style_icon_file(style)) or _read(style_icon_file(DEFAULT_ICON_STYLE))


def _render(svg_text: str, color: QColor) -> QIcon:
    """Rasterise *svg_text* at every size the desktop is likely to ask for.

    *color* substitutes the SVG's currentColor, which is how both the tray and
    the window icon follow the Plasma theme.
    """
    data = QByteArray(svg_text.replace("currentColor", color.name()).encode("utf-8"))
    renderer = QSvgRenderer(data)
    icon = QIcon()
    for size in _SIZES:
        pm = QPixmap(size, size)
        pm.fill(Qt.transparent)
        painter = QPainter(pm)
        renderer.render(painter, QRectF(0, 0, size, size))
        painter.end()
        icon.addPixmap(pm)
    return icon


def _fallback() -> QIcon:
    return QIcon.fromTheme("system-software-update")


def idle_icon(style: str, color: QColor) -> QIcon:
    svg = _style_svg(style)
    return _render(svg, color) if svg else _fallback()


def updates_icon(style: str) -> QIcon:
    svg = _style_svg(style)
    return _render(svg, QColor(_ATTENTION)) if svg else _fallback()


def window_icon(style: str = DEFAULT_ICON_STYLE) -> QIcon:
    """The title bar, the task manager and the task switcher.

    The same thing the tray shows when idle: the chosen style, in the palette's
    text colour, so it is dark on a light theme and white on a dark one. That
    only stays true if it is rebuilt when the colour scheme changes, which is
    App._on_color_scheme_changed()'s job - a palette read once at startup is
    not theme-following, it is just a colour.
    """
    return idle_icon(style, text_color())


def text_color() -> QColor:
    return QGuiApplication.palette().windowText().color()
