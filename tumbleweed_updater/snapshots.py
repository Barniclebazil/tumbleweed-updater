"""Listing and managing Btrfs snapshots via ``snapper``.

Everything here runs as root (inside ``helper/snapshots``): ``snapper list``
refuses to run as a normal user ("No permissions."), so even read-only
listing needs the privileged helper, same as the zypper dry-run in
:mod:`tumbleweed_updater.sources`.

``snapper --jsonout list`` nests its snapshots under the config name (usually
"root"): ``{"root": [ {...}, {...} ]}``, not a flat array - see
client/snapper/cmd-list.cc in the snapper source. ``snapper status`` has no
JSON mode at all; it always prints ``"<code> <path>"`` lines, so that output
is parsed as plain text instead.
"""

from __future__ import annotations

import json
import subprocess
from dataclasses import dataclass, field


@dataclass(frozen=True)
class Snapshot:
    number: int
    type: str  # "single", "pre", "post"
    date: str = ""
    description: str = ""
    cleanup: str = ""
    pre_number: int | None = None  # only set for type == "post"


@dataclass
class SnapshotsResult:
    snapshots: list[Snapshot] = field(default_factory=list)
    error: str | None = None


@dataclass(frozen=True)
class FileChange:
    status: str  # snapper's raw status-code string, e.g. "c...."
    path: str


@dataclass
class StatusResult:
    changes: list[FileChange] = field(default_factory=list)
    error: str | None = None


def _int_or_none(value: object) -> int | None:
    if value in (None, ""):
        return None
    try:
        return int(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return None


def parse_snapper_list_json(text: str) -> SnapshotsResult:
    """Parse ``snapper --jsonout list`` output."""
    result = SnapshotsResult()
    text = text.strip()
    if not text:
        return result
    try:
        data = json.loads(text)
    except json.JSONDecodeError:
        result.error = "could not parse snapper output"
        return result
    if not isinstance(data, dict):
        result.error = "unexpected snapper output"
        return result

    for entries in data.values():
        if not isinstance(entries, list):
            continue
        for entry in entries:
            if not isinstance(entry, dict):
                continue
            number = _int_or_none(entry.get("number"))
            if number is None:
                continue
            result.snapshots.append(
                Snapshot(
                    number=number,
                    type=str(entry.get("type") or "single"),
                    date=str(entry.get("date") or ""),
                    description=str(entry.get("description") or ""),
                    cleanup=str(entry.get("cleanup") or ""),
                    pre_number=_int_or_none(entry.get("pre-number")),
                )
            )
    result.snapshots.sort(key=lambda s: s.number)
    return result


def list_snapshots(timeout: int = 30) -> SnapshotsResult:
    """Run ``snapper --jsonout list --type all`` and parse the result."""
    try:
        proc = subprocess.run(
            ["snapper", "--jsonout", "list", "--type", "all"],
            capture_output=True,
            text=True,
            timeout=timeout,
        )
    except FileNotFoundError:
        return SnapshotsResult(error="snapper is not installed")
    except subprocess.TimeoutExpired:
        return SnapshotsResult(error="snapper timed out")
    if proc.returncode != 0:
        stderr = proc.stderr.strip().splitlines()
        return SnapshotsResult(
            error=stderr[-1] if stderr else f"snapper exited {proc.returncode}"
        )
    return parse_snapper_list_json(proc.stdout)


def parse_snapper_status(text: str) -> list[FileChange]:
    """Parse ``snapper status <n1>..<n2>``: ``"<code> <path>"`` per line."""
    changes = []
    for line in text.splitlines():
        line = line.rstrip("\n")
        if not line.strip():
            continue
        parts = line.split(" ", 1)
        if len(parts) != 2:
            continue
        changes.append(FileChange(status=parts[0], path=parts[1]))
    return changes


def status_between(pre: int, post: int, timeout: int = 60) -> StatusResult:
    """File-level changes between two snapshots (usually a pre/post pair)."""
    try:
        proc = subprocess.run(
            ["snapper", "status", f"{pre}..{post}"],
            capture_output=True,
            text=True,
            timeout=timeout,
        )
    except FileNotFoundError:
        return StatusResult(error="snapper is not installed")
    except subprocess.TimeoutExpired:
        return StatusResult(error="snapper timed out")
    if proc.returncode != 0:
        stderr = proc.stderr.strip().splitlines()
        return StatusResult(
            error=stderr[-1] if stderr else f"snapper exited {proc.returncode}"
        )
    return StatusResult(changes=parse_snapper_status(proc.stdout))


def _run_mutation(argv: list[str], timeout: int) -> str | None:
    """Run a snapper command that has no useful stdout. None on success, else
    an error message."""
    try:
        proc = subprocess.run(argv, capture_output=True, text=True, timeout=timeout)
    except FileNotFoundError:
        return "snapper is not installed"
    except subprocess.TimeoutExpired:
        return "snapper timed out"
    if proc.returncode != 0:
        stderr = proc.stderr.strip().splitlines()
        return stderr[-1] if stderr else f"snapper exited {proc.returncode}"
    return None


def rollback_to(number: int, timeout: int = 60) -> str | None:
    """Set *number* as the default subvolume for next boot (no effect on the
    running system - a reboot is needed). None on success, else an error."""
    return _run_mutation(["snapper", "rollback", str(number)], timeout)


def delete_snapshot(number: int, timeout: int = 60) -> str | None:
    """Permanently delete a snapshot. None on success, else an error."""
    return _run_mutation(["snapper", "delete", str(number)], timeout)
