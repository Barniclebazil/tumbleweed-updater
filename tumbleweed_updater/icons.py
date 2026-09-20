"""Tray/window icons.

Each icon *style* is a single monochrome SVG that paints itself in
``currentColor`` - the stroke for the line-art styles, the fill for the two
openSUSE logos.
In the tray, the idle state takes the current palette's text colour so it
follows a light or dark Plasma theme, and "updates available" takes an orange
that stands out regardless of theme.

The window, task manager and task switcher show the same idle icon as the tray,
so the app looks the same wherever it appears. See window_icon(). They ask for
it much smaller than the tray does, which is why _one_size() renders it the way
it does.

The launcher entry is the exception: data/icons/tumbleweed-updater.svg carries
a literal colour, because the launcher is handed that file as it is and has no
runtime to tint it in.
"""

from __future__ import annotations

from PySide6.QtCore import QByteArray, QRectF, Qt
from PySide6.QtGui import QColor, QIcon, QGuiApplication, QImage, QPainter, QPixmap
from PySide6.QtSvg import QSvgRenderer

from .resources import style_icon_file
from .settings import DEFAULT_ICON_STYLE

# Every size the desktop is likely to ask for. The small end matters more
# than it looks: measured by dumping the pixels of a screenshot, the Breeze
# title bar draws the icon at **14**, and with no 14 in this list Qt handed it
# the 16 scaled down, which softened every drawing that has been tried here.
# The rest of the small sizes are for whatever asks in between, so that
# nothing is ever scaled up from a smaller rendering; 128 is on the end so
# that a size nobody anticipated is scaled *down* from a large one.
_SIZES = (12, 14, 16, 18, 20, 22, 24, 32, 48, 64, 128)

# Each size is drawn this many times too large and then scaled back down,
# rather than straight into the final pixmap, so that the SVG's sub-pixel
# detail is averaged evenly instead of being left to the rasteriser.
_SUPERSAMPLE = 4

# How many extra times the finished rendering is laid over itself, by size.
# The line art in data/icons/styles/ is about five units wide in a 128-unit
# box, which is well under a pixel at title-bar size, so antialiasing spreads
# it into a half-transparent grey and the mark reads as a smudge rather than
# as the shape the tray shows at its larger size. Each pass takes a pixel's
# alpha from a to 1-(1-a)^n, which fills a thin line in towards opaque without
# moving the geometry or changing the colour. Above 24 the strokes already
# cover whole pixels, and deepening there would only harden the edges.
_DEEPEN = ((20, 2), (24, 1))

# The title bar cannot draw a half-transparent pixel. Measured here by giving
# three test windows the same mark rendered three ways and dumping the pixels
# of a screenshot: with ordinary antialiasing every partly covered pixel came
# back *darker* than the title bar behind it, near black, and only the fully
# opaque ones came through white; with the alpha forced to nothing or all, the
# mark drew exactly as designed. That is why every drawing tried in this
# window looked like a smudge, whatever the artwork was. So a title-bar
# drawing has its edges hardened at the sizes a decoration asks for, which is
# also how a small icon would be hinted by hand. Above this the smooth
# rendering stays, for the task switcher, which composites properly.
_HARDEN_UPTO = 24
# Alpha at or above this survives the hardening; below it goes. Somewhere near
# half a pixel of coverage, which keeps the geometry the drawing describes.
_HARDEN_AT = 110

# A style may ship a second drawing for the window icon, <style>-window.svg,
# for the case deepening cannot fix: artwork whose detail is finer than the
# 16px the decoration asks for. Only "tumbleweed" has one, and the file says
# why. The tray, the settings preview and the launcher never look for it.
_WINDOW_SUFFIX = "-window"

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


