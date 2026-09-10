"""Tray/window icons.

The idle icon is rendered from an SVG whose stroke is ``currentColor``; we
substitute the current palette's text colour so it follows a light or dark
Plasma theme like other status-area icons. The "updates available" icon is
always openSUSE orange so it stands out regardless of theme.
"""

from __future__ import annotations

from PySide6.QtCore import QByteArray, Qt
from PySide6.QtGui import QColor, QIcon, QPainter, QPixmap
from PySide6.QtSvg import QSvgRenderer

from .resources import icon_file

_SIZES = (16, 22, 24, 32, 48, 64)


def _render(svg_text: str) -> QIcon:
    renderer = QSvgRenderer(QByteArray(svg_text.encode("utf-8")))
    icon = QIcon()
    for size in _SIZES:
        pm = QPixmap(size, size)
        pm.fill(Qt.transparent)
        painter = QPainter(pm)
        renderer.render(painter)
        painter.end()
        icon.addPixmap(pm)
    return icon


def _load(name: str) -> str | None:
    path = icon_file(name)
    if not path:
        return None
    try:
        with open(path, "r", encoding="utf-8") as fh:
            return fh.read()
    except OSError:
        return None


def idle_icon(color: QColor) -> QIcon:
    svg = _load("tumbleweed-updater")
    if svg is None:
        return QIcon.fromTheme("system-software-update")
    return _render(svg.replace("currentColor", color.name()))


def updates_icon() -> QIcon:
    svg = _load("tumbleweed-updater-updates")
    if svg is None:
        return QIcon.fromTheme("system-software-update")
    return _render(svg)


def window_icon() -> QIcon:
    # Neutral mid-grey so it looks sane in the task switcher on any theme.
    return idle_icon(QColor("#4d4d4d"))
