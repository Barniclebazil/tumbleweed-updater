"""The persistent status-area icon.

States:

* **idle**    - monochrome, follows the Plasma light/dark theme.
* **updates** - openSUSE orange.
* **busy**    - orange while a check or an update run is in progress.
* **error**   - monochrome but the tooltip carries the message.
"""

from __future__ import annotations

from enum import Enum, auto

from PySide6.QtGui import QAction, QGuiApplication
from PySide6.QtWidgets import QMenu, QSystemTrayIcon

from . import APP_NAME
from .icons import idle_icon, updates_icon


class TrayState(Enum):
    IDLE = auto()
    UPDATES = auto()
    BUSY = auto()
    ERROR = auto()


class TrayIcon(QSystemTrayIcon):
    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self._state = TrayState.IDLE

        self._menu = QMenu()
        self.act_open = QAction("Show updates…", self._menu)
        self.act_check = QAction("Check now", self._menu)
        self.act_update = QAction("Update now…", self._menu)
        self.act_settings = QAction("Settings…", self._menu)
        self.act_quit = QAction("Quit", self._menu)
        self._menu.addAction(self.act_open)
        self._menu.addSeparator()
        self._menu.addAction(self.act_check)
        self._menu.addAction(self.act_update)
        self._menu.addSeparator()
        self._menu.addAction(self.act_settings)
        self._menu.addAction(self.act_quit)
        self.setContextMenu(self._menu)

        self.activated.connect(self._on_activated)

        # Rebuild the idle icon when the colour scheme changes.
        hints = QGuiApplication.styleHints()
        if hasattr(hints, "colorSchemeChanged"):
            hints.colorSchemeChanged.connect(lambda _=None: self._refresh_icon())

        self._refresh_icon()

    # -- public API ---------------------------------------------------------- #

    def set_state(self, state: TrayState, tooltip: str) -> None:
        self._state = state
        self.setToolTip(f"{APP_NAME}\n{tooltip}")
        self._refresh_icon()
        self.act_update.setEnabled(state == TrayState.UPDATES)

    # -- internals --------------------------------------------------------- #

    def _refresh_icon(self) -> None:
        if self._state in (TrayState.UPDATES, TrayState.BUSY):
            self.setIcon(updates_icon())
        else:
            self.setIcon(idle_icon(_text_color()))

    def _on_activated(self, reason: QSystemTrayIcon.ActivationReason) -> None:
        if reason in (
            QSystemTrayIcon.Trigger,
            QSystemTrayIcon.DoubleClick,
            QSystemTrayIcon.MiddleClick,
        ):
            self.act_open.trigger()


def _text_color():
    return QGuiApplication.palette().windowText().color()
