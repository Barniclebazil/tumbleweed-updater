"""Application wiring: tray icon, window, single-instance guard, status watching."""

from __future__ import annotations

import os
import sys
import tempfile

from PySide6.QtCore import QFileSystemWatcher, QTimer
from PySide6.QtGui import QGuiApplication
from PySide6.QtNetwork import QLocalServer, QLocalSocket
from PySide6.QtWidgets import QApplication, QMessageBox, QSystemTrayIcon

from . import APP_ID, APP_NAME, __version__
from . import autostart
from .icons import window_icon
from .mainwindow import MainWindow
from .paths import STATUS_DIR, STATUS_FILE, installed_version
from .privileged import PrivilegedRunner
from .settings import SettingsStore
from .statusfile import read as read_status
from .tray import TrayIcon, TrayState


def _should_ask_about_notifier(
    prefs, *, system_entry: bool, already_off: bool
) -> bool:
    """Whether to put the one-time question about Plasma's notifier."""
    if not system_entry:
        return False  # not Plasma, or discover6-notifier is not installed
    if already_off:
        return False  # nothing to ask; the answer is recorded without asking
    return not prefs.plasma_notifier_asked


def _should_notify(
    *,
    notify: bool,
    notify_on_updates: bool,
    total: int,
    last_total: int,
    deferred,
) -> bool:
    """Whether to pop "N update(s) available" on the desktop.

    Only when the count has actually changed, and never for the first status
    the app sees (*last_total* < 0), which would otherwise fire a notification
    every launch for updates the user already knows about.

    *deferred* is the day the user put the check off until, or None. While one
    is in force this stays quiet: a tray icon that has gone back to idle and a
    notification saying there are 42 updates cannot both be right.
    """
    if deferred is not None:
        return False
    return (
        notify
        and notify_on_updates
        and total > 0
        and total != last_total
        and last_total >= 0
    )


def _socket_path() -> str:
    """Absolute path for the single-instance socket.

    A bare server name makes Qt create /tmp/<name>, mode 0755: any other local
    user could connect to it (and so make this app raise a polkit password
    prompt on our desktop), or create the path first so that this app mistakes
    it for a running instance and exits. XDG_RUNTIME_DIR is per-user and 0700,
    so the socket is reachable only by us.
    """
    runtime = os.environ.get("XDG_RUNTIME_DIR") or f"/run/user/{os.getuid()}"
    if not os.path.isdir(runtime):
        # No logind session. Fall back to the temp directory, where the
        # UserAccessOption set on the server is the only protection left.
        runtime = tempfile.gettempdir()
    return os.path.join(runtime, "tumbleweed-updater.instance")


