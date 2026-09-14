"""A child process on a pseudo-terminal, wired into the Qt event loop.

``zypper dup`` only behaves interactively - colour, progress bars, and the
"Choose from above solutions" prompts - when it believes it is talking to a
terminal. So we give it a real PTY and pump the master end through a
:class:`QSocketNotifier` instead of blocking threads.
"""

from __future__ import annotations

import fcntl
import os
import pty
import signal
import struct
import termios

from PySide6.QtCore import QObject, QSocketNotifier, QTimer, Signal

# How long to keep polling for a child that closed its PTY but has not exited,
# and the status reported if it never does. Negative reads as "did not finish
# normally" to UpdateRunner; past -64 so it cannot be mistaken for -SIGNUM.
_REAP_ATTEMPTS = 40
_REAP_INTERVAL_MS = 100
_REAP_GAVE_UP = -128


class PtySession(QObject):
    output = Signal(bytes)
    finished = Signal(int)  # exit status, negative for signal N

    def __init__(self, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._fd: int = -1
        self._pid: int = -1
        self._notifier: QSocketNotifier | None = None
        self._reaped = False

    # -- lifecycle -------------------------------------------------------- #

    @property
    def is_running(self) -> bool:
        return self._pid > 0 and not self._reaped

    def start(
        self,
        argv: list[str],
        *,
        rows: int = 24,
        cols: int = 80,
        cwd: str | None = None,
        env: dict[str, str] | None = None,
    ) -> None:
        if self.is_running:
            raise RuntimeError("session already running")

        full_env = dict(os.environ)
        full_env.update(
            {
                "TERM": "xterm-256color",
                "COLUMNS": str(cols),
                "LINES": str(rows),
                # Keep zypper/flatpak from trying to page their output.
                "PAGER": "cat",
                "SYSTEMD_PAGER": "cat",
            }
        )
        if env:
            full_env.update(env)

        pid, fd = pty.fork()
        if pid == 0:  # child
            # Keep this branch minimal and exec() straight away: the parent may
            # be multi-threaded (Qt thread pool), so anything touching a lock
            # here could deadlock.
            try:
                if cwd:
                    os.chdir(cwd)
                _set_winsize(pty.STDIN_FILENO, rows, cols)
                os.execvpe(argv[0], argv, full_env)
            except BaseException:
                os._exit(127)
        # parent
        self._pid = pid
        self._fd = fd
        self._reaped = False
        flags = fcntl.fcntl(fd, fcntl.F_GETFL)
        fcntl.fcntl(fd, fcntl.F_SETFL, flags | os.O_NONBLOCK)
        self.set_winsize(rows, cols)

        self._notifier = QSocketNotifier(fd, QSocketNotifier.Type.Read, self)
        self._notifier.activated.connect(self._on_readable)

    # -- I/O ------------------------------------------------------------- #

    def _on_readable(self) -> None:
        if self._fd < 0:
            return
        try:
            data = os.read(self._fd, 65536)
        except BlockingIOError:
            return
        except OSError:
            # EIO on Linux means the child closed its side of the PTY.
            data = b""
        if not data:
            self._reap()
            return
        self.output.emit(data)

    def write(self, data: bytes) -> None:
        if self._fd < 0 or not data:
            return
        try:
            os.write(self._fd, data)
        except OSError:
            pass

    def set_winsize(self, rows: int, cols: int) -> None:
        if self._fd < 0:
            return
        try:
            _set_winsize(self._fd, rows, cols)
        except OSError:
            pass

    # -- teardown ------------------------------------------------------- #

    def interrupt(self) -> bool:
        """Send Ctrl-C down the PTY. True if it was delivered.

        Not os.kill(): the child is pkexec, which has already become root, so
        signalling it from this unprivileged process fails with EPERM. Writing
        the interrupt character makes the kernel raise SIGINT on the terminal's
        foreground process group instead, whoever owns it.
        """
        if self._fd < 0 or not self.is_running:
            return False
        try:
            os.write(self._fd, b"\x03")
        except OSError:
            return False
        return True

    def terminate(self) -> bool:
        """SIGTERM the child. False when we are not allowed to (a root child)."""
        if not self.is_running:
            return False
        try:
            os.kill(self._pid, signal.SIGTERM)
        except OSError:
            return False
        return True

    def kill(self) -> bool:
        if not self.is_running:
            return False
        try:
            os.kill(self._pid, signal.SIGKILL)
        except OSError:
            return False
        return True

    def _reap(self) -> None:
        if self._reaped:
            return
        self._reaped = True

        if self._notifier is not None:
            self._notifier.setEnabled(False)
            self._notifier.deleteLater()
            self._notifier = None
        if self._fd >= 0:
            try:
                os.close(self._fd)
            except OSError:
                pass
            self._fd = -1

        self._collect(attempts=0)

    def _collect(self, attempts: int) -> None:
        """Reap the child and report its status, without blocking the UI.

        EOF on the master usually means the child is already gone, but a child
        that closes its descriptors and lingers would freeze the whole GUI in a
        blocking waitpid, so poll instead and give up after a few seconds.
        """
        status_code = 0
        if self._pid > 0:
            try:
                pid, status = os.waitpid(self._pid, os.WNOHANG)
            except ChildProcessError:
                pid, status = self._pid, 0
            if pid == 0:
                if attempts < _REAP_ATTEMPTS:
                    # self as the context object: the timer dies with us, so a
                    # session torn down mid-poll cannot be called back into.
                    QTimer.singleShot(
                        _REAP_INTERVAL_MS, self, lambda: self._collect(attempts + 1)
                    )
                    return
                status_code = _REAP_GAVE_UP
            elif os.WIFSIGNALED(status):
                status_code = -os.WTERMSIG(status)
            elif os.WIFEXITED(status):
                status_code = os.WEXITSTATUS(status)
        self.finished.emit(status_code)


def _set_winsize(fd: int, rows: int, cols: int) -> None:
    winsize = struct.pack("HHHH", max(rows, 1), max(cols, 1), 0, 0)
    fcntl.ioctl(fd, termios.TIOCSWINSZ, winsize)
