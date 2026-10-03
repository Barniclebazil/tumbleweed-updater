"""Reading zypper's package counters for the progress bar.

The lines below are built from zypper's source (src/callbacks/repo.h for the
download line, src/callbacks/rpm.h for the install line, the "(%*u/%u) "
counter format) for zypper 1.14.101. They are not a capture of a real run: if
the first real update disagrees with them, replace them with what it printed.
"""

from tumbleweed_updater.progress import Phase, Snapshot, ZypperProgress, describe

ESC = "\x1b"
# What zypper sends when it redraws a line: back to the start, clear it.
REDRAW = f"\r{ESC}[K"


def _download(n, total, name="vim-9.1-1.1.x86_64"):
    return (
        f"Retrieving: {name} (Main Repository (OSS))"
        f"{' ' * 20}({n}/{total}),   1.6 MiB    \n"
    )


def _install(n, total, name="vim-9.1-1.1.x86_64", word="Installing"):
    width = len(str(total))
    return (
        f"({n:>{width}}/{total}) {word}: {name} ....[\\]"
        f"{REDRAW}({n:>{width}}/{total}) {word}: {name} ....{ESC}[32m[done]{ESC}[0m\n"
    )


def _feed(text, progress=None, chunk=None):
    p = progress or ZypperProgress()
    data = text.encode("utf-8")
    seen = []
    if chunk is None:
        p.feed(data)
        seen.append(p.snapshot)
    else:
        for start in range(0, len(data), chunk):
            p.feed(data[start : start + chunk])
            seen.append(p.snapshot)
    return p, seen


def _never_backwards(seen):
    values = [s.permille for s in seen]
    assert values == sorted(values), values


def test_everything_before_the_first_counter_is_waiting():
    p, _ = _feed(
        "Retrieving repository 'Main Repository (OSS)' metadata ....[done]\n"
        "Loading repository data...\nReading installed packages...\n"
        "Computing distribution upgrade...\n"
        "The following 3 packages are going to be upgraded:\n  vim curl zypper\n"
        "3 packages to upgrade.\nOverall download size: 4.8 MiB.\n"
        "Continue? [y/n/v/...? shows all options] (y): "
    )
    assert p.snapshot == Snapshot(Phase.WAITING)


def test_padded_install_lines_are_read_and_removals_count_as_installs():
    p, _ = _feed(_install(1, 12) + _install(2, 12, "old-1.0", word="Removing"))
    assert p.snapshot.phase is Phase.INSTALLING
    assert (p.snapshot.done, p.snapshot.total) == (2, 12)


def test_a_redrawn_line_is_a_change_only_the_first_time():
    p = ZypperProgress()
    line = f"( 1/12) Installing: vim ....[|]{REDRAW}"
    assert p.feed(line.encode()) is True
    assert p.feed(f"( 1/12) Installing: vim ....[/]{REDRAW}".encode()) is False
    assert p.feed(f"{ESC}[32m( 1/12) Installing: vim [done]{ESC}[0m\n".encode()) is False


def test_a_download_counter_on_its_own_line_is_still_a_download():
    """zypper moves the right-hand part of the line down when it does not fit."""
    p, _ = _feed(_download(1, 5))
    assert p.snapshot.phase is Phase.DOWNLOADING

    p, _ = _feed("Retrieving: a-very-long-package-name-1.0-1.1.x86_64 (OSS)\n (2/5),   1.6 MiB    \n")
    assert p.snapshot.phase is Phase.DOWNLOADING
    assert p.snapshot.done == 2


def test_counters_that_are_not_the_updates_are_ignored():
    p, _ = _feed(_install(1, 10))
    # Inside a script's output, not at the start of the line.
    p.feed(b"post-install: rebuilt (5/10) caches\n")
    # A different total, zero, and one past the end.
    p.feed(b"( 7/99) Installing: x\n( 0/10) Installing: x\n(11/10) Installing: x\n")
    assert (p.snapshot.done, p.snapshot.total) == (1, 10)


