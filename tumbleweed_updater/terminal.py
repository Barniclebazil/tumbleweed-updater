"""A small VT100-ish terminal widget backed by :mod:`pyte`.

Enough of a terminal to run ``zypper dup`` inside: colour, cursor, scrollback,
text selection, and a keyboard mapping that covers the keys zypper's prompts
care about (digits, letters, Enter, Ctrl-C). It is deliberately *not* a full
terminal emulator - no mouse reporting, no sixel - because the workload is a
package manager, not vim.
"""

from __future__ import annotations

import collections
import re

import pyte
from pyte.screens import Margins
from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import (
    QClipboard,
    QColor,
    QFont,
    QFontDatabase,
    QGuiApplication,
    QKeyEvent,
    QPainter,
)
from PySide6.QtWidgets import (
    QAbstractScrollArea,
    QApplication,
    QMenu,
    QMessageBox,
)

_HEX = re.compile(r"^[0-9a-fA-F]{6}$")

# The 16 ANSI colours, tuned to sit comfortably on both light and dark
# backgrounds (roughly the "Breeze" palette).
_NAMED = {
    "black": "#232627", "red": "#ed1515", "green": "#11d116",
    "brown": "#f67400", "blue": "#1d99f3", "magenta": "#9b59b6",
    "cyan": "#1abc9c", "white": "#fcfcfc",
    "brightblack": "#7f8c8d", "brightred": "#c0392b",
    "brightgreen": "#1cdc9a", "brightbrown": "#fdbc4b",
    "brightblue": "#3daee9", "brightmagenta": "#8e44ad",
    "brightcyan": "#16a085", "brightwhite": "#ffffff",
}

_KEYMAP = {
    Qt.Key_Return: b"\r", Qt.Key_Enter: b"\r",
    Qt.Key_Backspace: b"\x7f", Qt.Key_Tab: b"\t", Qt.Key_Escape: b"\x1b",
    Qt.Key_Up: b"\x1b[A", Qt.Key_Down: b"\x1b[B",
    Qt.Key_Right: b"\x1b[C", Qt.Key_Left: b"\x1b[D",
    Qt.Key_Home: b"\x1b[H", Qt.Key_End: b"\x1b[F",
    Qt.Key_Insert: b"\x1b[2~", Qt.Key_Delete: b"\x1b[3~",
    Qt.Key_PageUp: b"\x1b[5~", Qt.Key_PageDown: b"\x1b[6~",
}


def build_terminal_font(family: str, size: int) -> QFont:
    if family:
        font = QFont(family)
    else:
        font = QFontDatabase.systemFont(QFontDatabase.FixedFont)
    font.setPointSize(max(6, int(size)))
    font.setStyleHint(QFont.Monospace)
    font.setFixedPitch(True)
    font.setKerning(False)
    return font


class _Screen(pyte.Screen):
    """A pyte screen that keeps lines scrolled off the top in a deque."""

    def __init__(self, columns: int, lines: int, scrollback: int = 20000) -> None:
        self.scrollback: collections.deque = collections.deque(maxlen=scrollback)
        super().__init__(columns, lines)

    def index(self) -> None:
        top, bottom = self.margins or Margins(0, self.lines - 1)
        if self.cursor.y == bottom and (top, bottom) == (0, self.lines - 1):
            self.scrollback.append(dict(self.buffer[top]))
        super().index()


