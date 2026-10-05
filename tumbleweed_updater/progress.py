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

3. The parallel download that comes before both (src/callbacks/media.h,
   ``CommitPreloadReportReceiver``, zypper 1.14.101 with libzypp 17.38): one
   bar, redrawn in place, carrying the bytes fetched so far and the bytes
   needed::

       Preloading Packages: [ (29.2 MiB / 33.6 MiB) (29.2 MiB/s)] ....<87%>===[|]

   It is recognised by that pair of sizes, never by its translated words, and
   not by the ``<87%>``, which zypper leaves out when the line is narrow. No
   other line of a ``zypper dup`` has two sizes either side of a slash. The
   ``Retrieving:`` lines with their ``(12/345),`` counters still follow it,
   all at once, as each package is taken from what was preloaded.

All three kinds of line are redrawn in place with ``\\r`` and carry colour and
cursor codes, and a chunk from the terminal can end anywhere, even half way
through a counter.
"""

from __future__ import annotations

import math
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
    permille: int = 0  # the whole bar, in tenths of a percent


# How much of the bar the counted packages fill. The rest is for what comes
# after the last package (scripts, the closing snapshot, clean-up), which
# zypper does not count; see finishing_permille().
COUNTED_UPTO = 950
# Where the bar stops while that last part runs, however long it takes. Only
# the end of the run fills the bar.
CREEP_TO = 990
# How quickly it gets there: about 962 after 11 seconds, 984 after a minute.
_CREEP_SECONDS = 30.0


def finishing_permille(seconds: float) -> int:
    """Where the bar stands *seconds* after the last package went in.

    This is a clock, not a measurement. Nothing zypper prints counts the
    scripts, the closing snapshot or the clean-up, and a bar that sat still
    for that long looked stuck. It slows as it goes and never reaches
    CREEP_TO, so it cannot claim the update is done.
    """
    gap = CREEP_TO - COUNTED_UPTO
    return min(CREEP_TO, CREEP_TO - math.ceil(gap * math.exp(-max(seconds, 0.0) / _CREEP_SECONDS)))


# Terminal control codes: CSI sequences (colour, clear line, cursor movement),
# character-set choices such as "ESC ( B", and the two-character ones. Removed
# before a line is read, since zypper puts them in front of the counter when it
# redraws a line.
_ESCAPE = re.compile(rb"\x1b(?:\[[0-?]*[ -/]*[@-~]|[()*+].|[^\[()*+])")
_LINE_BREAK = re.compile(rb"[\r\n]")
_DOWNLOAD = re.compile(rb"\((\d+)/(\d+)\),")
_INSTALL = re.compile(rb"^\s*\(\s*(\d+)/(\d+)\) \S")
# zypp's ByteCount: "512 B", "206.0 KiB", "29.2 MiB". The decimal mark follows
# the locale, so a comma is accepted as well.
_SIZE = rb"(\d+(?:[.,]\d+)?)\s*([KMGTP]?i?B)"
_PRELOAD = re.compile(rb"\(\s*" + _SIZE + rb"\s*/\s*" + _SIZE + rb"\s*\)")
_UNITS = {b"B": 0, b"KiB": 1, b"MiB": 2, b"GiB": 3, b"TiB": 4, b"PiB": 5}

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
        self._preloaded = 0.0  # the share of the preload done, 0 to 1
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
            return
        found = _PRELOAD.findall(line)
        if found:
            self._preload(*found[-1])

    def _preload(self, got: bytes, got_unit: bytes, need: bytes, need_unit: bytes) -> None:
        if got_unit not in _UNITS or need_unit not in _UNITS:
            return
        received = float(got.replace(b",", b".")) * 1024 ** _UNITS[got_unit]
        required = float(need.replace(b",", b".")) * 1024 ** _UNITS[need_unit]
        if not 0 < required or received > required:
            return
        share = received / required
        if share <= self._preloaded:
            return
        self._preloaded = share
        # Counters, if any have come yet, stay on the text; the preload has
        # none of its own, and describe() says "downloading packages".
        before = self.snapshot
        done, total = (
            (before.done, before.total) if before.phase is Phase.DOWNLOADING else (0, 0)
        )
        self._show(Phase.DOWNLOADING, done, total, self._permille())

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
        if finished:
            self._show(Phase.FINISHING, current, total, COUNTED_UPTO)
        else:
            self._show(phase, current, total, self._permille())

    def _show(self, phase: Phase, done: int, total: int, permille: int) -> None:
        self.snapshot = Snapshot(
            phase,
            done,
            total,
            # Never backwards: a total learnt late can lower the estimate.
            max(permille, self.snapshot.permille),
        )

    def _permille(self) -> int:
        """The counted part of the bar, 0 to COUNTED_UPTO."""
        return int(self._share() * COUNTED_UPTO)

    def _share(self) -> float:
        d, big_d = self._downloaded, self._to_download
        i, big_i = self._installed, self._to_install
        pre = self._preloaded
        if big_d:
            # A package that is installed has been downloaded, even when no
            # download line was shown for it because it was already here.
            fetched = max(d, min(i, big_d), pre * big_d)
        if self._download_only:
            return fetched / big_d if big_d else pre
        if not big_i:
            # Only downloads so far, and the installs are still to come.
            return (fetched / big_d if big_d else pre) / 2
        if big_d:
            return (fetched + i) / (big_d + big_i)
        if pre:
            # Preloaded, and no download counter came after it.
            return (pre + i / big_i) / 2
        # Everything was already on this computer.
        return i / big_i


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
    elif snapshot.phase is Phase.DOWNLOADING and not snapshot.total:
        what = "downloading packages"
    elif snapshot.phase is Phase.DOWNLOADING:
        what = f"downloading {snapshot.done} of {_packages(snapshot.total)}"
    elif snapshot.phase is Phase.INSTALLING:
        what = f"installing {snapshot.done} of {_packages(snapshot.total)}"
    else:
        what = "finishing off"
    return f"{label}: {what}{where}"
