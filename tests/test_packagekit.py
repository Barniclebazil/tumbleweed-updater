"""Tests for reading and waiting on the zypp lock.

Every function takes pid_file/proc as arguments precisely so these tests can
point them at tmp_path instead of the real /run and /proc.
"""

import pytest

from tumbleweed_updater import packagekit


def _proc(tmp_path, pid, cmdline):
    d = tmp_path / "proc" / str(pid)
    d.mkdir(parents=True)
    (d / "cmdline").write_bytes(cmdline)
    (d / "comm").write_text(cmdline.split(b"\0")[0].decode().rsplit("/", 1)[-1][:15])
    return str(tmp_path / "proc")


def _pidfile(tmp_path, text):
    p = tmp_path / "zypp.pid"
    p.write_text(text)
    return str(p)


def test_a_renamed_main_thread_is_still_matched(tmp_path, monkeypatch):
    """libzypp renames packagekitd's main thread to "Zypp-main", so comm (and
    therefore pgrep) does not say packagekitd. cmdline does, which is why it is
    read first."""
    d = tmp_path / "proc" / "4242"
    d.mkdir(parents=True)
    (d / "cmdline").write_bytes(b"/usr/libexec/packagekitd\0")
    (d / "comm").write_text("Zypp-main\n")

    holder = packagekit.lock_holder(_pidfile(tmp_path, "4242"), str(tmp_path / "proc"))
    assert packagekit.holder_is_packagekit(holder) is True


def test_zypp_main_alone_is_not_treated_as_packagekit(tmp_path):
    """The same thread name would show up for a running zypper, which must
    never be asked to stand aside."""
    d = tmp_path / "proc" / "4242"
    d.mkdir(parents=True)
    (d / "cmdline").write_bytes(b"")
    (d / "comm").write_text("Zypp-main\n")

    holder = packagekit.lock_holder(_pidfile(tmp_path, "4242"), str(tmp_path / "proc"))
    assert packagekit.holder_is_packagekit(holder) is False


# -- wait_for_lock --------------------------------------------------------- #


def test_wait_returns_at_once_when_the_lock_is_free(tmp_path, monkeypatch):
    monkeypatch.setattr(
        packagekit.time, "sleep", lambda _s: pytest.fail("should not have waited")
    )
    free, detail = packagekit.wait_for_lock(
        pid_file=str(tmp_path / "nope"), proc=str(tmp_path)
    )
    assert free is True
    assert "free" in detail


def test_wait_does_not_sit_behind_somebody_elses_zypper(tmp_path, monkeypatch):
    # Another zypper can legitimately run for many minutes; waiting silently
    # behind it would be worse than saying who has the lock.
    monkeypatch.setattr(
        packagekit.time, "sleep", lambda _s: pytest.fail("should not have waited")
    )
    proc = _proc(tmp_path, 900, b"/usr/bin/zypper\0dup\0")
    free, detail = packagekit.wait_for_lock(pid_file=_pidfile(tmp_path, "900"), proc=proc)
    assert free is False
    assert "zypper" in detail and "900" in detail


def test_wait_succeeds_once_packagekit_lets_go(tmp_path, monkeypatch):
    pid_file = _pidfile(tmp_path, "4242")
    proc = _proc(tmp_path, 4242, b"/usr/libexec/packagekitd\0")

    def release(_s):
        # libzypp truncates the file rather than unlinking it, and packagekitd
        # itself stays alive; an empty file still means free.
        open(pid_file, "w").close()

    monkeypatch.setattr(packagekit.time, "sleep", release)
    free, detail = packagekit.wait_for_lock(pid_file=pid_file, proc=proc)
    assert free is True
    assert "released" in detail


def test_wait_gives_up_at_the_deadline(tmp_path, monkeypatch):
    proc = _proc(tmp_path, 4242, b"/usr/libexec/packagekitd\0")
    monkeypatch.setattr(packagekit.time, "sleep", lambda _s: None)

    free, detail = packagekit.wait_for_lock(
        timeout_s=0.0, pid_file=_pidfile(tmp_path, "4242"), proc=proc
    )
    assert free is False
    assert "4242" in detail