def _window_svg(style: str) -> tuple[str | None, bool]:
    """The drawing the window icon uses, and whether it is a title-bar one.

    The style's own title-bar drawing if it has one, otherwise the same file
    the tray draws. The flag matters because a title-bar drawing is made for
    the 16px the decoration asks for and is rendered as drawn, while artwork
    that was not needs the deepening _one_size() does.
    """
    own = _read(style_icon_file(f"{style}{_WINDOW_SUFFIX}"))
    if own:
        return own, True
    for name in (style, f"{DEFAULT_ICON_STYLE}{_WINDOW_SUFFIX}", DEFAULT_ICON_STYLE):
        svg = _read(style_icon_file(name))
        if svg:
            return svg, name.endswith(_WINDOW_SUFFIX)
    return None, False


def _passes(size: int, deepen: bool = True) -> int:
    """How many extra passes a pixmap of *size* gets. See _DEEPEN."""
    if not deepen:
        return 0
    for limit, passes in _DEEPEN:
        if size <= limit:
            return passes
    return 0


def _harden(image: QImage, size: int) -> QImage:
    """Round every pixel's alpha to nothing or all. See _HARDEN_UPTO."""
    image = image.convertToFormat(QImage.Format_ARGB32)
    for y in range(size):
        for x in range(size):
            colour = image.pixelColor(x, y)
            colour.setAlpha(255 if colour.alpha() >= _HARDEN_AT else 0)
            image.setPixelColor(x, y, colour)
    return image


def _one_size(
    renderer: QSvgRenderer, size: int, deepen: bool = True, harden: bool = False
) -> QPixmap:
    """One pixmap: supersampled, scaled down, then deepened or hardened."""
    big = size * _SUPERSAMPLE
    image = QImage(big, big, QImage.Format_ARGB32_Premultiplied)
    image.fill(Qt.transparent)
    painter = QPainter(image)
    painter.setRenderHint(QPainter.Antialiasing)
    renderer.render(painter, QRectF(0, 0, big, big))
    painter.end()

    image = image.scaled(size, size, Qt.IgnoreAspectRatio, Qt.SmoothTransformation)
    if harden and size <= _HARDEN_UPTO:
        return QPixmap.fromImage(_harden(image, size))
    passes = _passes(size, deepen)
    if passes:
        # A real copy, not a reference: Qt cannot use an image as the source
        # while painting on it.
        source = image.copy()
        painter = QPainter(image)
        for _ in range(passes):
            painter.drawImage(0, 0, source)
        painter.end()
    return QPixmap.fromImage(image)


def _render(svg_text: str, color: QColor, title_bar: bool = False) -> QIcon:
    """Rasterise *svg_text* at every size the desktop is likely to ask for.

    *color* substitutes the SVG's currentColor, which is how both the tray and
    the window icon follow the Plasma theme. *title_bar* is for a drawing made
    for the size a decoration asks for: it is rendered as drawn rather than
    deepened (see _DEEPEN), and its small sizes are hardened (see
    _HARDEN_UPTO, which is the one that actually made this legible).
    """
    data = QByteArray(svg_text.replace("currentColor", color.name()).encode("utf-8"))
    renderer = QSvgRenderer(data)
    icon = QIcon()
    for size in _SIZES:
        icon.addPixmap(
            _one_size(renderer, size, deepen=not title_bar, harden=title_bar)
        )
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

    The chosen style in the palette's text colour, so it is dark on a light
    theme and white on a dark one. That only stays true if it is rebuilt when
    the colour scheme changes, which is App._refresh_app_icon()'s job - a
    palette read once at startup is not theme-following, it is just a colour.

    The drawing is the tray's, unless the style ships a title-bar one of its
    own: see _WINDOW_SUFFIX. These three places share a single QIcon, the one
    handed to setWindowIcon(), so they cannot differ from each other.
    """
    svg, drawn_for_the_title_bar = _window_svg(style)
    if not svg:
        return _fallback()
    return _render(svg, text_color(), title_bar=drawn_for_the_title_bar)


def text_color() -> QColor:
    return QGuiApplication.palette().windowText().color()
