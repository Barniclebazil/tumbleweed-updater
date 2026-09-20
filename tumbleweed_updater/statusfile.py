"""Serialising :class:`~tumbleweed_updater.sources.UpdateStatus` to and from the
JSON file that the privileged checker and the GUI use to communicate.

The checker (running as root) writes :data:`~tumbleweed_updater.paths.STATUS_FILE`;
the GUI reads it and watches it for changes. Keeping the schema in one module
means the two processes cannot drift apart.
"""

from __future__ import annotations

import json
import os
import tempfile
from datetime import datetime, timezone

from .paths import STATUS_DIR, STATUS_FILE
from .sources import (
    Action,
    FlatpakRef,
    FlatpakResult,
    Package,
    UpdateStatus,
    ZypperResult,
)

SCHEMA = 1


def to_dict(status: UpdateStatus) -> dict:
    return {
        "schema": SCHEMA,
        "generated": status.generated
        or datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "snapshots_ok": status.snapshots_ok,
        "zypper": {
            "error": status.zypper.error,
            # Added after SCHEMA 1 shipped. from_dict() reads it with .get, so
            # an older status file simply reads back as "not locked" and an
            # older reader ignores the key: no schema bump is needed.
            "locked": status.zypper.locked,
            "download_size": status.zypper.download_size,
            "space_diff": status.zypper.space_diff,
            "need_reboot": status.zypper.need_reboot,
            "need_restart": status.zypper.need_restart,
            "packages": [
                {
                    "name": p.name,
                    "action": p.action.value,
                    "new": p.new_version,
                    "old": p.old_version,
                    "arch": p.arch,
                }
                for p in status.zypper.packages
            ],
        },
        "flatpak": {
            "error": status.flatpak.error,
            "refs": [
                {
                    "id": r.ref_id,
                    "version": r.version,
                    "branch": r.branch,
                    "origin": r.origin,
                    "installation": r.installation,
                }
                for r in status.flatpak.refs
            ],
        },
    }


def from_dict(data: dict) -> UpdateStatus:
    z = data.get("zypper", {}) or {}
    f = data.get("flatpak", {}) or {}
    zres = ZypperResult(
        error=z.get("error"),
        locked=bool(z.get("locked", False)),
        download_size=int(z.get("download_size", 0) or 0),
        space_diff=int(z.get("space_diff", 0) or 0),
        need_reboot=bool(z.get("need_reboot", False)),
        need_restart=bool(z.get("need_restart", False)),
        packages=[
            Package(
                name=p.get("name", "?"),
                action=_action(p.get("action")),
                new_version=p.get("new", ""),
                old_version=p.get("old", ""),
                arch=p.get("arch", ""),
            )
            for p in z.get("packages", [])
        ],
    )
    fres = FlatpakResult(
        error=f.get("error"),
        refs=[
            FlatpakRef(
                ref_id=r.get("id", "?"),
                version=r.get("version", ""),
                branch=r.get("branch", ""),
                origin=r.get("origin", ""),
                installation=r.get("installation", "system"),
            )
            for r in f.get("refs", [])
        ],
    )
    return UpdateStatus(
        zypper=zres,
        flatpak=fres,
        generated=data.get("generated", ""),
        snapshots_ok=bool(data.get("snapshots_ok", True)),
    )


def _action(value: str | None) -> Action:
    try:
        return Action(value)
    except ValueError:
        return Action.UPGRADE


def read(path: str = STATUS_FILE) -> UpdateStatus | None:
    """Parse the status file, or return None if it is missing or unusable.

    Every failure mode is folded into None on purpose: this is called from a
    QFileSystemWatcher slot, where an escaping exception aborts the process.
    The wrong shape (a string where a mapping is expected, say) raises
    TypeError or AttributeError rather than ValueError, so catch broadly.
    """
    try:
        with open(path, "r", encoding="utf-8") as fh:
            return from_dict(json.load(fh))
    except Exception:
        return None


def write(status: UpdateStatus, path: str = STATUS_FILE) -> None:
    """Atomically replace *path*. Called by the root checker."""
    directory = os.path.dirname(path) or STATUS_DIR
    os.makedirs(directory, exist_ok=True)
    # pkexec does not reset the umask, so when the GUI triggers the check the
    # directory would inherit the user's: 0700 leaves the GUI unable to read
    # its own status file ever again, 0777 leaves a world-writable directory
    # in /run. makedirs(mode=...) is masked too, hence the explicit chmod.
    try:
        os.chmod(directory, 0o755)
    except OSError:
        pass
    fd, tmp = tempfile.mkstemp(dir=directory, suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            json.dump(to_dict(status), fh, indent=2)
            fh.write("\n")
        os.chmod(tmp, 0o644)
        os.replace(tmp, path)
    except BaseException:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise
