"""Filesystem locations shared between the GUI and the privileged helpers.

Kept in one place so the RPM packaging and the code agree on paths.
"""

from __future__ import annotations

import os

# Directory the periodic checker writes its result into. A tmpfs path (/run) is
# used deliberately: the data is disposable and should not survive a reboot.
STATUS_DIR = "/run/tumbleweed-updater"
STATUS_FILE = os.path.join(STATUS_DIR, "status.json")

# Helpers installed by the package. Invoked through pkexec; the paths are
# referenced verbatim by the polkit policy, so do not change one without the
# other.
LIBEXEC_DIR = "/usr/libexec/tumbleweed-updater"
HELPER_CHECK = os.path.join(LIBEXEC_DIR, "check")
HELPER_SET_INTERVAL = os.path.join(LIBEXEC_DIR, "set-interval")
HELPER_RUN_UPDATE = os.path.join(LIBEXEC_DIR, "run-update")

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


# polkit action IDs (see data/org.opensuse.tumbleweedupdater.policy).
ACTION_CHECK = "org.opensuse.tumbleweedupdater.check"
ACTION_SET_INTERVAL = "org.opensuse.tumbleweedupdater.set-interval"
ACTION_UPDATE = "org.opensuse.tumbleweedupdater.update"

# systemd unit that runs HELPER_CHECK on a timer.
CHECK_TIMER = "tumbleweed-updater-check.timer"
CHECK_TIMER_DROPIN = (
    "/etc/systemd/system/tumbleweed-updater-check.timer.d/override.conf"
)