_SOCKET_NAME = _socket_path()


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
        # 0600 on the socket itself, so that it is ours alone even in the
        # temp-directory fallback _socket_path() describes.
        self._server.setSocketOptions(QLocalServer.UserAccessOption)
        if not self._server.listen(_SOCKET_NAME):
            # Not fatal - the app works, it just cannot be re-focused by a
            # second launch - but it means something else holds the path.
            sys.stderr.write(
                f"tumbleweed-updater: could not listen on {_SOCKET_NAME}: "
                f"{self._server.errorString()}\n"
            )

        self.privileged = PrivilegedRunner(self.qt)

        self.window = MainWindow(self.settings, self.privileged)
        self.window.stateChanged.connect(self._on_state)
        # Guarded the way tray.py guards the same signal: it arrived in Qt 6.5
        # and this is the only thing that keeps the icon honest across a theme
        # change.
        hints = QGuiApplication.styleHints()
        if hasattr(hints, "colorSchemeChanged"):
            hints.colorSchemeChanged.connect(lambda _=None: self._refresh_app_icon())
        self.window.settingsApplied.connect(self._on_settings_applied)
        self.window.restartRequested.connect(self.restart)
        self.window.quitRequested.connect(self._quit)

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

        # The question is asked once the window is actually on screen, which
        # for a tray start is whenever the user first opens it. Connecting
        # before the show below means a windowed start asks straight away, and
        # a zero-delay timer keeps the modal out of the constructor, where it
        # would open a nested event loop before the window has painted.
        if not want_update:
            self.window.firstShown.connect(
                lambda: QTimer.singleShot(0, self._maybe_ask_about_notifier)
            )

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
        # Before the deferral is read: this can clear it, when the check comes
        # back with every source reachable.
        self.window.apply_zypper_status(status)
        total = status.total
        if _should_notify(
            notify=notify,
            notify_on_updates=self.settings.load().notify_on_updates,
            total=total,
            last_total=self._last_total,
            deferred=self.settings.deferred_until(),
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
        self.window.reload_icon()

    def _refresh_app_icon(self) -> None:
        """Repaint the app's icon in the current theme's text colour.

        The tray does this for itself; the window and the task switcher get it
        from here. Without it "follows the system theme" would mean "was the
        right colour when the app started", and switching Plasma to a light
        theme would leave a white mark on a white bar.
        """
        style = self.settings.load().icon_style
        self.qt.setWindowIcon(window_icon(style))
        self.window.reload_icon()

    def _confirm_abort(self, question: str) -> bool:
        return (
            QMessageBox.question(
                self.window,
                "Update in progress",
                question,
                QMessageBox.Yes | QMessageBox.No,
                QMessageBox.No,
            )
            == QMessageBox.Yes
        )

    def _quit(self) -> None:
        if self.window.runner_active and not self._confirm_abort(
            "An update is still running. Quit anyway and abort it?"
        ):
            return
        self.qt.quit()

    def restart(self) -> None:
        # Re-executing tears down the terminal's PTY, which SIGHUPs whatever is
        # attached to it - including a zypper transaction in flight.
        if self.window.runner_active and not self._confirm_abort(
            "An update is still running. Restart anyway and abort it?"
        ):
            return
        # Release the single-instance socket before re-executing in place, so
        # the fresh process doesn't mistake the (about to vanish) old one for
        # a still-running instance and hand off to it instead of starting.
        self._server.close()
        QLocalServer.removeServer(_SOCKET_NAME)
        os.execv(sys.executable, _relaunch_argv())

    # -- Plasma's own update notifier -------------------------------------- #

    def _maybe_ask_about_notifier(self) -> None:
        """Offer once to switch off Plasma's update notifier.

        It polls PackageKit, PackageKit takes the zypp lock when it starts, and
        that is what makes checks and upgrades fail here. This app already
        reports the same zypper and Flatpak updates, so the notifier is
        redundant - but it belongs to another application, so it is never
        switched off without asking.
        """
        prefs = self.settings.load()
        already_off = autostart.is_hidden()
        if not _should_ask_about_notifier(
            prefs,
            system_entry=autostart.is_installed(),
            already_off=already_off,
        ):
            if already_off and not prefs.plasma_notifier_asked:
                # Already off by the user's own hand: record it as answered.
                prefs.plasma_notifier_asked = True
                self.settings.save(prefs)
            return

        box = QMessageBox(self.window)
        box.setIcon(QMessageBox.Question)
        box.setWindowTitle("Plasma also checks for updates")
        box.setText("Turn off Plasma's own update notifier?")
        box.setInformativeText(
            "Plasma's update notifier (part of Discover) looks for updates "
            "through PackageKit. Starting PackageKit takes the system package "
            "lock, which is what makes an update check fail with \"System "
            "management is locked\".\n\n"
            f"{APP_NAME} already tells you about the same zypper and Flatpak "
            "updates, so the notifier is not needed as well.\n\n"
            "Discover itself is not affected: you can still open it to install "
            "and remove software and to manage repositories. You can change "
            "this again at any time in Settings."
        )
        off = box.addButton("Turn it off", QMessageBox.AcceptRole)
        keep = box.addButton("Keep it", QMessageBox.RejectRole)
        box.setDefaultButton(off)
        box.setEscapeButton(keep)
        box.exec()

        if box.clickedButton() is off:
            ok, detail = autostart.suppress_plasma_notifier(True)
            if not ok:
                QMessageBox.warning(
                    self.window, "Could not change the notifier", detail
                )

        # Dismissing counts as an answer, so the question is genuinely one-off.
        prefs = self.settings.load()
        prefs.plasma_notifier_asked = True
        self.settings.save(prefs)

    def run(self) -> int:
        return self.qt.exec()


def main(argv: list[str] | None = None) -> int:
    argv = list(sys.argv if argv is None else argv)
    try:
        app = Application(argv)
    except SystemExit as exc:
        return int(exc.code or 0)
    return app.run()
