"""Application wiring: tray icon, window, single-instance guard, status watching."""

from __future__ import annotations

import os
import sys

from PySide6.QtCore import QFileSystemWatcher, QTimer
from PySide6.QtNetwork import QLocalServer, QLocalSocket
from PySide6.QtWidgets import QApplication, QMessageBox, QSystemTrayIcon

from . import APP_ID, APP_NAME, __version__
from .icons import window_icon
from .mainwindow import MainWindow
from .paths import STATUS_DIR, STATUS_FILE, installed_version
from .privileged import PrivilegedRunner
from .settings import SettingsStore
from .statusfile import read as read_status
from .tray import TrayIcon, TrayState

_SOCKET_NAME = "tumbleweed-updater.instance"


def _existing_instance_takeover(action: str) -> bool:
    """Return True if another instance handled *action* (so we should exit)."""
    sock = QLocalSocket()
    sock.connectToServer(_SOCKET_NAME)
    if sock.waitForConnected(300):
        sock.write(action.encode("utf-8"))
        sock.flush()
        sock.waitForBytesWritten(300)
        sock.disconnectFromServer()
        return True
    # Stale socket file from a crashed instance.
    QLocalServer.removeServer(_SOCKET_NAME)
    return False


def _relaunch_argv() -> list[str]:
    """Rebuild the command line to re-exec this same process.

    ``python3 -m tumbleweed_updater`` (the checkout/``make run`` case) sets
    ``sys.argv[0]`` to ``.../tumbleweed_updater/__main__.py``; re-executing
    that path directly would drop the package context its relative import
    needs, so re-add ``-m tumbleweed_updater`` instead. The installed launcher
    (``/usr/bin/tumbleweed-updater``) uses an absolute import and can just be
    re-run by path.
    """
    if sys.argv and os.path.basename(sys.argv[0]) == "__main__.py":
        return [sys.executable, "-m", "tumbleweed_updater", *sys.argv[1:]]
    return [sys.executable, *sys.argv]


class Application:
    def __init__(self, argv: list[str]) -> None:
        self._start_in_tray = "--tray" in argv
        want_update = "--update" in argv

        self.qt = QApplication(argv)

        action = "update" if want_update else "show"
        if _existing_instance_takeover(action):
            raise SystemExit(0)

        self.settings = SettingsStore()

        self.qt.setApplicationName(APP_NAME)
        self.qt.setApplicationDisplayName(APP_NAME)
        self.qt.setDesktopFileName(APP_ID)
        self.qt.setWindowIcon(window_icon(self.settings.load().icon_style))
        self.qt.setQuitOnLastWindowClosed(False)

        self._server = QLocalServer(self.qt)
        self._server.newConnection.connect(self._on_ipc)
        self._server.listen(_SOCKET_NAME)

        self.privileged = PrivilegedRunner(self.qt)

        self.window = MainWindow(self.settings, self.privileged)
        self.window.stateChanged.connect(self._on_state)
        self.window.settingsApplied.connect(self._on_settings_applied)
        self.window.restartRequested.connect(self.restart)

        self.tray = TrayIcon(self.settings, self.qt)
        self.tray.act_open.triggered.connect(self.window.show_and_raise)
        self.tray.act_check.triggered.connect(self.window.trigger_check)
        self.tray.act_update.triggered.connect(self.window.trigger_update)
        self.tray.act_settings.triggered.connect(
            lambda: (self.window.show_and_raise(), self.window.open_settings())
        )
        self.tray.act_quit.triggered.connect(self._quit)
        if QSystemTrayIcon.isSystemTrayAvailable():
            self.tray.show()

        self._last_total = -1
        self._update_notified = False
        self._watcher = QFileSystemWatcher(self.qt)
        self._install_watch()
        self._watcher.fileChanged.connect(self._on_status_touched)
        self._watcher.directoryChanged.connect(self._on_status_touched)

        self._reload_status(notify=False)

        prefs = self.settings.load()
        if want_update:
            QTimer.singleShot(0, self.window.trigger_update)
        elif not self._start_in_tray:
            self.window.show_and_raise()

        if prefs.check_on_launch:
            QTimer.singleShot(1500, self.window.trigger_check)

    # -- IPC ------------------------------------------------------------- #

    def _on_ipc(self) -> None:
        conn = self._server.nextPendingConnection()
        if conn is None:
            return

        def handle() -> None:
            data = bytes(conn.readAll()).decode("utf-8", "replace").strip()
            if data == "update":
                self.window.trigger_update()
            else:
                self.window.show_and_raise()
            conn.disconnectFromServer()

        conn.readyRead.connect(handle)

    # -- status file --------------------------------------------------------- #

    def _on_status_touched(self, _path: str) -> None:
        # Atomic writes (rename) drop the file from the watch list; re-add it.
        self._install_watch()
        self._reload_status()

    def _install_watch(self) -> None:
        paths = self._watcher.files() + self._watcher.directories()
        parent = os.path.dirname(STATUS_DIR)
        if os.path.isdir(STATUS_DIR):
            if STATUS_DIR not in paths:
                self._watcher.addPath(STATUS_DIR)
            if parent in self._watcher.directories():
                # No longer needed now that the real directory exists.
                self._watcher.removePath(parent)
        elif parent not in paths and os.path.isdir(parent):
            # STATUS_DIR (tmpfs) doesn't exist yet — e.g. we started before the
            # first check ran since boot. Watch its parent so we notice when
            # it's created and can switch to watching it directly.
            self._watcher.addPath(parent)
        if STATUS_FILE not in self._watcher.files() and os.path.exists(STATUS_FILE):
            self._watcher.addPath(STATUS_FILE)

    def _reload_status(self, notify: bool = True) -> None:
        status = read_status()
        if status is None:
            return
        self.window.apply_zypper_status(status)
        total = status.total
        prefs = self.settings.load()
        if (
            notify
            and prefs.notify_on_updates
            and total > 0
            and total != self._last_total
            and self._last_total >= 0
        ):
            self.tray.showMessage(
                APP_NAME,
                f"{total} update(s) available for your system.",
                QSystemTrayIcon.Information,
                8000,
            )
        self._last_total = total
        self._check_for_update()

    def _check_for_update(self) -> None:
        if self._update_notified:
            return
        new_version = installed_version()
        if new_version and new_version != __version__:
            self._update_notified = True
            self.window.show_update_available(new_version)

    # -- tray state ---------------------------------------------------------- #

    def _on_state(self, state: TrayState, tooltip: str) -> None:
        self.tray.set_state(state, tooltip)

    def _on_settings_applied(self) -> None:
        self.tray.reload()

    def _quit(self) -> None:
        if self.window.runner_active:
            if (
                QMessageBox.question(
                    self.window,
                    "Update in progress",
                    "An update is still running. Quit anyway and abort it?",
                    QMessageBox.Yes | QMessageBox.No,
                    QMessageBox.No,
                )
                != QMessageBox.Yes
            ):
                return
        self.qt.quit()

    def restart(self) -> None:
        # Release the single-instance socket before re-executing in place, so
        # the fresh process doesn't mistake the (about to vanish) old one for
        # a still-running instance and hand off to it instead of starting.
        self._server.close()
        QLocalServer.removeServer(_SOCKET_NAME)
        os.execv(sys.executable, _relaunch_argv())

    def run(self) -> int:
        return self.qt.exec()


def main(argv: list[str] | None = None) -> int:
    argv = list(sys.argv if argv is None else argv)
    try:
        app = Application(argv)
    except SystemExit as exc:
        return int(exc.code or 0)
    return app.run()
