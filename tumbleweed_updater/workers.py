"""Background workers for things that would otherwise block the UI thread.

Only the Flatpak query runs here. The zypper dry-run needs root and is done by
the privileged ``check`` helper, which writes the status file the GUI watches.
"""

from __future__ import annotations

from PySide6.QtCore import QObject, QRunnable, QThreadPool, Signal

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
