"""Reading and switching zypper's software sources (repositories).

Split the same way as :mod:`tumbleweed_updater.snapshots`: listing is harmless
and works for an ordinary user, while changing a source needs root and goes
through ``helper/repos``. Qt-free, because both the helper and the GUI import
it.

Two things live here that the rest of the app needs:

* :func:`list_repos` - what sources exist, what they are called, and whether
  they are switched on. ``zypper repos`` does *not* need root, so the GUI calls
  this directly.
* :func:`failed_aliases` - which sources a failed ``zypper refresh`` could not
  reach. zypper has no machine-readable refresh output, so this reads the human
  one, anchored on the one part of it that is not translated (see below).

A third pair, :func:`remember_to_restore` and :func:`restore_remembered`, is
the crash net for ``helper/run-update --without-unreachable``: it switches an
unreachable source off for the length of one upgrade and back on afterwards,
and this is what finishes the job if the machine dies in between.

The user-facing word for a repository is "software source"; the strings the
window shows are built in :mod:`tumbleweed_updater.mainwindow`, from the
display *name* here, never the alias.
"""

from __future__ import annotations

import json
import os
import re
import subprocess
import tempfile
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field

from .paths import SOURCES_TO_RESTORE
from .sources import ZYPPER_EXIT_ZYPP_LOCKED


@dataclass(frozen=True)
class Repo:
    alias: str  # what zypper commands take
    name: str = ""  # what the user sees in YaST; may be translated
    enabled: bool = True
    url: str = ""

    @property
    def label(self) -> str:
        """The name to show a person. Falls back to the alias, since a repo
        added with `zypper ar <url> <alias>` has no separate name."""
        return self.name or self.alias


@dataclass
class ReposResult:
    repos: list[Repo] = field(default_factory=list)
    error: str | None = None

    def by_alias(self, alias: str) -> Repo | None:
        for repo in self.repos:
            if repo.alias == alias:
                return repo
        return None


def _bool_attr(value: str | None) -> bool:
    # zypper writes enabled="1"/"0"; be lenient about the spelling anyway.
    return str(value).strip().lower() in ("1", "true", "yes")


def parse_zypper_repos_xml(xml_text: str) -> ReposResult:
    """Parse ``zypper --xmlout repos --details``.

    Shape (see /usr/share/zypper/xml/xmlout.rnc)::

        <stream><repo-list>
          <repo alias="vlc" name="VLC" enabled="1" ...><url>http://…</url></repo>
        </repo-list></stream>
    """
    result = ReposResult()
    try:
        root = ET.fromstring(xml_text)
    except ET.ParseError as exc:
        result.error = f"could not parse the source list: {exc}"
        return result

    for element in root.iter("repo"):
        alias = (element.get("alias") or "").strip()
        if not alias:
            continue
        url = element.findtext("url") or ""
        result.repos.append(
            Repo(
                alias=alias,
                name=(element.get("name") or "").strip(),
                enabled=_bool_attr(element.get("enabled")),
                url=url.strip(),
            )
        )
    return result


def list_repos(timeout: int = 30) -> ReposResult:
    """Every configured source, switched on or not.

    ``--no-refresh`` because this is only reading the configuration: without it
    zypper would try to contact an out-of-date source, which is exactly the
    situation this module exists to report on.
    """
    try:
        proc = subprocess.run(
            [
                "zypper",
                "--non-interactive",
                "--no-refresh",
                "--xmlout",
                "repos",
                "--details",
            ],
            capture_output=True,
            text=True,
            timeout=timeout,
        )
    except FileNotFoundError:
        return ReposResult(error="zypper is not installed")
    except subprocess.TimeoutExpired:
        return ReposResult(error="zypper timed out")

    result = parse_zypper_repos_xml(proc.stdout)
    # Exit 6 is "no repositories defined", which is a legitimate empty answer
    # rather than a failure worth reporting.
    if result.error is None and proc.returncode not in (0, 6) and not result.repos:
        stderr = proc.stderr.strip().splitlines()
        result.error = stderr[-1] if stderr else f"zypper exited {proc.returncode}"
    return result


# zypper prints the failing source as "[<alias>|<url>] Failed to retrieve new
# repository metadata." The surrounding sentences are translated and the
# "Skipping repository 'VLC'" line carries the display *name*, not the alias,
# so this bracketed pair is the only part worth matching. Everything it yields
# is then checked against the real source list before it is used, so a stray
# match cannot turn into an alias the app acts on.
_BRACKETED = re.compile(r"\[([^\[\]|]+)\|[^\[\]]*\]")


