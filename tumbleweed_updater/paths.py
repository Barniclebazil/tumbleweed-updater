"""Filesystem locations shared between the GUI and the privileged helpers.

Kept in one place so the RPM packaging and the code agree on paths.
"""

from __future__ import annotations

import os
import re

# Directory the periodic checker writes its result into. A tmpfs path (/run) is
# used deliberately: the data is disposable and should not survive a reboot.
STATUS_DIR = "/run/tumbleweed-updater"
STATUS_FILE = os.path.join(STATUS_DIR, "status.json")

# State that must outlive a reboot, so not /run. There is exactly one thing in
# it: the list of software sources helper/run-update switched off for the
# duration of one upgrade. If the machine loses power between switching them
# off and putting them back, helper/check finds this file on its next run and
# finishes the job. Created at runtime by whichever helper writes it; nothing
# in the packaging ships it.
STATE_DIR = "/var/lib/tumbleweed-updater"
SOURCES_TO_RESTORE = os.path.join(STATE_DIR, "sources-to-restore.json")

# Helpers installed by the package. Invoked through pkexec; the paths are
# referenced verbatim by the polkit policy, so do not change one without the
# other.
LIBEXEC_DIR = "/usr/libexec/tumbleweed-updater"
HELPER_CHECK = os.path.join(LIBEXEC_DIR, "check")
HELPER_SET_INTERVAL = os.path.join(LIBEXEC_DIR, "set-interval")
HELPER_RUN_UPDATE = os.path.join(LIBEXEC_DIR, "run-update")
HELPER_SNAPSHOTS = os.path.join(LIBEXEC_DIR, "snapshots")
# Rollback and delete live in their own helper, behind their own polkit action,
# so that they always prompt instead of riding the cached authorisation the
# read-only listing keeps alive.
HELPER_SNAPSHOTS_MANAGE = os.path.join(LIBEXEC_DIR, "snapshots-manage")
# Switching a software source on or off. There is no read-side helper to go
# with it: `zypper repos` works for an ordinary user, so the GUI lists them
# itself and only comes here to change one.
HELPER_REPOS = os.path.join(LIBEXEC_DIR, "repos")

# When running straight from a source checkout (no RPM installed), the helpers
# live next to the repo. resolve_helper() prefers the installed copy.
_REPO_HELPERS = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "helper"
)


def resolve_helper(installed_path: str) -> str:
    if os.path.exists(installed_path):
        return installed_path
    local = os.path.join(_REPO_HELPERS, os.path.basename(installed_path))
    return local if os.path.exists(local) else installed_path


_VERSION_RE = re.compile(r'^__version__\s*=\s*"([^"]+)"', re.MULTILINE)


def installed_version() -> str | None:
    """Read ``__version__`` straight off the on-disk ``__init__.py``.

    Bypasses the already-imported ``tumbleweed_updater`` module (whose
    ``__version__`` stays whatever it was at process start) so a long-running
    GUI can notice its own package files were replaced by a newer version
    underneath it, e.g. by a ``zypper dup`` that upgraded this package too.
    """
    init_file = os.path.join(os.path.dirname(os.path.abspath(__file__)), "__init__.py")
    try:
        with open(init_file, "r", encoding="utf-8") as fh:
            text = fh.read()
    except OSError:
        return None
    match = _VERSION_RE.search(text)
    return match.group(1) if match else None


# polkit action IDs (see data/org.opensuse.tumbleweedupdater.policy).
ACTION_CHECK = "org.opensuse.tumbleweedupdater.check"
ACTION_SET_INTERVAL = "org.opensuse.tumbleweedupdater.set-interval"
ACTION_UPDATE = "org.opensuse.tumbleweedupdater.update"
ACTION_SNAPSHOTS = "org.opensuse.tumbleweedupdater.snapshots"
ACTION_SNAPSHOTS_MANAGE = "org.opensuse.tumbleweedupdater.snapshots-manage"
ACTION_REPOS = "org.opensuse.tumbleweedupdater.repos"

# systemd unit that runs HELPER_CHECK on a timer.
CHECK_TIMER = "tumbleweed-updater-check.timer"
CHECK_TIMER_DROPIN = (
    "/etc/systemd/system/tumbleweed-updater-check.timer.d/override.conf"
)