def test_feeding_a_byte_at_a_time_gives_the_same_answer():
    transcript = (
        "Continue? [y/n/v/...? shows all options] (y): y\n"
        + _download(1, 3)
        + _download(2, 3, "bäckerei-1.0-1.1.noarch")
        + f"{ESC}(B{ESC}[m"
        + _install(1, 3, word="Wird installiert")
        + _download(3, 3)
        + _install(2, 3, "bäckerei-1.0-1.1.noarch", word="Wird installiert")
    )
    whole, _ = _feed(transcript)
    bytewise, seen = _feed(transcript, chunk=1)
    assert bytewise.snapshot == whole.snapshot
    assert whole.snapshot.phase is Phase.INSTALLING
    assert (whole.snapshot.done, whole.snapshot.total) == (2, 3)
    _never_backwards(seen)


def _runs():
    """The orders a real update can produce, as (name, transcript)."""
    n = 6
    downloads_first = "".join(_download(k, n) for k in range(1, n + 1)) + "".join(
        _install(k, n) for k in range(1, n + 1)
    )
    heaps = (
        _download(1, n) + _download(2, n) + _install(1, n) + _install(2, n)
        + _download(3, n) + _download(4, n) + _install(3, n) + _install(4, n)
        + _download(5, n) + _download(6, n) + _install(5, n) + _install(6, n)
    )
    one_by_one = "".join(_download(k, n) + _install(k, n) for k in range(1, n + 1))
    all_cached = "".join(_install(k, n) for k in range(1, n + 1))
    # Packages 1 and 2 were already here, so the download counter covers 4.
    some_cached = (
        _install(1, n) + _install(2, n)
        + "".join(_download(k, 4) + _install(k + 2, n) for k in range(1, 5))
    )
    first_batch_cached = (
        _install(1, n) + _install(2, n) + _install(3, n)
        + _download(1, 3) + _download(2, 3) + _download(3, 3)
        + _install(4, n) + _install(5, n) + _install(6, n)
    )
    return [
        ("downloads first", downloads_first),
        ("in heaps", heaps),
        ("one at a time", one_by_one),
        ("all cached", all_cached),
        ("some cached", some_cached),
        ("first batch cached", first_batch_cached),
    ]


def test_every_order_moves_forward_and_ends_full():
    for name, transcript in _runs():
        p, seen = _feed(transcript, chunk=7)
        _never_backwards(seen)
        assert p.snapshot.permille == 1000, name
        assert p.snapshot.phase is Phase.FINISHING, name


def test_a_download_only_update_ends_full():
    p, seen = _feed(
        "".join(_download(k, 4) for k in range(1, 5)),
        ZypperProgress(download_only=True),
    )
    _never_backwards(seen)
    assert p.snapshot.permille == 1000
    assert p.snapshot.phase is Phase.FINISHING


def test_finishing_stays_finishing():
    p, _ = _feed(_install(1, 1))
    assert p.snapshot.phase is Phase.FINISHING
    p.feed(_download(1, 1).encode() + b"( 1/2) Installing: late\n")
    assert p.snapshot.phase is Phase.FINISHING
    assert p.snapshot.permille == 1000


def test_a_line_that_never_ends_keeps_only_a_small_tail():
    p = ZypperProgress()
    p.feed(b"x" * 100 * 1024)
    assert len(p._tail) == 4096


def test_the_text_above_the_bar():
    label = "Updating the system"
    assert describe(label, Snapshot(Phase.WAITING)) == "Updating the system: getting ready"
    assert (
        describe(label, Snapshot(Phase.DOWNLOADING, 12, 345))
        == "Updating the system: downloading 12 of 345 packages"
    )
    assert (
        describe(label, Snapshot(Phase.INSTALLING, 1, 1))
        == "Updating the system: installing 1 of 1 package"
    )
    assert (
        describe(label, Snapshot(Phase.FINISHING, 3, 3))
        == "Updating the system: finishing off"
    )
    assert (
        describe(label, Snapshot(Phase.INSTALLING, 40, 360), step=1, steps=3)
        == "Updating the system: installing 40 of 360 packages (step 1 of 3)"
    )
    assert (
        describe("Updating your Flatpak apps", None, step=3, steps=3)
        == "Updating your Flatpak apps (step 3 of 3)"
    )