def failed_aliases(refresh_output: str, known: list[str] | set[str]) -> list[str]:
    """Aliases of the sources a failed ``zypper refresh`` could not reach.

    *known* is the set of aliases that actually exist; anything else in the
    output is discarded. Order follows the output, and duplicates are dropped,
    since zypper mentions the same source on several lines.
    """
    known_set = set(known)
    found: list[str] = []
    for match in _BRACKETED.finditer(refresh_output):
        alias = match.group(1).strip()
        if alias in known_set and alias not in found:
            found.append(alias)
    return found


# zypper's own words for a held package lock - "System management is locked by
# the application with pid N ... Close this application before trying again." -
# are written for whoever typed the command, and read as nonsense in a dialog
# the user did not type anything into, so they are replaced rather than passed
# on.
_LOCKED_MESSAGE = (
    "Something else on this computer was installing or checking for software "
    "at the time. Wait for that to finish, then try again."
)


def set_enabled(alias: str, enabled: bool, timeout: int = 30) -> str | None:
    """Switch a source on or off. None on success, else an error message.

    The message is shown to the user in a dialog, so it follows the house rule
    for those: no "repository", no exit codes, nothing that assumes the reader
    knows what zypper is.

    Needs root, so it only runs inside ``helper/repos``.
    """
    flag = "--enable" if enabled else "--disable"
    try:
        proc = subprocess.run(
            ["zypper", "--non-interactive", "modifyrepo", flag, alias],
            capture_output=True,
            text=True,
            timeout=timeout,
        )
    except FileNotFoundError:
        return "zypper is not installed"
    except subprocess.TimeoutExpired:
        return "zypper timed out"
    if proc.returncode == ZYPPER_EXIT_ZYPP_LOCKED:
        return _LOCKED_MESSAGE
    if proc.returncode != 0:
        stderr = (proc.stderr or proc.stdout).strip().splitlines()
        return stderr[-1] if stderr else f"zypper exited {proc.returncode}"
    return None


# --------------------------------------------------------------------------- #
# Putting back a source that was switched off for one upgrade.
#
# helper/run-update switches an unreachable source off, runs the dup, and
# switches it back on in a finally block. That covers every ending the process
# gets to see, including the Ctrl-C the Cancel button sends. It does not cover
# a power cut or a SIGKILL, and the consequence of those would be a source left
# off for good with nothing in the window to say so - the "switch it back on"
# offer keys off SettingsStore.disabled_sources(), which is the GUI's own
# record and knows nothing about this. Hence a note on disk, written before the
# source is touched and removed once it is back, that helper/check picks up on
# its next run.
# --------------------------------------------------------------------------- #


def remember_to_restore(aliases: list[str], path: str | None = None) -> None:
    """Note that *aliases* are switched off only until the upgrade finishes."""
    path = path or SOURCES_TO_RESTORE
    directory = os.path.dirname(path)
    os.makedirs(directory, exist_ok=True)
    # As in statusfile.write(): pkexec does not reset the umask, so the mode
    # has to be set rather than asked for.
    try:
        os.chmod(directory, 0o755)
    except OSError:
        pass
    fd, tmp = tempfile.mkstemp(dir=directory, suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            json.dump({"aliases": list(aliases)}, fh)
            fh.write("\n")
        os.chmod(tmp, 0o644)
        os.replace(tmp, path)
    except BaseException:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


def forget_to_restore(path: str | None = None) -> None:
    """Drop the note, the sources having been put back."""
    try:
        os.unlink(path or SOURCES_TO_RESTORE)
    except OSError:
        pass


def restore_remembered(path: str | None = None) -> list[str]:
    """Switch any source left off by an interrupted upgrade back on.

    Returns the aliases it switched on, which is empty in the ordinary case of
    no note being there at all. Only ever *enables*: a bad or stale file cannot
    turn a source off, and an alias that no longer exists is skipped rather
    than handed to zypper.
    """
    path = path or SOURCES_TO_RESTORE
    try:
        with open(path, "r", encoding="utf-8") as fh:
            aliases = json.load(fh).get("aliases") or []
    except Exception:
        # Missing is the normal case. Unreadable or the wrong shape is not
        # worth reporting either: there is nothing to act on either way.
        forget_to_restore(path)
        return []

    listing = list_repos()
    if listing.error:
        # Leave the note in place for the next run rather than losing it.
        return []

    restored = []
    for alias in aliases:
        if not isinstance(alias, str):
            continue
        repo = listing.by_alias(alias)
        if repo is None or repo.enabled:
            continue
        if set_enabled(alias, enabled=True) is None:
            restored.append(alias)
    forget_to_restore(path)
    return restored
