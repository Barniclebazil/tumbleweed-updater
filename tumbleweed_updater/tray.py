"""The persistent status-area icon.

States:

* **idle**       - monochrome, follows the Plasma light/dark theme.
* **updates**    - openSUSE orange.
* **installing** - orange too: there are updates, and they are going in.
* **checking**   - no icon of its own. The mark keeps saying whatever it
                   already knew, and only the tooltip changes.
* **error**      - monochrome but the tooltip carries the message.

Orange therefore means exactly one thing: there are updates. A check used to
turn it orange as well, which put a bright mark in the panel every few hours to
announce that the app was looking - attention asked for with nothing to say.
"""

from __future__ import annotations

from enum import Enum, auto

from PySide6.QtGui import QAction, QGuiApplication
from PySide6.QtWidgets import QMenu, QSystemTrayIcon

from . import APP_NAME
from .icons import idle_icon, text_color, updates_icon
from .settings import DEFAULT_ICON_STYLE, SettingsStore


class TrayState(Enum):
    IDLE = auto()
    UPDATES = auto()
    INSTALLING = auto()
    CHECKING = auto()
    ERROR = auto()


class TrayIcon(QSystemTrayIcon):
    def __init__(self, settings: SettingsStore | None = None, parent=None) -> None:
        super().__init__(parent)
        self._settings = settings
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
        self.setToolTip(f"{APP_NAME}\n{tooltip}")
        # Disabled for every state but UPDATES, CHECKING included: it is what
        # stops this menu starting an update while a check has zypper's lock.
        # The window emits the real state when the check ends, which brings it
        # back.
        self.act_update.setEnabled(state is TrayState.UPDATES)
        if state is TrayState.CHECKING:
            # Deliberately leaves _state and the icon alone. A check is the app
            # looking, not the app wanting attention, so the mark goes on
            # saying what it knew a moment ago - orange if updates are waiting,
            # monochrome if none are.
            return
        self._state = state
        self._refresh_icon()

    def reload(self) -> None:
        """Re-render the icon (e.g. after the icon style changed in settings)."""
        self._refresh_icon()

    # -- internals --------------------------------------------------------- #

    def _style(self) -> str:
        if self._settings is None:
            return DEFAULT_ICON_STYLE
        return self._settings.load().icon_style

    def _refresh_icon(self) -> None:
        style = self._style()
        if self._state in (TrayState.UPDATES, TrayState.INSTALLING):
            self.setIcon(updates_icon(style))
        else:
            self.setIcon(idle_icon(style, text_color()))

    def _on_activated(self, reason: QSystemTrayIcon.ActivationReason) -> None:
        if reason in (
            QSystemTrayIcon.Trigger,
            QSystemTrayIcon.DoubleClick,
            QSystemTrayIcon.MiddleClick,
        ):
            self.act_open.trigger()