def test_wait_stops_if_the_holder_changes_to_something_else(tmp_path, monkeypatch):
    pid_file = _pidfile(tmp_path, "4242")
    proc = _proc(tmp_path, 4242, b"/usr/libexec/packagekitd\0")
    other = tmp_path / "proc" / "900"
    other.mkdir()
    (other / "cmdline").write_bytes(b"/usr/bin/zypper\0")

    def hand_over(_s):
        open(pid_file, "w").write("900")

    monkeypatch.setattr(packagekit.time, "sleep", hand_over)
    free, detail = packagekit.wait_for_lock(pid_file=pid_file, proc=proc)
    assert free is False
    assert "zypper" in detail


def test_describe_holder_names_packagekit_specifically(tmp_path):
    proc = _proc(tmp_path, 4242, b"/usr/libexec/packagekitd\0")
    holder = packagekit.lock_holder(_pidfile(tmp_path, "4242"), proc)
    assert "PackageKit" in packagekit.describe_holder(holder)
    assert packagekit.describe_holder(None) == "the package lock is free"


def test_wait_reports_progress_while_it_waits(tmp_path, monkeypatch):
    """A refresh can run for minutes, so a caller with a terminal needs to be
    able to show that something is still happening."""
    pid_file = _pidfile(tmp_path, "4242")
    proc = _proc(tmp_path, 4242, b"/usr/libexec/packagekitd\0")
    clock = {"t": 0.0}
    monkeypatch.setattr(packagekit.time, "monotonic", lambda: clock["t"])
    monkeypatch.setattr(
        packagekit.time, "sleep", lambda s: clock.__setitem__("t", clock["t"] + 5)
    )
    seen = []

    free, _ = packagekit.wait_for_lock(
        timeout_s=40.0,
        pid_file=pid_file,
        proc=proc,
        on_progress=seen.append,
        progress_every_s=15.0,
    )
    assert free is False
    assert seen  # and roughly every 15s of the 40s budget
    assert all(s >= 15.0 for s in seen)


def test_wait_says_how_long_it_waited(tmp_path, monkeypatch):
    pid_file = _pidfile(tmp_path, "4242")
    proc = _proc(tmp_path, 4242, b"/usr/libexec/packagekitd\0")
    clock = {"t": 0.0}
    monkeypatch.setattr(packagekit.time, "monotonic", lambda: clock["t"])

    def release(_s):
        clock["t"] += 7
        open(pid_file, "w").close()

    monkeypatch.setattr(packagekit.time, "sleep", release)
    free, detail = packagekit.wait_for_lock(pid_file=pid_file, proc=proc)
    assert free is True
    assert "7s" in detail


# -- holder_is_ours -------------------------------------------------------- #
#
# The process in /run/zypp.pid is always zypper, never one of our helpers:
# both of them shell out. So "is that zypper one of ours?" can only be answered
# from the ancestry, and a helper run through a shebang carries its own path as
# a token of argv ("/usr/bin/python3", "/usr/libexec/.../check").

_CHECK = "/usr/libexec/tumbleweed-updater/check"


def _tree(tmp_path, chain):
    """Build a fake /proc from a list of (pid, ppid, argv) tuples."""
    root = tmp_path / "proc"
    for pid, ppid, argv in chain:
        d = root / str(pid)
        d.mkdir(parents=True)
        (d / "cmdline").write_bytes(b"\0".join(a.encode() for a in argv) + b"\0")
        (d / "comm").write_text(argv[0].rsplit("/", 1)[-1][:15])
        (d / "status").write_text(f"Name:\tx\nPPid:\t{ppid}\n")
    return str(root)


def test_our_own_checks_zypper_is_recognised(tmp_path):
    proc = _tree(
        tmp_path,
        [
            (900, 800, ["/usr/bin/zypper", "--non-interactive", "refresh"]),
            (800, 1, ["/usr/bin/python3", _CHECK]),
        ],
    )
    holder = packagekit.lock_holder(_pidfile(tmp_path, "900"), proc)
    assert packagekit.holder_is_ours(holder, (_CHECK,), proc) is True


