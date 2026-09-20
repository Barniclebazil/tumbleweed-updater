"""Coexisting with PackageKit over the libzypp lock.

Qt-free on purpose: the root helpers import this (see the conventions in
CLAUDE.md).

Only one process at a time may hold the libzypp lock, and the holder records
its pid in ``/run/zypp.pid``. On a stock Plasma install the usual holder is
``packagekitd``, which nothing starts deliberately: ``packagekit.service`` is a
static, D-Bus-activated unit, so any traffic at all to
``org.freedesktop.PackageKit`` launches it as root.

What the daemon actually does, measured rather than assumed:

* It takes the lock when a transaction starts and releases it the moment that
  transaction finishes. An idle daemon does **not** hold the lock, even though
  it stays alive for ``ShutdownTimeout`` (15s) afterwards.
* ``org.freedesktop.PackageKit.SuggestDaemonQuit`` therefore cannot help. It
  returns success immediately but is ignored while any transaction is in the
  daemon's list, which is exactly and only when the lock is held. Asking it to
  quit is not implemented here for that reason.
* Cancelling the transaction outright would work, but ``cancel-foreign`` is
  ``auth_admin_keep`` even for an active local session, so it would raise a
  password prompt to save a wait of seconds. Not worth it.

So the answer is to wait, which is what this module does. That is a partial
fix and is meant to be: a refresh has been measured here at anything from 15
seconds to over two minutes, depending on how much repository metadata it
decides to fetch, so waiting converts many failures into delays but not all of
them. The real fix is not to have PackageKit woken in the first place, which is
``autostart.py``'s job.

libzypp **truncates** the pid file rather than unlinking it when it lets go, so
an empty file means the lock is free even with packagekitd still alive.
"""

from __future__ import annotations

import os
import time

ZYPP_PID_FILE = "/run/zypp.pid"

# Matched against the basename of argv[0]. comm is NOT a usable substitute:
# libzypp renames the main thread, so a running packagekitd appears in
# /proc/<pid>/comm (and to pgrep) as "Zypp-main". That name is deliberately not
# matched, because a running zypper would carry it too.
PACKAGEKIT_NAMES = ("packagekitd", "PackageKit")

# Waiting budgets. A refresh has been measured here at 15s to over 120s. The
# check helper retries anyway, so it waits briefly and lets its own retry delay
# provide the patience; an interactive upgrade waits much longer, because
# failing an upgrade to save a couple of minutes is the wrong trade and the
# user can see it happening.
QUICK_WAIT_S = 5.0
DEFAULT_WAIT_S = 20.0
UPDATE_WAIT_S = 120.0
POLL_S = 0.5


def _process_name(pid: int, proc: str) -> str | None:
    """argv[0] of a live process, or None if it is gone."""
    try:
        with open(f"{proc}/{pid}/cmdline", "rb") as fh:
            argv0 = fh.read().split(b"\0", 1)[0]
        if argv0:
            return argv0.decode("utf-8", "replace")
    except OSError:
        pass
    # Kernel threads have an empty cmdline; comm is always there. It is
    # truncated to 15 characters, which is part of why it is only a fallback.
    try:
        with open(f"{proc}/{pid}/comm", encoding="utf-8", errors="replace") as fh:
            return fh.read().strip() or None
    except OSError:
        return None


def lock_holder(
    pid_file: str = ZYPP_PID_FILE, proc: str = "/proc"
) -> tuple[int, str] | None:
    """``(pid, argv0)`` of whoever holds the zypp lock, or None if it is free.

    "Free" covers a missing file, an empty one (the normal case once the lock
    is released), an unparseable one, and a pid with no live process behind it
    (a stale file left by a crash).
    """
    try:
        with open(pid_file, encoding="utf-8", errors="replace") as fh:
            raw = fh.readline().strip()
    except OSError:
        return None
    if not raw:
        return None
    try:
        pid = int(raw.split(":")[0])
    except ValueError:
        return None
    if pid <= 0:
        return None
    name = _process_name(pid, proc)
    if name is None:
        return None
    return pid, name


def holder_is_packagekit(holder: tuple[int, str] | None) -> bool:
    if holder is None:
        return False
    return os.path.basename(holder[1]) in PACKAGEKIT_NAMES


def describe_holder(holder: tuple[int, str] | None) -> str:
    if holder is None:
        return "the package lock is free"
    pid, name = holder
    if holder_is_packagekit(holder):
        return f"PackageKit is using the package system (pid {pid})"
    return f"the package lock is held by {name} (pid {pid})"


def wait_for_lock(
    timeout_s: float = DEFAULT_WAIT_S,
    poll_s: float = POLL_S,
    pid_file: str = ZYPP_PID_FILE,
    proc: str = "/proc",
    on_progress=None,
    progress_every_s: float = 15.0,
) -> tuple[bool, str]:
    """Wait for PackageKit to finish with the package lock.

    Returns ``(free, human-readable detail)``. Never raises, never signals
    anything, never changes anything.

    Only PackageKit is waited for. Anything else holding the lock is somebody's
    own ``zypper``, which can legitimately run for a very long time and is not
    something to sit behind silently, so that case returns at once.

    *on_progress* is called with a seconds-waited-so-far count every
    *progress_every_s*, so a caller with a terminal in front of it can show
    that something is still happening rather than looking hung.
    """
    holder = lock_holder(pid_file, proc)
    if holder is None:
        return True, describe_holder(None)
    if not holder_is_packagekit(holder):
        return False, describe_holder(holder)

    started = time.monotonic()
    deadline = started + timeout_s
    next_report = started + progress_every_s
    while True:
        now = time.monotonic()
        if now >= deadline:
            return False, (
                f"PackageKit was still using the package system after "
                f"{timeout_s:.0f}s (pid {holder[0]})"
            )
        if on_progress is not None and now >= next_report:
            next_report = now + progress_every_s
            on_progress(now - started)
        time.sleep(poll_s)
        holder = lock_holder(pid_file, proc)
        if holder is None:
            waited = time.monotonic() - started
            return True, (
                f"PackageKit finished and released the package lock "
                f"after {waited:.0f}s"
            )
        if not holder_is_packagekit(holder):
            return False, describe_holder(holder)
