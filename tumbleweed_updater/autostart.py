"""XDG autostart entries: this app's own, and suppressing other people's.

Qt-free on purpose (see the conventions in CLAUDE.md), and used from both the
settings dialog and app.py's first-run question.

Two jobs live here:

1. This app's own "start at login" entry, which is a complete desktop file
   written into the user's autostart directory.
2. Switching off Plasma's Discover update notifier. That is a *system* entry in
   /etc/xdg/autostart, which a user cannot edit, so the spec's answer is to
   shadow it with a same-named file in the user's own autostart directory
   carrying ``Hidden=true``. Removing that file restores the original. This is
   exactly what Plasma's own Autostart settings page does.

Why suppress it at all: the notifier polls PackageKit, PackageKit is
D-Bus-activated, and starting it takes the libzypp lock that zypper needs. It
is the only thing on a stock Plasma install that wakes it. Discover itself is
untouched, so installing, removing and managing repositories all still work.
"""

from __future__ import annotations

import os
import shutil
import signal
import time

OWN_ENTRY = "tumbleweed-updater.desktop"

# Plasma's update notifier. The binary is a separate program from Discover.
PLASMA_NOTIFIER_ENTRY = "org.kde.discover.notifier.desktop"
PLASMA_NOTIFIER_EXE = "/usr/libexec/DiscoverNotifier"

SYSTEM_AUTOSTART_DIRS = ("/etc/xdg/autostart",)

_OWN_BODY = """\
[Desktop Entry]
Type=Application
Name=Tumbleweed Updater
Exec={exec} --tray
Icon=tumbleweed-updater
Terminal=false
X-GNOME-Autostart-enabled=true
"""

# A Hidden=true override still has to be a valid desktop entry, so Type, Name
# and Exec are carried over from the system file rather than omitted.
_HIDDEN_BODY = """\
[Desktop Entry]
Type=Application
Name={name}
Exec={exec}
Hidden=true
"""


def autostart_dir() -> str:
    """The user's autostart directory.

    Read from the environment at call time, rather than pinned to ~/.config at
    import: that is what the XDG spec says, and it keeps the tests out of the
    real user's configuration.
    """
    base = os.environ.get("XDG_CONFIG_HOME") or os.path.expanduser("~/.config")
    return os.path.join(base, "autostart")


def entry_path(basename: str) -> str:
    """Where the user-level copy or override of *basename* lives."""
    return os.path.join(autostart_dir(), basename)


def system_entry_path(basename: str) -> str | None:
    """The system-wide entry being shadowed, if there is one."""
    for directory in SYSTEM_AUTOSTART_DIRS:
        candidate = os.path.join(directory, basename)
        if os.path.exists(candidate):
            return candidate
    return None


def desktop_exec(path: str) -> str:
    """Quote *path* for a desktop file's Exec= key.

    Per the Desktop Entry spec: reserved characters mean the argument must be
    double-quoted, and backslash, double quote, backtick and dollar are escaped
    with a backslash inside those quotes.
    """
    if not any(c in path for c in ' \t\n"\'\\><~|&;$*?#()`'):
        return path
    escaped = path
    for ch in "\\`$\"":
        escaped = escaped.replace(ch, "\\" + ch)
    return f'"{escaped}"'


def read_keys(path: str, keys: tuple[str, ...]) -> dict[str, str]:
    """Plain (untranslated) keys from a desktop file's [Desktop Entry] group.

    Deliberately minimal: it skips ``Name[de]=``-style translations and stops
    at the next group header, which is all that is needed to copy a couple of
    values into an override.
    """
    found: dict[str, str] = {}
    try:
        with open(path, encoding="utf-8", errors="replace") as fh:
            in_group = False
            for line in fh:
                line = line.strip()
                if line.startswith("["):
                    if in_group:
                        break
                    in_group = line == "[Desktop Entry]"
                    continue
                if not in_group or "=" not in line or line.startswith("#"):
                    continue
                key, _, value = line.partition("=")
                key = key.strip()
                if key in keys and key not in found:
                    found[key] = value.strip()
    except OSError:
        return {}
    return found


def _write(basename: str, body: str) -> str:
    path = entry_path(basename)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as fh:
        fh.write(body)
    return path


def _remove(basename: str) -> bool:
    try:
        os.unlink(entry_path(basename))
        return True
    except FileNotFoundError:
        return False