class TerminalWidget(QAbstractScrollArea):
    keyForwarded = Signal()
    resizedGrid = Signal(int, int)  # rows, cols
    clearRequested = Signal()  # "Clear" chosen from the context menu

    def __init__(
        self,
        parent=None,
        *,
        font_family: str = "",
        font_size: int = 10,
        bg: str = "#1b1b1b",
        fg: str = "#f0f0f0",
    ) -> None:
        super().__init__(parent)
        self._palette_bg = QColor(bg)
        self._palette_fg = QColor(fg)
        self._apply_font(font_family, font_size)

        self._cols, self._rows = 80, 24
        self._screen = _Screen(self._cols, self._rows)
        self._stream = pyte.ByteStream(self._screen)
        self._session = None

        self._sel_anchor: tuple[int, int] | None = None
        self._sel_head: tuple[int, int] | None = None

        self.setVerticalScrollBarPolicy(Qt.ScrollBarAlwaysOn)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.setFocusPolicy(Qt.StrongFocus)
        self.viewport().setCursor(Qt.IBeamCursor)
        self.verticalScrollBar().valueChanged.connect(lambda _: self.viewport().update())

    # -- appearance ------------------------------------------------------- #

    def _apply_font(self, family: str, size: int) -> None:
        self.setFont(build_terminal_font(family, size))
        self._recompute_metrics()

    def apply_appearance(
        self, *, font_family: str, font_size: int, bg: str, fg: str
    ) -> None:
        """Re-style a live terminal from user settings and reflow the grid."""
        self._palette_bg = QColor(bg)
        self._palette_fg = QColor(fg)
        self._apply_font(font_family, font_size)
        # Font metrics changed -> recompute rows/cols and tell the child.
        vp = self.viewport().size()
        cols = max(20, vp.width() // self._cell_w)
        rows = max(4, vp.height() // self._cell_h)
        self._cols, self._rows = cols, rows
        self._screen.resize(rows, cols)
        self._sync_scrollbar(True)
        self._push_winsize()
        self.viewport().update()

    # -- session plumbing --------------------------------------------------- #

    def attach(self, session) -> None:
        """Bind a :class:`~tumbleweed_updater.pty_session.PtySession`."""
        self._session = session
        session.output.connect(self.feed)
        self._push_winsize()

    def detach(self) -> None:
        """Forget the current session (call before it is destroyed)."""
        self._session = None
        self.viewport().update()

    def _session_running(self) -> bool:
        try:
            return self._session is not None and self._session.is_running
        except RuntimeError:  # underlying C++ session already deleted
            self._session = None
            return False

    def grid_size(self) -> tuple[int, int]:
        return self._rows, self._cols

    def feed(self, data: bytes) -> None:
        follow = self.verticalScrollBar().value() == self.verticalScrollBar().maximum()
        try:
            self._stream.feed(data)
        except Exception:
            # This is called from the PTY notifier's slot, so anything pyte
            # chokes on would otherwise abort the process. Losing a chunk of
            # output is the better failure.
            pass
        self._sync_scrollbar(follow)
        self.viewport().update()

    def append_notice(self, text: str) -> None:
        """Inject locally-generated lines (e.g. '[process exited]').

        Each newline is carriage-returned as well: on a real terminal a bare
        line feed moves down without returning to column 0, so a multi-line
        notice would come out staircased across the screen.
        """
        body = text.replace("\r\n", "\n").replace("\n", "\r\n")
        self.feed(("\r\n" + body + "\r\n").encode("utf-8"))

    def reset(self) -> None:
        self._screen.scrollback.clear()
        self._screen.reset()
        self._sel_anchor = self._sel_head = None
        self._sync_scrollbar(True)
        self.viewport().update()

    def clear(self) -> bool:
        """Drop the transcript at the user's request. False if it was refused.

        Refused while a command is running: clearing then would throw away the
        live transcript and leave the screen being redrawn from partial output.
        The widget knows nothing about the panel it sits in, so whoever owns
        that is told through :attr:`clearRequested` and decides for itself
        whether to collapse it too.
        """
        if self._session_running():
            return False
        self.reset()
        self.clearRequested.emit()
        return True

    # -- geometry --------------------------------------------------------- #

    def _recompute_metrics(self) -> None:
        fm = self.fontMetrics()
        self._cell_w = max(1, fm.horizontalAdvance("M"))
        self._cell_h = max(1, fm.height())
        self._ascent = fm.ascent()

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        vp = self.viewport().size()
        cols = max(20, vp.width() // self._cell_w)
        rows = max(4, vp.height() // self._cell_h)
        if (cols, rows) != (self._cols, self._rows):
            self._cols, self._rows = cols, rows
            self._screen.resize(rows, cols)
            self._sync_scrollbar(True)
            self._push_winsize()
        self.viewport().update()

    def _push_winsize(self) -> None:
        self.resizedGrid.emit(self._rows, self._cols)
        if self._session_running():
            self._session.set_winsize(self._rows, self._cols)

    def _sync_scrollbar(self, follow: bool) -> None:
        content = len(self._screen.scrollback) + self._rows
        maximum = max(0, content - self._rows)
        bar = self.verticalScrollBar()
        bar.setRange(0, maximum)
        bar.setPageStep(self._rows)
        bar.setSingleStep(1)
        if follow:
            bar.setValue(maximum)

    # -- rendering ------------------------------------------------------- #

    def _row_map(self, line_idx: int) -> dict:
        back = len(self._screen.scrollback)
        if line_idx < back:
            return self._screen.scrollback[line_idx]
        buf_y = line_idx - back
        return self._screen.buffer[buf_y] if buf_y < self._rows else {}

    def paintEvent(self, event) -> None:  # noqa: N802 (Qt naming)
        painter = QPainter(self.viewport())
        painter.fillRect(self.viewport().rect(), self._palette_bg)
        painter.setFont(self.font())

        offset = self.verticalScrollBar().value()
        default = self._screen.default_char
        sel = self._normalized_selection()
        base_font = self.font()

        for r in range(self._rows):
            line_idx = offset + r
            row = self._row_map(line_idx)
            y = r * self._cell_h
            # Collect (start_x, text, fg, bg, bold) runs of uniform style.
            run_start = 0
            run_chars: list[str] = []
            run_key = None
            run_fg = self._palette_fg
            run_bg: QColor | None = None
            run_bold = False

            def flush(end_x: int) -> None:
                if not run_chars:
                    return
                px = run_start * self._cell_w
                if run_bg is not None:
                    painter.fillRect(
                        px, y, (end_x - run_start) * self._cell_w,
                        self._cell_h, run_bg,
                    )
                if run_bold:
                    bf = QFont(base_font)
                    bf.setBold(True)
                    painter.setFont(bf)
                else:
                    painter.setFont(base_font)
                painter.setPen(run_fg)
                painter.drawText(px, y + self._ascent, "".join(run_chars))

            for x in range(self._cols):
                char = row.get(x, default) if row else default
                fg, bg, bold = _resolve_colors(
                    char, self._palette_fg, self._palette_bg
                )
                if _in_selection(sel, line_idx, x):
                    fg, bg = (bg or self._palette_bg), fg
                key = (fg.rgb(), bg.rgb() if bg is not None else None, bold)
                if key != run_key:
                    flush(x)
                    run_start, run_chars = x, []
                    run_key, run_fg, run_bg, run_bold = key, fg, bg, bold
                run_chars.append(char.data or " ")
            flush(self._cols)

        painter.setFont(base_font)
        self._paint_cursor(painter, offset)

    def _paint_cursor(self, painter: QPainter, offset: int) -> None:
        if not self._session_running():
            return
        cur = self._screen.cursor
        if cur.hidden:
            return
        line_idx = len(self._screen.scrollback) + cur.y
        r = line_idx - offset
        if not (0 <= r < self._rows):
            return
        px = cur.x * self._cell_w
        y = r * self._cell_h
        painter.fillRect(px, y, self._cell_w, self._cell_h, QColor("#f0c000"))
        row = self._screen.buffer[cur.y]
        ch = row.get(cur.x)
        if ch and ch.data.strip():
            painter.setPen(self._palette_bg)
            painter.drawText(px, y + self._ascent, ch.data)

    # -- selection & clipboard ----------------------------------------- #

    def _point_at(self, pos) -> tuple[int, int]:
        offset = self.verticalScrollBar().value()
        col = max(0, min(self._cols, pos.x() // self._cell_w))
        row = max(0, min(self._rows - 1, pos.y() // self._cell_h))
        return offset + row, col

    def _normalized_selection(self):
        if self._sel_anchor is None or self._sel_head is None:
            return None
        a, b = self._sel_anchor, self._sel_head
        return (a, b) if a <= b else (b, a)

    def mousePressEvent(self, event) -> None:
        self.setFocus()
        if event.button() == Qt.LeftButton:
            self._sel_anchor = self._point_at(event.position().toPoint())
            self._sel_head = self._sel_anchor
            self.viewport().update()

    def mouseMoveEvent(self, event) -> None:
        if self._sel_anchor is not None:
            self._sel_head = self._point_at(event.position().toPoint())
            self.viewport().update()

    def mouseReleaseEvent(self, event) -> None:
        sel = self._normalized_selection()
        if sel and sel[0] != sel[1]:
            text = self.selected_text()
            if text:
                QGuiApplication.clipboard().setText(text, QClipboard.Selection)

    def contextMenuEvent(self, event) -> None:
        menu = QMenu(self)
        act_copy = menu.addAction("Copy")
        act_copy.setEnabled(self._normalized_selection() is not None)
        act_all = menu.addAction("Copy Everything")
        act_paste = menu.addAction("Paste")
        menu.addSeparator()
        act_clear = menu.addAction("Clear")
        act_clear.setEnabled(not self._session_running())
        chosen = menu.exec(event.globalPos())
        if chosen is act_copy:
            QGuiApplication.clipboard().setText(self.selected_text())
        elif chosen is act_all:
            QGuiApplication.clipboard().setText(self.buffer_text())
        elif chosen is act_paste:
            self._paste()
        elif chosen is act_clear:
            self.clear()

    def selected_text(self) -> str:
        sel = self._normalized_selection()
        if not sel:
            return ""
        (l0, c0), (l1, c1) = sel
        out: list[str] = []
        for line_idx in range(l0, l1 + 1):
            row = self._row_map(line_idx)
            start = c0 if line_idx == l0 else 0
            end = c1 if line_idx == l1 else self._cols
            chars = [(row.get(x).data if row.get(x) else " ") for x in range(start, end)]
            out.append("".join(chars).rstrip())
        return "\n".join(out)

    def buffer_text(self) -> str:
        lines = []
        total = len(self._screen.scrollback) + self._rows
        for line_idx in range(total):
            row = self._row_map(line_idx)
            lines.append(
                "".join(
                    (row.get(x).data if row.get(x) else " ")
                    for x in range(self._cols)
                ).rstrip()
            )
        return "\n".join(lines).rstrip() + "\n"

    def _paste(self) -> None:
        if not self._session_running():
            return
        text = _sanitise_paste(QApplication.clipboard().text())
        if not text:
            return
        # A newline is an answer to whatever zypper is asking, and zypper is
        # running as root here, so multi-line pastes are confirmed rather than
        # submitted on the spot. This is the usual terminal-emulator guard.
        if "\n" in text:
            lines = text.count("\n") + 1
            if (
                QMessageBox.question(
                    self,
                    "Paste multiple lines?",
                    f"The clipboard holds {lines} lines. Pasting them will "
                    "answer any prompt the running command is showing.\n\n"
                    "Paste anyway?",
                    QMessageBox.Yes | QMessageBox.No,
                    QMessageBox.No,
                )
                != QMessageBox.Yes
            ):
                return
        self._session.write(text.encode("utf-8"))

    # -- keyboard ----------------------------------------------------------- #

    def keyPressEvent(self, event: QKeyEvent) -> None:  # noqa: N802
        mods = event.modifiers()
        key = event.key()

        if mods & Qt.ShiftModifier and key in (Qt.Key_PageUp, Qt.Key_PageDown):
            bar = self.verticalScrollBar()
            step = bar.pageStep() * (1 if key == Qt.Key_PageDown else -1)
            bar.setValue(bar.value() + step)
            return
        if mods & (Qt.ControlModifier | Qt.ShiftModifier) == (
            Qt.ControlModifier | Qt.ShiftModifier
        ):
            if key == Qt.Key_C:
                QGuiApplication.clipboard().setText(
                    self.selected_text() or self.buffer_text()
                )
                return
            if key == Qt.Key_V:
                self._paste()
                return

        if not self._session_running():
            super().keyPressEvent(event)
            return

        data: bytes | None = None
        if mods & Qt.ControlModifier and Qt.Key_A <= key <= Qt.Key_Z:
            data = bytes([key - Qt.Key_A + 1])
        elif key in _KEYMAP:
            data = _KEYMAP[key]
        elif event.text():
            data = event.text().encode("utf-8")

        if data is not None:
            self._session.write(data)
            # A keystroke means the user wants to watch the bottom.
            bar = self.verticalScrollBar()
            bar.setValue(bar.maximum())
            self.keyForwarded.emit()
        else:
            super().keyPressEvent(event)


# --------------------------------------------------------------------------- #

def _sanitise_paste(text: str) -> str:
    """Drop control characters from pasted text, keeping tab and newline.

    Escape sequences in a paste would otherwise be interpreted by whatever is
    reading the PTY rather than treated as the text the user thinks they are
    pasting.
    """
    return "".join(
        ch for ch in text.replace("\r\n", "\n").replace("\r", "\n")
        if ch in "\t\n" or (ch.isprintable() and ch != "\x7f")
    )


def _colour(value: str, bold: bool, fallback: QColor) -> QColor | None:
    if value == "default":
        return None if not bold else fallback
    if _HEX.match(value):
        return QColor("#" + value)
    if bold and value in _NAMED and "bright" + value in _NAMED:
        value = "bright" + value
    hexval = _NAMED.get(value)
    return QColor(hexval) if hexval else fallback


def _resolve_colors(char, default_fg: QColor, default_bg: QColor):
    fg = _colour(char.fg, char.bold, default_fg) or default_fg
    bg = _colour(char.bg, False, default_bg)
    if char.reverse:
        fg, bg = (bg or default_bg), fg
    return fg, bg, bool(char.bold)


def _in_selection(sel, line_idx: int, col: int) -> bool:
    if not sel:
        return False
    (l0, c0), (l1, c1) = sel
    if line_idx < l0 or line_idx > l1:
        return False
    if l0 == l1:
        return c0 <= col < c1
    if line_idx == l0:
        return col >= c0
    if line_idx == l1:
        return col < c1
    return True
