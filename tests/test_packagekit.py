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
