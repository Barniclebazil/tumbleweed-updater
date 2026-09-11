"""Thin wrappers around the pkexec-invoked helpers.

Three helpers are called this way:

* ``check``        - refresh repos + dry-run dup, write the status file. The
                     polkit policy lets an active local session run this without
                     a password (it only reads state).
* ``set-interval`` - rewrite the systemd timer drop-in. Needs admin auth.
* ``snapshots``    - list/compare/roll back/delete Btrfs snapshots. Needs
                     admin auth even to list, since ``snapper list`` refuses
                     to run as a normal user.

The interactive ``run-update`` helper is *not* here: it is spawned straight onto
the terminal's PTY by :mod:`tumbleweed_updater.runner` so the user can talk to
zypper.
"""

from __future__ import annotations

from PySide6.QtCore import QObject, QProcess, Signal

from .paths import HELPER_CHECK, HELPER_SET_INTERVAL, HELPER_SNAPSHOTS, resolve_helper


def _explain_exit(code: int, stderr: str) -> str:
    stderr = stderr.strip()
    if code == 126:
        return "Not authorised (the password dialog was dismissed or denied)."
    if code == 127:
        return "Helper not found - is the package installed correctly?"
    if stderr:
        return stderr.splitlines()[-1]
    return f"Helper exited with code {code}."


class PrivilegedRunner(QObject):
    checkFinished = Signal(bool, str)  # ok, message
    intervalFinished = Signal(bool, str)
    snapshotsFinished = Signal(bool, str, str)  # ok, message, stdout

    def __init__(self, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._check_proc: QProcess | None = None
        self._interval_proc: QProcess | None = None
        self._snapshots_proc: QProcess | None = None

    @property
    def check_running(self) -> bool:
        return self._check_proc is not None

    @property
    def snapshots_running(self) -> bool:
        return self._snapshots_proc is not None

    def run_check(self) -> None:
        if self._check_proc is not None:
            return
        self._check_proc = self._spawn(
            [resolve_helper(HELPER_CHECK)],
            lambda ok, msg: self._done("_check_proc", self.checkFinished, ok, msg),
        )

    def set_interval(self, label: str) -> None:
        if self._interval_proc is not None:
            return
        self._interval_proc = self._spawn(
            [resolve_helper(HELPER_SET_INTERVAL), label],
            lambda ok, msg: self._done(
                "_interval_proc", self.intervalFinished, ok, msg
            ),
        )

    def run_snapshots(self, args: list[str]) -> None:
        if self._snapshots_proc is not None:
            return
        self._snapshots_proc = self._spawn(
            [resolve_helper(HELPER_SNAPSHOTS), *args],
            lambda ok, msg, out: self._done(
                "_snapshots_proc", self.snapshotsFinished, ok, msg, out
            ),
            capture_stdout=True,
        )

    # -- internals ------------------------------------------------------- #

    def _spawn(self, argv: list[str], on_finish, capture_stdout: bool = False) -> QProcess:
        proc = QProcess(self)
        proc.setProgram("pkexec")
        proc.setArguments(argv)

        def handle_finished(code: int, _status) -> None:
            stderr = bytes(proc.readAllStandardError()).decode("utf-8", "replace")
            message = "" if code == 0 else _explain_exit(code, stderr)
            if capture_stdout:
                stdout = bytes(proc.readAllStandardOutput()).decode("utf-8", "replace")
                on_finish(code == 0, message, stdout)
            else:
                on_finish(code == 0, message)

        def handle_error(_err) -> None:
            if capture_stdout:
                on_finish(False, "Could not launch pkexec.", "")
            else:
                on_finish(False, "Could not launch pkexec.")

        proc.finished.connect(handle_finished)
        proc.errorOccurred.connect(handle_error)
        proc.start()
        return proc

    def _done(self, attr: str, signal: Signal, *args) -> None:
        proc = getattr(self, attr)
        setattr(self, attr, None)
        if proc is not None:
            proc.deleteLater()
        signal.emit(*args)
