"""How far an update has got, read from zypper's own output.

Qt-free on purpose (see the conventions in CLAUDE.md); runner.py feeds it the
bytes the update's terminal receives, and the window draws what it reports.

zypper numbers every package twice during an update, and both counters are
digits and brackets in every language, so they can be read whatever the
locale. The words around them are translated and are never read.

1. Downloads (src/callbacks/repo.h, ``fillsRhs``): the counter sits at the
   right of the line, followed by a comma::

       Retrieving: vim-9.1-1.1.x86_64 (Main Repository (OSS))   (12/345),  1.6 MiB

   When the line does not fit the terminal, zypper moves that right-hand part
   onto a line of its own, which still reads ``(12/345),``.
2. Installs and removals (src/callbacks/rpm.h, a ProgressBar with a counter):
   the counter starts the line, from the untranslated format ``"(%*u/%u) "``::

       ( 12/345) Installing: vim-9.1-1.1.x86_64 .....................[done]

   Removals share the same counter, so they count as installs here.

Both kinds of line are redrawn in place with ``\\r`` and carry colour and
cursor codes, and a chunk from the terminal can end anywhere, even half way
through a counter.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from enum import Enum


class Phase(Enum):
    WAITING = "waiting"  # before the first counter: refresh, solver, questions
    DOWNLOADING = "downloading"
    INSTALLING = "installing"
    FINISHING = "finishing"  # every package done; scripts and clean-up remain


@dataclass(frozen=True)
class Snapshot:
    phase: Phase
    done: int = 0  # the counter of the current phase
    total: int = 0
    permille: int = 0  # the whole update, in tenths of a percent


# Terminal control codes: CSI sequences (colour, clear line, cursor movement),
# character-set choices such as "ESC ( B", and the two-character ones. Removed
# before a line is read, since zypper puts them in front of the counter when it
# redraws a line.
_ESCAPE = re.compile(rb"\x1b(?:\[[0-?]*[ -/]*[@-~]|[()*+].|[^\[()*+])")
_LINE_BREAK = re.compile(rb"[\r\n]")
_DOWNLOAD = re.compile(rb"\((\d+)/(\d+)\),")
_INSTALL = re.compile(rb"^\s*\(\s*(\d+)/(\d+)\) \S")

# The most of an unfinished line kept between chunks. A counter is read the
# moment it arrives, so a line that never ends costs no more than this.
_TAIL_LIMIT = 4096


class ZypperProgress:
    """Follows zypper's package counters through one update.

    *download_only* is for "--download only", where nothing is installed and
    the update is complete once the last package has been downloaded.
    """

    def __init__(self, download_only: bool = False) -> None:
        self._download_only = download_only
        self._tail = b""
        self._downloaded = 0
        self._to_download = 0
        self._installed = 0
        self._to_install = 0
        self.snapshot = Snapshot(Phase.WAITING)

    def feed(self, data: bytes) -> bool:
        """Read another chunk of output. True if the snapshot changed."""
        before = self.snapshot
        pieces = _LINE_BREAK.split(self._tail + data)
        # The last piece may be a line still being written. It is read now and
        # kept to be read again with what follows it, which is safe: both
        # patterns end at ")", so half a counter cannot match, and a counter
        # read twice does not move anything.
        self._tail = pieces[-1][-_TAIL_LIMIT:]
        for piece in pieces:
            self._read_line(_ESCAPE.sub(b"", piece))
        return self.snapshot != before

    def _read_line(self, line: bytes) -> None:
        if self.snapshot.phase is Phase.FINISHING:
            return
        # Installs first: the counter must start the line, which keeps out a
        # counter that turns up inside a package's own script output.
        match = _INSTALL.match(line)
        if match:
            self._count(False, int(match[1]), int(match[2]))
            return
        found = _DOWNLOAD.findall(line)
        if found:
            current, total = found[-1]
            self._count(True, int(current), int(total))

    def _count(self, download: bool, current: int, total: int) -> None:
        if not 0 < current <= total:
            return
        # The first counter of each kind fixes its total, and a counter that
        # disagrees with it is not one of the update's.
        if download:
            if self._to_download and total != self._to_download:
                return
            if current <= self._downloaded:
                return
            self._to_download, self._downloaded = total, current
            phase = Phase.DOWNLOADING
        else:
            if self._to_install and total != self._to_install:
                return
            if current <= self._installed:
                return
            self._to_install, self._installed = total, current
            phase = Phase.INSTALLING

        if self._download_only:
            finished = bool(self._to_download) and (
                self._downloaded >= self._to_download
            )
        else:
            finished = bool(self._to_install) and (
                self._installed >= self._to_install
            )
        permille = 1000 if finished else self._permille()
        self.snapshot = Snapshot(
            Phase.FINISHING if finished else phase,
            current,
            total,
            # Never backwards: a total learnt late can lower the estimate.
            max(permille, self.snapshot.permille),
        )

    def _permille(self) -> int:
        d, big_d = self._downloaded, self._to_download
        i, big_i = self._installed, self._to_install
        if self._download_only:
            return d * 1000 // big_d if big_d else 0
        if not big_i:
            # Only downloads so far, and the installs are still to come.
            return d * 1000 // (2 * big_d)
        if not big_d:
            # Everything was already on this computer.
            return i * 1000 // big_i
        # A package that is installed has been downloaded, even when no
        # download line was shown for it because it was already here.
        return (max(d, min(i, big_d)) + i) * 1000 // (big_d + big_i)


def _packages(n: int) -> str:
    return f"{n} package" if n == 1 else f"{n} packages"


def describe(label: str, snapshot: Snapshot | None, step: int = 1, steps: int = 1) -> str:
    """The line of text above the progress bar.

    *snapshot* is None for a step whose output is not read (the Flatpak ones),
    which is named and nothing more.
    """
    where = f" (step {step} of {steps})" if steps > 1 else ""
    if snapshot is None:
        return f"{label}{where}"
    if snapshot.phase is Phase.WAITING:
        what = "getting ready"
    elif snapshot.phase is Phase.DOWNLOADING:
        what = f"downloading {snapshot.done} of {_packages(snapshot.total)}"
    elif snapshot.phase is Phase.INSTALLING:
        what = f"installing {snapshot.done} of {_packages(snapshot.total)}"
    else:
        what = "finishing off"
    return f"{label}: {what}{where}"
