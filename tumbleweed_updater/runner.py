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

import time
from dataclasses import dataclass

from PySide6.QtCore import QObject, QTimer, Signal

from .paths import HELPER_RUN_UPDATE, resolve_helper
from .progress import Phase, ZypperProgress, describe, finishing_permille
from .pty_session import PtySession


@dataclass
class Step:
    label: str
    argv: list[str]
    # How the window names this step when it fails or is cancelled: a noun
    # phrase that starts a sentence, such as "The system update".
    what: str = "The update"
    # The zypper step. Its output carries zypper's package counters, which
    # progress.py reads for the progress bar, which then fills from start to
    # end; any other step gets a moving bar and its label.
    counts_packages: bool = False
    # "--download only" among the options: nothing is installed, so the bar is
    # full once the last package has been downloaded.
    download_only: bool = False


def _downloads_only(args: list[str]) -> bool:
    """Whether zypper dup *args* ask for "--download only", either spelling."""
    for n, token in enumerate(args):
        if token == "--download=only":
            return True
        if token == "--download" and args[n + 1 : n + 2] == ["only"]:
            return True
    return False


class UpdateRunner(QObject):
    stepStarted = Signal(str)  # label
    finished = Signal(bool, str)  # ok, message
    # The progress bar under the window's buttons: its text, value and
    # maximum. A maximum of 0 means a moving bar with no count to show, which
    # only the Flatpak steps and a cancelled run use.
    progressChanged = Signal(str, int, int)

    def __init__(self, terminal, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._terminal = terminal
        self._queue: list[Step] = []
        self._session: PtySession | None = None
        self._running = False
        self._failed_label: str | None = None
        self._step: Step | None = None
        self._step_no = 0
        self._steps = 0
        self._progress: ZypperProgress | None = None
        # Set once Ctrl-C has gone to a step: zypper may still finish the
        # package it is on, and the bar must not carry on as if nothing
        # happened.
        self._cancelling = False
        self._last_progress: tuple[str, int, int] | None = None
        # After the zypper step's last package, while its scripts, snapshot
        # and clean-up run, this moves the bar on by the clock
        # (progress.finishing_permille). None until then.
        self._finishing_since: float | None = None
        self._creep = QTimer(self)
        self._creep.setInterval(500)
        self._creep.timeout.connect(self._emit_progress)

    @property
    def is_running(self) -> bool:
        return self._running

    def build_queue(
        self,
        *,
        do_zypper: bool,
        dup_args: list[str] | None = None,
        cleanup: bool = False,
        do_flatpak_system: bool = False,
        do_flatpak_user: bool = False,
    ) -> list[Step]:
        steps: list[Step] = []
        if do_zypper:
            argv = ["pkexec", resolve_helper(HELPER_RUN_UPDATE)]
            if cleanup:
                argv.append("--cleanup")
            argv += dup_args or []
            steps.append(
                Step(
                    "Updating the system",
                    argv,
                    "The system update",
                    counts_packages=True,
                    download_only=_downloads_only(dup_args or []),
                )
            )
        if do_flatpak_system:
            steps.append(
                Step(
                    "Updating Flatpak apps for all users",
                    ["flatpak", "update"],
                    "The Flatpak update for all users",
                )
            )
        if do_flatpak_user:
            steps.append(
                Step(
                    "Updating your Flatpak apps",
                    ["flatpak", "--user", "update"],
                    "The update of your Flatpak apps",
                )
            )
        return steps

    def start(self, steps: list[Step]) -> None:
        if self._running or not steps:
            return
        self._queue = list(steps)
        self._running = True
        self._failed_label = None
        self._step_no = 0
        self._steps = len(steps)
        self._cancelling = False
        self._last_progress = None
        self._stop_creeping()
        self._terminal.reset()
        self._next()

    def cancel(self) -> bool:
        """Ask the running step to stop. False if nothing could be asked.

        Ctrl-C first, because the zypper step runs as root through pkexec and a
        signal from this process would be refused; SIGTERM is only a fallback
        for the flatpak steps, which run as us.
        """
        if self._session is None or not self._session.is_running:
            return False
        self._queue.clear()  # stop at the current step, whatever it answers
        asked = self._session.interrupt() or self._session.terminate()
        if asked:
            self._cancelling = True
            self._stop_creeping()
            self._emit_progress()
        return asked

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
        self._step = step
        self._step_no += 1
        self._progress = (
            ZypperProgress(step.download_only) if step.counts_packages else None
        )
        session.output.connect(self._on_output)
        self._emit_progress()
        rows, cols = self._terminal.grid_size()
        session.start(step.argv, rows=rows, cols=cols)

    def _on_output(self, data: bytes) -> None:
        if self._progress is None or self._cancelling:
            return
        if self._progress.feed(data):
            self._emit_progress()

    def _emit_progress(self) -> None:
        if self._cancelling:
            update = ("Stopping the update", 0, 0)
        elif self._step is None:
            return
        else:
            snap = self._progress.snapshot if self._progress else None
            text = describe(self._step.label, snap, self._step_no, self._steps)
            if snap is None:
                # Not zypper: nothing to count, so the bar moves.
                update = (text, 0, 0)
            elif snap.phase is Phase.FINISHING:
                # Every package is in; scripts, the closing snapshot and the
                # clean-up are left, and zypper counts none of them.
                if self._finishing_since is None:
                    self._finishing_since = time.monotonic()
                    self._creep.start()
                elapsed = time.monotonic() - self._finishing_since
                update = (text, finishing_permille(elapsed), 1000)
            else:
                # One bar for the whole step, empty until the first count.
                update = (text, snap.permille, 1000)
        # zypper redraws its lines many times a second; only a change is sent.
        if update != self._last_progress:
            self._last_progress = update
            self.progressChanged.emit(*update)

    def _stop_creeping(self) -> None:
        self._creep.stop()
        self._finishing_since = None

    def _step_done(self, step: Step, code: int) -> None:
        self._stop_creeping()
        if self._session is not None:
            self._terminal.detach()
            self._session.deleteLater()
            self._session = None

        # zypper: 0 ok, 102 reboot needed, 103 restart needed - all successful.
        if code in (0, 102, 103):
            self._terminal.append_notice("\x1b[1;32m*** done ***\x1b[0m")
            self._next()
            return

        self._running = False
        self._queue.clear()
        self._failed_label = step.label
        # The terminal keeps the exit code as the record of what happened; the
        # message goes to the window's banner, so it is plain words.
        if code < 0:
            record = f"“{step.label}” was cancelled."
            reason = (
                f"{step.what} was cancelled. The terminal below shows how far "
                "it got."
            )
        else:
            record = f"“{step.label}” failed (exit {code})."
            reason = (
                f"{step.what} did not finish. The terminal below shows what "
                "happened."
            )
        self._terminal.append_notice(f"\x1b[1;31m*** {record} ***\x1b[0m")
        self.finished.emit(False, reason)
