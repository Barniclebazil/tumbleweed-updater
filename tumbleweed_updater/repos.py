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

The user-facing word for a repository is "software source"; the strings the
window shows are built in :mod:`tumbleweed_updater.mainwindow`, from the
display *name* here, never the alias.
"""

from __future__ import annotations

import re
import subprocess
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field


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


def set_enabled(alias: str, enabled: bool, timeout: int = 30) -> str | None:
    """Switch a source on or off. None on success, else an error message.

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
    if proc.returncode != 0:
        stderr = (proc.stderr or proc.stdout).strip().splitlines()
        return stderr[-1] if stderr else f"zypper exited {proc.returncode}"
    return None
