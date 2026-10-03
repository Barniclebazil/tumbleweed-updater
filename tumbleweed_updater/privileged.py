"""Thin wrappers around the pkexec-invoked helpers.

Five helpers are called this way:

* ``check``        - refresh repos + dry-run dup, write the status file. The
                     polkit policy lets an active local session run this without
                     a password (it only reads state).
* ``set-interval`` - rewrite the systemd timer drop-in. Needs admin auth.
* ``snapshots``    - list and compare Btrfs snapshots. Needs admin auth even
                     to list, since ``snapper list`` refuses to run as a normal
                     user.
* ``snapshots-manage`` - roll back or delete a snapshot. A separate helper, and
                     a separate polkit action, so these prompt every time.
* ``repos``        - switch a software source on or off. Needs admin auth, and
                     prompts every time for the same reason. Listing sources is
                     not here at all: ``zypper repos`` works unprivileged, so
                     :mod:`tumbleweed_updater.repos` is called directly.

The interactive ``run-update`` helper is *not* here: it is spawned straight onto
the terminal's PTY by :mod:`tumbleweed_updater.runner` so the user can talk to
zypper.
"""

from __future__ import annotations

from PySide6.QtCore import QObject, QProcess, Signal

from . import intervals, repos
from .paths import (
    HELPER_CHECK,
    HELPER_REPOS,
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


# Sentences written for the window. Anything else that arrives as a helper's
# message is in the helper's own words or zypper's or snapper's, and the window
# keeps it out of its main text: see is_plain().
NOT_AUTHORISED = (
    "The password request was cancelled or refused, so nothing was changed."
)
HELPER_MISSING = (
    "Part of Tumbleweed Updater is missing. Reinstalling the "
    "tumbleweed-updater package should fix this."
)
HELPER_FAILED = "Part of Tumbleweed Updater stopped with an error."
NO_PASSWORD_PROMPT = (
    "Tumbleweed Updater could not ask for the password, so nothing was changed."
)
PASSWORD_SERVICE_DOWN = (
    "The part of the system that checks passwords is not running, so nothing "
    "was changed. Restarting the computer should fix this."
)
PKEXEC_MISSING = (
    "The program that asks for the administrator password is not installed, "
    "so nothing was changed. Installing the pkexec package should fix this."
)

# Every message a helper can finish with that is already written for the
# user: the ones above, plus the sentences helper/repos and helper/set-interval
# print on purpose.
_PLAIN = frozenset(
    {
        NOT_AUTHORISED,
        HELPER_MISSING,
        HELPER_FAILED,
        NO_PASSWORD_PROMPT,
        PASSWORD_SERVICE_DOWN,
        PKEXEC_MISSING,
        repos.LOCKED_MESSAGE,
        *intervals.FAILURES,
    }
)


def is_plain(message: str) -> bool:
    """Whether *message* can be shown to the user as it is.

    False means it is somebody else's wording, such as "zypper exited 4" or the
    last line of a traceback: still worth keeping for whoever needs it, but as
    details under a plain sentence of the window's own.
    """
    return message in _PLAIN


# pkexec's own failure lines, and what each one means for the user. pkexec
# exits 127 for all but the dismissed one, so the exit code alone cannot tell a
# missing helper from a refused password: only these lines can. pkexec prints
# them untranslated (checked against polkit 127), so matching on the English
# is safe. The first match wins.
_PKEXEC_LINES = (
    ("Request dismissed", NOT_AUTHORISED),
    ("Not authorized", NOT_AUTHORISED),
    ("No authentication agent found", NO_PASSWORD_PROMPT),
    ("Error getting authority", PASSWORD_SERVICE_DOWN),
    ("Error checking for authorization", PASSWORD_SERVICE_DOWN),
    ("Cannot run program", HELPER_MISSING),
)


def _explain_exit(code: int, stderr: str) -> str:
    stderr = stderr.strip()
    if code in (126, 127):
        # Only pkexec's own exit codes: a helper that fails prints zypper's or
        # snapper's words, which are not to be read as pkexec's.
        for line, meaning in _PKEXEC_LINES:
            if line in stderr:
                return meaning
    if code == 126 and not stderr:
        # 126 is what pkexec returns when the password window was closed.
        return NOT_AUTHORISED
    if stderr:
        # The helper's own words, or pkexec's for a case not listed above.
        # Not plain, so the window keeps them under details.
        return stderr.splitlines()[-1]
    return HELPER_FAILED


class PrivilegedRunner(QObject):
    checkFinished = Signal(bool, str)  # ok, message
    intervalFinished = Signal(bool, str)
    snapshotsFinished = Signal(bool, str, str)  # ok, message, stdout
    reposFinished = Signal(bool, str)  # ok, message

    def __init__(self, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._check_proc: QProcess | None = None
        self._interval_proc: QProcess | None = None
        self._snapshots_proc: QProcess | None = None
        self._repos_proc: QProcess | None = None

    @property
    def check_running(self) -> bool:
        return self._check_proc is not None

    @property
    def snapshots_running(self) -> bool:
        return self._snapshots_proc is not None

    @property
    def repos_running(self) -> bool:
        return self._repos_proc is not None

    def run_check(self) -> bool:
        """Start a check. False if one is already in flight.

        No arguments: the helper takes none, and waiting for the package lock
        is what it always does. It used to be a preference, which was a switch
        whose only sensible setting was on - and one the scheduled check could
        not read anyway, running as root from a timer with no session.
        """
        if self._check_proc is not None:
            return False
        self._check_proc = self._spawn(
            [resolve_helper(HELPER_CHECK)],
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

    def set_repo_enabled(self, alias: str, enabled: bool) -> bool:
        """Switch one software source on or off. False if one is already in
        flight - callers must not then sit waiting for reposFinished."""
        if self._repos_proc is not None:
            return False
        self._repos_proc = self._spawn(
            [resolve_helper(HELPER_REPOS), "enable" if enabled else "disable", alias],
            lambda ok, msg: self._done("_repos_proc", self.reposFinished, ok, msg),
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

        def handle_error(err) -> None:
            # FailedToStart means pkexec itself could not be run. Tumbleweed
            # ships it as its own package, apart from polkit.
            if err == QProcess.ProcessError.FailedToStart:
                message = PKEXEC_MISSING
            else:
                message = NO_PASSWORD_PROMPT
            if capture_stdout:
                on_finish(False, message, "")
            else:
                on_finish(False, message)

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