def test_the_helper_is_found_further_up_the_chain(tmp_path):
    proc = _tree(
        tmp_path,
        [
            (900, 850, ["/usr/bin/zypper", "dup"]),
            (850, 800, ["/bin/sh", "-c", "zypper dup"]),
            (800, 1, ["/usr/bin/python3", _CHECK]),
        ],
    )
    holder = packagekit.lock_holder(_pidfile(tmp_path, "900"), proc)
    assert packagekit.holder_is_ours(holder, (_CHECK,), proc) is True


def test_somebody_elses_zypper_is_not_ours(tmp_path):
    proc = _tree(
        tmp_path,
        [
            (900, 800, ["/usr/bin/zypper", "dup"]),
            (800, 1, ["/bin/bash"]),
        ],
    )
    holder = packagekit.lock_holder(_pidfile(tmp_path, "900"), proc)
    assert packagekit.holder_is_ours(holder, (_CHECK,), proc) is False


def test_the_path_has_to_be_a_whole_argument(tmp_path):
    """An editor with the helper open must not count as the helper running."""
    proc = _tree(
        tmp_path,
        [
            (900, 800, ["/usr/bin/zypper", "dup"]),
            (800, 1, ["/usr/bin/vim", f"{_CHECK}.py"]),
        ],
    )
    holder = packagekit.lock_holder(_pidfile(tmp_path, "900"), proc)
    assert packagekit.holder_is_ours(holder, (_CHECK,), proc) is False


def test_an_ancestor_that_has_gone_ends_the_walk(tmp_path):
    proc = _tree(tmp_path, [(900, 800, ["/usr/bin/zypper", "dup"])])
    holder = packagekit.lock_holder(_pidfile(tmp_path, "900"), proc)
    assert packagekit.holder_is_ours(holder, (_CHECK,), proc) is False


def test_nothing_is_ours_when_no_paths_are_given(tmp_path):
    proc = _tree(
        tmp_path,
        [
            (900, 800, ["/usr/bin/zypper", "dup"]),
            (800, 1, ["/usr/bin/python3", _CHECK]),
        ],
    )
    holder = packagekit.lock_holder(_pidfile(tmp_path, "900"), proc)
    assert packagekit.holder_is_ours(holder, (), proc) is False


def test_our_own_check_is_named_without_a_pid(tmp_path):
    proc = _tree(
        tmp_path,
        [
            (900, 800, ["/usr/bin/zypper", "refresh"]),
            (800, 1, ["/usr/bin/python3", _CHECK]),
        ],
    )
    holder = packagekit.lock_holder(_pidfile(tmp_path, "900"), proc)
    detail = packagekit.describe_holder(holder, (_CHECK,), proc)
    assert "own update check" in detail
    assert "900" not in detail
    # Without being told what is ours, it is just another zypper.
    assert "900" in packagekit.describe_holder(holder)


def test_wait_sits_behind_our_own_check(tmp_path, monkeypatch):
    """It used to give up at once, because our check's zypper looks like
    anybody's. That is how an upgrade and a scheduled check wrecked each
    other's runs."""
    proc = _tree(
        tmp_path,
        [
            (900, 800, ["/usr/bin/zypper", "refresh"]),
            (800, 1, ["/usr/bin/python3", _CHECK]),
        ],
    )
    pid_file = _pidfile(tmp_path, "900")
    # Second look: the lock has been let go.
    slept = []

    def fake_sleep(seconds):
        slept.append(seconds)
        open(pid_file, "w").close()

    monkeypatch.setattr(packagekit.time, "sleep", fake_sleep)

    free, detail = packagekit.wait_for_lock(
        pid_file=pid_file, proc=proc, ours=(_CHECK,)
    )
    assert free is True
    assert slept
    assert "own update check" in detail


def test_wait_still_gives_up_at_once_on_a_stranger(tmp_path, monkeypatch):
    proc = _tree(
        tmp_path,
        [
            (900, 800, ["/usr/bin/zypper", "dup"]),
            (800, 1, ["/bin/bash"]),
        ],
    )
    monkeypatch.setattr(
        packagekit.time, "sleep", lambda _s: pytest.fail("should not have waited")
    )
    free, detail = packagekit.wait_for_lock(
        pid_file=_pidfile(tmp_path, "900"), proc=proc, ours=(_CHECK,)
    )
    assert free is False
    assert "900" in detail
