"""Tray/window icons.

Each icon *style* is a single monochrome SVG that paints itself in
``currentColor`` - the stroke for the line-art styles, the fill for the two
openSUSE logos.
For the idle state we substitute the current palette's text colour so it follows
a light or dark Plasma theme; for "updates available" we substitute openSUSE
orange so it stands out regardless of theme.
"""

from __future__ import annotations

from PySide6.QtCore import QByteArray, QRectF, Qt
from PySide6.QtGui import QColor, QIcon, QGuiApplication, QPainter, QPixmap
from PySide6.QtSvg import QSvgRenderer

from .resources import icon_file, style_icon_file
from .settings import DEFAULT_ICON_STYLE

_SIZES = (16, 22, 24, 32, 48, 64)
_ATTENTION = "#f67400"  # openSUSE orange


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
    # Neutral mid-grey so it looks sane in the task switcher on any theme.
    return idle_icon(style, QColor("#4d4d4d"))


def text_color() -> QColor:
    return QGuiApplication.palette().windowText().color()


# Kept for the installed hicolor app icon lookup (unchanged behaviour).
def app_icon() -> QIcon:
    svg = _read(icon_file("tumbleweed-updater"))
    return _render(svg, QColor("#4d4d4d")) if svg else _fallback()
