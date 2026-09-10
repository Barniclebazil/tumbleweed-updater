"""Drives an update run through the embedded terminal.

An update is a short queue of shell commands fed one after another into a single
:class:`~tumbleweed_updater.pty_session.PtySession` attached to the terminal
widget:

1. ``pkexec run-update [extra dup args]``  - the ``zypper dup`` itself, fully
   interactive so the user answers zypper's prompts.
2. ``flatpak update``                      - system Flatpaks (flatpak triggers
   its own polkit prompt if needed).
3. ``flatpak --user update``               - per-user Flatpaks.

If a step exits non-zero the queue stops and the failure is reported; the user
can rerun. zypper's own snapshots (via ``snapper-zypp-plugin``) happen inside
step 1 - we do not manage snapshots ourselves.
"""

from __future__ import annotations

from dataclasses import dataclass

from PySide6.QtCore import QObject, Signal

from .paths import HELPER_RUN_UPDATE, resolve_helper
from .pty_session import PtySession


@dataclass
class Step:
    label: str
    argv: list[str]


class UpdateRunner(QObject):
    stepStarted = Signal(str)  # label
    finished = Signal(bool, str)  # ok, message

    def __init__(self, terminal, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._terminal = terminal
        self._queue: list[Step] = []
        self._session: PtySession | None = None
        self._running = False
        self._failed_label: str | None = None

    @property
    def is_running(self) -> bool:
        return self._running

    def build_queue(
        self,
        *,
        do_zypper: bool,
        dup_args: list[str] | None = None,
        do_flatpak_system: bool = False,
        do_flatpak_user: bool = False,
    ) -> list[Step]:
        steps: list[Step] = []
        if do_zypper:
            steps.append(
                Step(
                    "Upgrading the system with zypper dup",
                    ["pkexec", resolve_helper(HELPER_RUN_UPDATE), *(dup_args or [])],
                )
            )
        if do_flatpak_system:
            steps.append(Step("Updating system Flatpaks", ["flatpak", "update"]))
        if do_flatpak_user:
            steps.append(
                Step("Updating your Flatpaks", ["flatpak", "--user", "update"])
            )
        return steps

    def start(self, steps: list[Step]) -> None:
        if self._running or not steps:
            return
        self._queue = list(steps)
        self._running = True
        self._failed_label = None
        self._terminal.reset()
        self._next()

    def cancel(self) -> None:
        if self._session is not None and self._session.is_running:
            self._session.terminate()

    # -- queue pump ---------------------------------------------------------- #

    def _next(self) -> None:
        if not self._queue:
            self._running = False
            self._terminal.detach()
            self.finished.emit(True, "All updates completed.")
            return

        step = self._queue.pop(0)
        self.stepStarted.emit(step.label)
        self._terminal.append_notice(f"\x1b[1;33m*** {step.label} ***\x1b[0m")

        session = PtySession(self)
        session.finished.connect(lambda code, s=step: self._step_done(s, code))
        self._session = session
        self._terminal.attach(session)  # wires session.output -> terminal.feed
        rows, cols = self._terminal.grid_size()
        session.start(step.argv, rows=rows, cols=cols)

    def _step_done(self, step: Step, code: int) -> None:
        if self._session is not None:
            self._terminal.detach()
            self._session.deleteLater()
            self._session = None

        if code == 0:
            self._terminal.append_notice("\x1b[1;32m*** done ***\x1b[0m")
            self._next()
            return

        self._running = False
        self._queue.clear()
        self._failed_label = step.label
        if code < 0:
            reason = f"“{step.label}” was cancelled."
        else:
            reason = f"“{step.label}” failed (exit {code})."
        self._terminal.append_notice(f"\x1b[1;31m*** {reason} ***\x1b[0m")
        self.finished.emit(False, reason)