# -- this app's own entry -------------------------------------------------- #


def set_own_autostart(enabled: bool) -> None:
    if enabled:
        exec_path = shutil.which("tumbleweed-updater") or "tumbleweed-updater"
        _write(OWN_ENTRY, _OWN_BODY.format(exec=desktop_exec(exec_path)))
    else:
        _remove(OWN_ENTRY)


def own_autostart_enabled() -> bool:
    return os.path.exists(entry_path(OWN_ENTRY))


# -- shadowing somebody else's entry --------------------------------------- #


def is_installed(basename: str = PLASMA_NOTIFIER_ENTRY) -> bool:
    """Is there a system entry to suppress? False on any non-Plasma desktop."""
    return system_entry_path(basename) is not None


def is_hidden(basename: str = PLASMA_NOTIFIER_ENTRY) -> bool:
    """Has this user shadowed it with a Hidden=true override?"""
    path = entry_path(basename)
    if not os.path.exists(path):
        return False
    return read_keys(path, ("Hidden",)).get("Hidden", "").lower() == "true"


def set_hidden(basename: str, hidden: bool, *, name: str = "", exec_: str = "") -> None:
    """Write or remove the Hidden=true override for a system entry."""
    if not hidden:
        _remove(basename)
        return
    system = system_entry_path(basename)
    original = read_keys(system, ("Name", "Exec")) if system else {}
    _write(
        basename,
        _HIDDEN_BODY.format(
            name=original.get("Name") or name or basename,
            exec=original.get("Exec") or exec_ or "/bin/true",
        ),
    )


# -- stopping the notifier that is already running ------------------------- #


def notifier_pids(proc: str = "/proc") -> list[int]:
    """Live DiscoverNotifier processes belonging to this user.

    Matched on the basename of argv[0], not on a substring of the whole command
    line: ``pgrep -f DiscoverNotifier`` would also match an editor with
    DiscoverNotifier.cpp open. ``pgrep`` without ``-f`` cannot be used either,
    because /proc/<pid>/comm truncates to 15 characters.

    Restricted to our own uid, which is also why no privileges are needed.
    """
    uid = os.getuid()
    mine = os.getpid()
    pids: list[int] = []
    try:
        entries = os.listdir(proc)
    except OSError:
        return pids
    for entry in entries:
        if not entry.isdigit():
            continue
        pid = int(entry)
        if pid == mine:
            continue
        try:
            if os.stat(f"{proc}/{entry}").st_uid != uid:
                continue
            with open(f"{proc}/{entry}/cmdline", "rb") as fh:
                argv0 = fh.read().split(b"\0", 1)[0].decode("utf-8", "replace")
        except OSError:
            # /proc races constantly; a process that went away is not an error.
            continue
        if not argv0:
            continue
        if os.path.basename(argv0) == os.path.basename(PLASMA_NOTIFIER_EXE):
            pids.append(pid)
    return pids


def stop_notifier(proc: str = "/proc", timeout_s: float = 3.0) -> int:
    """SIGTERM this user's DiscoverNotifier processes. Returns how many.

    SIGTERM only, never SIGKILL: if it declines to go, the Hidden=true override
    still takes effect at the next login, and the cost of failing here is one
    redundant notification rather than anything broken. Plasma's generated unit
    has Restart=no, so nothing brings it back.
    """
    pids = notifier_pids(proc)
    signalled = 0
    for pid in pids:
        try:
            os.kill(pid, signal.SIGTERM)
            signalled += 1
        except (ProcessLookupError, PermissionError, OSError):
            continue
    deadline = time.monotonic() + timeout_s
    while signalled and time.monotonic() < deadline:
        if not notifier_pids(proc):
            break
        time.sleep(0.1)
    return signalled


def suppress_plasma_notifier(hidden: bool) -> tuple[bool, str]:
    """Switch Plasma's update notifier off (or back on). ``(ok, detail)``."""
    try:
        set_hidden(PLASMA_NOTIFIER_ENTRY, hidden, name="Discover",
                   exec_=f"{PLASMA_NOTIFIER_EXE} --check-delay 20")
    except OSError as exc:
        return False, f"Could not change the autostart entry: {exc}"
    if not hidden:
        return True, "Plasma's update notifier will start again at your next login."
    stopped = stop_notifier()
    if stopped:
        return True, "Plasma's update notifier is off."
    return True, "Plasma's update notifier is off from your next login."
