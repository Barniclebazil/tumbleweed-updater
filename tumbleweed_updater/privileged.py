"""Thin wrappers around the pkexec-invoked helpers.

Three helpers are called this way:

* ``check``        - refresh repos + dry-run dup, write the status file. The
                     polkit policy lets an active local session run this without
                     a password (it only reads state).
* ``set-interval`` - rewrite the systemd timer drop-in. Needs admin auth.
* ``snapshots``    - list and compare Btrfs snapshots. Needs admin auth even
                     to list, since ``snapper list`` refuses to run as a normal
                     user.
* ``snapshots-manage`` - roll back or delete a snapshot. A separate helper, and
                     a separate polkit action, so these prompt every time.

The interactive ``run-update`` helper is *not* here: it is spawned straight onto
the terminal's PTY by :mod:`tumbleweed_updater.runner` so the user can talk to
zypper.
"""

from __future__ import annotations

from PySide6.QtCore import QObject, QProcess, Signal

from .paths import (
    HELPER_CHECK,
    HELPER_SET_INTERVAL,
    HELPER_SNAPSHOTS,
    HELPER_SNAPSHOTS_MANAGE,
    resolve_helper,
)

# Snapshot operations are split over two helpers, and so over two polkit
# actions: listing and comparing are read-only and keep their authorisation
# cached, while rolling back or deleting must ask every time.
_MANAGE_ACTIONS = ("rollback", "delete")


def _snapshots_helper(args: list[str]) -> str:
    if args and args[0] in _MANAGE_ACTIONS:
        return HELPER_SNAPSHOTS_MANAGE
    return HELPER_SNAPSHOTS


def _explain_exit(code: int, stderr: str) -> str:
    stderr = stderr.strip()
    if code == 126:
        # pkexec uses 126 both for a refused authorisation and for a helper it
        # will not run at all, which is what a bare source checkout looks like.
        if "not authorized" in stderr.lower() or not stderr:
            return "Not authorised (the password dialog was dismissed or denied)."
        return stderr.splitlines()[-1]
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

    def run_check(self, wait_for_packagekit: bool = True) -> bool:
        """Start a check. False if one is already in flight.

        *wait_for_packagekit* carries the user's preference into the helper,
        which runs as root and cannot read it. The helper defaults to waiting,
        so only the opt-out needs passing - which is also what makes the systemd
        timer (no arguments) always wait.
        """
        if self._check_proc is not None:
            return False
        argv = [resolve_helper(HELPER_CHECK)]
        if not wait_for_packagekit:
            argv.append("--no-wait-for-packagekit")
        self._check_proc = self._spawn(
            argv,
            lambda ok, msg: self._done("_check_proc", self.checkFinished, ok, msg),
        )
        return True

    def set_interval(self, label: str) -> bool:
        """Apply a new check cadence. False if one is already in flight -
        callers must not then sit waiting for intervalFinished."""
        if self._interval_proc is not None:
            return False
        self._interval_proc = self._spawn(
            [resolve_helper(HELPER_SET_INTERVAL), label],
            lambda ok, msg: self._done(
                "_interval_proc", self.intervalFinished, ok, msg
            ),
        )
        return True

    def run_snapshots(self, args: list[str]) -> bool:
        """Run one snapshot operation. False if one is already in flight."""
        if self._snapshots_proc is not None:
            return False
        self._snapshots_proc = self._spawn(
            [resolve_helper(_snapshots_helper(args)), *args],
            lambda ok, msg, out: self._done(
                "_snapshots_proc", self.snapshotsFinished, ok, msg, out
            ),
            capture_stdout=True,
        )
        return True

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
        # A crashing QProcess emits both errorOccurred and finished, so this
        # can be reached twice for one run. The stored handle is the guard:
        # without it, listeners see a second, duplicate result.
        proc = getattr(self, attr)
        if proc is None:
            return
        setattr(self, attr, None)
        proc.deleteLater()
        signal.emit(*args)
