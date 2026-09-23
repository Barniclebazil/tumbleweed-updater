"""Discovering what can be updated.

Two update sources are supported:

* **zypper** - Tumbleweed is a rolling release, so the meaningful operation is
  ``zypper dup`` (distribution upgrade), not ``zypper update``. We ask zypper
  for a machine-readable dry run and parse the ``<install-summary>`` block.
* **flatpak** - both the system-wide and per-user installations.

The zypper half needs root: ``zypper dup --dry-run`` refuses to run as a normal
user even though it changes nothing, so :func:`check_zypper` is only ever called
from the privileged ``helper/check``, which refreshes first and then runs it
against that metadata (``--no-refresh``). The Flatpak half runs as the user,
from the GUI.
"""

from __future__ import annotations

import subprocess
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field
from enum import Enum


def _int(value: str | None) -> int:
    try:
        return int(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return 0


class Action(str, Enum):
    UPGRADE = "upgrade"
    DOWNGRADE = "downgrade"
    INSTALL = "install"
    REINSTALL = "reinstall"
    REMOVE = "remove"
    CHANGE_ARCH = "change-arch"


# Maps the zypper <install-summary> child element to our Action enum. Element
# names come from /usr/share/zypper/xml/xmlout.rnc.
_SUMMARY_TAGS = {
    "to-upgrade": Action.UPGRADE,
    "to-upgrade-change-arch": Action.UPGRADE,
    "to-downgrade": Action.DOWNGRADE,
    "to-downgrade-change-arch": Action.DOWNGRADE,
    "to-install": Action.INSTALL,
    "to-reinstall": Action.REINSTALL,
    "to-remove": Action.REMOVE,
    "to-change-arch": Action.CHANGE_ARCH,
}


@dataclass(frozen=True)
class Package:
    name: str
    action: Action
    new_version: str = ""
    old_version: str = ""
    arch: str = ""

    @property
    def summary_line(self) -> str:
        if self.old_version and self.new_version:
            return f"{self.old_version} → {self.new_version}"
        return self.new_version or self.old_version


@dataclass(frozen=True)
class FlatpakRef:
    ref_id: str
    version: str = ""
    branch: str = ""
    origin: str = ""
    installation: str = "system"  # "system" or "user"


@dataclass
class ZypperResult:
    packages: list[Package] = field(default_factory=list)
    download_size: int = 0  # bytes
    space_diff: int = 0  # bytes, may be negative
    need_reboot: bool = False
    need_restart: bool = False
    error: str | None = None
    locked: bool = False
    # Sources zypper could not reach during the refresh, as (alias, display
    # name) pairs. Not an error: the dry run below still succeeds from the
    # metadata already on disk, and the upgrade still runs. The window turns
    # these into the "couldn't reach" warning; only the alias is ever passed
    # back to a helper.
    failed_repos: list[tuple[str, str]] = field(default_factory=list)

    @property
    def count(self) -> int:
        return len(self.packages)


def human_bytes(n: int) -> str:
    step = 1024.0
    value = float(abs(n))
    for unit in ("B", "KiB", "MiB", "GiB", "TiB"):
        if value < step:
            sign = "-" if n < 0 else ""
            return f"{sign}{value:.0f} {unit}" if unit == "B" else f"{sign}{value:.1f} {unit}"
        value /= step
    return f"{n} B"


@dataclass
class FlatpakResult:
    refs: list[FlatpakRef] = field(default_factory=list)
    error: str | None = None

    @property
    def count(self) -> int:
        return len(self.refs)


@dataclass
class UpdateStatus:
    zypper: ZypperResult = field(default_factory=ZypperResult)
    flatpak: FlatpakResult = field(default_factory=FlatpakResult)
    generated: str = ""
    snapshots_ok: bool = True

    @property
    def total(self) -> int:
        return self.zypper.count + self.flatpak.count

    @property
    def has_updates(self) -> bool:
        return self.total > 0


# --------------------------------------------------------------------------- #
# zypper
# --------------------------------------------------------------------------- #

# Read by someone who has never heard of a repository, like everything else
# that reaches the window. The cause is nearly always the one named here, since
# an ordinary upgrade does not raise solver questions.
# Public: mainwindow compares ZypperResult.error against it, to say something
# better than this when it also knows which source went missing. It travels
# through the status file as an ordinary string, so equality is enough.
NEEDS_A_DECISION = (
    "The list of updates couldn’t be worked out. Some of the programs you "
    "have installed came from a software source that is switched off or "
    "can’t be reached, so there is no newer version to offer them. "
    "Switching that source back on is usually the fix."
)


def parse_zypper_dup_xml(xml_text: str) -> ZypperResult:
    """Parse ``zypper --xmlout dup --dry-run`` output.

    zypper emits a stream of elements; we only care about the final
    ``<install-summary>`` and any ``<message type="error">``. The attribute
    names on ``<solvable>`` have drifted between zypper releases, so we probe a
    few spellings for each field.
    """
    result = ZypperResult()

    # zypper wraps everything in a <stream> root, but the leading
    # "<?xml ... ?>" declaration can repeat and the stream may be unterminated
    # if zypper was killed. Wrap defensively.
    text = xml_text.strip()
    if not text:
        result.error = "zypper produced no output"
        return result
    if not text.startswith("<?xml") and not text.startswith("<stream"):
        text = f"<stream>{text}</stream>"
    try:
        root = ET.fromstring(text)
    except ET.ParseError:
        # Retry after forcing a wrapper - handles the unterminated-stream case.
        try:
            root = ET.fromstring(f"<stream>{text}</stream>")
        except ET.ParseError as exc:
            result.error = f"could not parse zypper output: {exc}"
            return result

    errors = [
        (m.text or "").strip()
        for m in root.iter("message")
        if m.get("type") == "error" and (m.text or "").strip()
    ]

    summary = root.find(".//install-summary")
    if summary is None:
        # No summary at all: either nothing to do, or zypper failed before
        # computing one.
        if errors:
            result.error = "; ".join(errors)
        elif root.find(".//prompt") is not None:
            # zypper stopped to ask a question and, being non-interactive, took
            # its own default and gave up. Measured: switch off a source that
            # some installed packages came from, and the solver raises one of
            # these per orphaned package ("does not belong to a distupgrade
            # repository and must be replaced"), so nothing at all is computed
            # and the exit code is a bare 4. Everything it printed is
            # <message type="info"> and a <prompt>, which is why this looks at
            # the element rather than the words: the words are translated, the
            # element name is not.
            result.error = NEEDS_A_DECISION
        return result

    result.download_size = _int(summary.get("download-size"))
    result.space_diff = _int(summary.get("space-usage-diff"))
    result.need_reboot = summary.get("need-reboot") == "true"
    result.need_restart = summary.get("need-restart") == "true"

    for group in summary:
        action = _SUMMARY_TAGS.get(group.tag)
        if action is None:
            continue
        for sol in group.findall("solvable"):
            if sol.get("kind", "package") != "package":
                continue
            result.packages.append(
                Package(
                    name=sol.get("name", "?"),
                    action=action,
                    new_version=sol.get("edition", ""),
                    old_version=sol.get("edition-old", ""),
                    arch=sol.get("arch", ""),
                )
            )

    result.packages.sort(key=lambda p: (p.action.value, p.name))
    # Surface errors only if they left us with nothing usable.
    if errors and not result.packages:
        result.error = "; ".join(errors)
    return result


# zypper's documented exit code for "another process holds the zypp lock"
# (e.g. PackageKit refreshing after NetworkManager reconnects post-resume).
# Locale-independent — used only to decide whether to retry, never for
# matching the (possibly translated) message text.
ZYPPER_EXIT_ZYPP_LOCKED = 7


def check_zypper(timeout: int = 120) -> ZypperResult:
    """Run a dry-run dup against already-refreshed metadata."""
    try:
        proc = subprocess.run(
            [
                "zypper",
                "--non-interactive",
                "--no-refresh",
                "--xmlout",
                "dup",
                "--dry-run",
                "--details",
            ],
            capture_output=True,
            text=True,
            timeout=timeout,
        )
    except FileNotFoundError:
        return ZypperResult(error="zypper is not installed")
    except subprocess.TimeoutExpired:
        return ZypperResult(error="zypper timed out")

    res = parse_zypper_dup_xml(proc.stdout)
    res.locked = proc.returncode == ZYPPER_EXIT_ZYPP_LOCKED
    # Exit codes: 0 ok, 100/101 updates available (for `lu`), 7 zypp locked
    # (see ZYPPER_EXIT_ZYPP_LOCKED), 106 repo issue... For `dup --dry-run` a
    # non-zero code with no parsed packages is a real failure worth showing.
    if res.error is None and proc.returncode not in (0, 100, 101) and not res.packages:
        stderr = proc.stderr.strip().splitlines()
        res.error = stderr[-1] if stderr else f"zypper exited {proc.returncode}"
    return res


# --------------------------------------------------------------------------- #
# flatpak
# --------------------------------------------------------------------------- #

def parse_flatpak_updates(text: str, installation: str) -> list[FlatpakRef]:
    """Parse ``flatpak remote-ls --updates --columns=...`` (tab separated)."""
    refs: list[FlatpakRef] = []
    for line in text.splitlines():
        line = line.strip()
        if not line:
            continue
        cols = [c.strip() for c in line.split("\t")]
        # We request: application, version, branch, origin
        ref_id = cols[0] if cols else ""
        if not ref_id or ref_id.lower() == "application":
            continue
        refs.append(
            FlatpakRef(
                ref_id=ref_id,
                version=cols[1] if len(cols) > 1 else "",
                branch=cols[2] if len(cols) > 2 else "",
                origin=cols[3] if len(cols) > 3 else "",
                installation=installation,
            )
        )
    return refs


def check_flatpak(timeout: int = 60) -> FlatpakResult:
    result = FlatpakResult()
    columns = "--columns=application,version,branch,origin"
    scopes = [("system", ["flatpak"]), ("user", ["flatpak", "--user"])]
    found_any_binary = False
    for installation, base in scopes:
        try:
            proc = subprocess.run(
                [*base, "remote-ls", "--updates", columns],
                capture_output=True,
                text=True,
                timeout=timeout,
            )
        except FileNotFoundError:
            result.error = "flatpak is not installed"
            return result
        except subprocess.TimeoutExpired:
            result.error = "flatpak timed out"
            return result
        found_any_binary = True
        if proc.returncode != 0:
            # A missing user installation is not an error worth surfacing.
            continue
        result.refs.extend(parse_flatpak_updates(proc.stdout, installation))
    if not found_any_binary:
        result.error = "flatpak is not installed"
    return result
