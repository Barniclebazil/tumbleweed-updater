"""Background workers for things that would otherwise block the UI thread.

The Flatpak query and the wait for PackageKit run here; the latter polls the
lock file for up to twenty seconds. The zypper dry-run needs root and is done by
the privileged ``check`` helper, which writes the status file the GUI watches.
"""

from __future__ import annotations

from PySide6.QtCore import QObject, QRunnable, QThreadPool, Signal

from .packagekit import wait_for_lock
from .sources import FlatpakResult, check_flatpak


class _Signals(QObject):
    done = Signal(object)  # FlatpakResult


class _FlatpakTask(QRunnable):
    def __init__(self, signals: _Signals) -> None:
        super().__init__()
        self._signals = signals

    def run(self) -> None:  # noqa: D401 - QRunnable entry point
        try:
            result = check_flatpak()
        except Exception as exc:  # pragma: no cover - defensive
            result = FlatpakResult(error=str(exc))
        self._signals.done.emit(result)


class FlatpakChecker(QObject):
    finished = Signal(object)  # FlatpakResult

    def __init__(self, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._signals = _Signals()
        self._signals.done.connect(self._on_done)
        self._busy = False

    @property
    def is_running(self) -> bool:
        return self._busy

    def start(self) -> None:
        if self._busy:
            return
        self._busy = True
        QThreadPool.globalInstance().start(_FlatpakTask(self._signals))

    def _on_done(self, result) -> None:
        self._busy = False
        self.finished.emit(result)


class _LockWaitSignals(QObject):
    done = Signal(bool, str)


class _LockWaitTask(QRunnable):
    def __init__(self, signals: _LockWaitSignals) -> None:
        super().__init__()
        self._signals = signals

    def run(self) -> None:  # noqa: D401 - QRunnable entry point
        try:
            free, detail = wait_for_lock()
        except Exception as exc:  # pragma: no cover - defensive
            free, detail = False, str(exc)
        self._signals.done.emit(free, detail)


class LockWaiter(QObject):
    """Waits for PackageKit to finish with the zypp lock, off the UI thread.

    Reading /run/zypp.pid and /proc needs no privileges, and nothing here
    changes any state - it only watches.
    """

    finished = Signal(bool, str)  # free, detail

    def __init__(self, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._signals = _LockWaitSignals()
        self._signals.done.connect(self._on_done)
        self._busy = False

    @property
    def is_running(self) -> bool:
        return self._busy

    def start(self) -> None:
        if self._busy:
            return
        self._busy = True
        QThreadPool.globalInstance().start(_LockWaitTask(self._signals))

    def _on_done(self, free: bool, detail: str) -> None:
        self._busy = False
        self.finished.emit(free, detail)
