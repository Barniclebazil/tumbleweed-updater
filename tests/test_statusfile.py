import os

from tumbleweed_updater import statusfile
from tumbleweed_updater.sources import (
    Action,
    FlatpakRef,
    FlatpakResult,
    Package,
    UpdateStatus,
    ZypperResult,
)


def _sample() -> UpdateStatus:
    return UpdateStatus(
        zypper=ZypperResult(
            packages=[
                Package("bash", Action.UPGRADE, "5.2.37-1.1", "5.2.32-1.1", "x86_64"),
                Package("oldpkg", Action.REMOVE, "", "0.9-1.1", "x86_64"),
            ],
            download_size=1024,
            space_diff=-512,
            need_reboot=True,
            locked=True,
            failed_repos=[("vlc", "VLC")],
        ),
        flatpak=FlatpakResult(
            refs=[FlatpakRef("org.kde.Kdenlive", "24.12", "stable", "flathub", "user")]
        ),
        generated="2026-09-10T12:00:00+00:00",
        snapshots_ok=False,
    )


def test_roundtrip(tmp_path):
    path = os.path.join(tmp_path, "status.json")
    original = _sample()
    statusfile.write(original, path)
    loaded = statusfile.read(path)

    assert loaded is not None
    assert loaded.zypper.count == 2
    assert loaded.zypper.packages[0].name == "bash"
    assert loaded.zypper.packages[0].action is Action.UPGRADE
    assert loaded.zypper.need_reboot is True
    assert loaded.zypper.download_size == 1024
    assert loaded.zypper.space_diff == -512
    assert loaded.zypper.locked is True
    assert loaded.flatpak.refs[0].installation == "user"
    assert loaded.snapshots_ok is False
    assert loaded.total == 3
    assert loaded.has_updates


def test_from_dict_without_locked_defaults_to_false():
    """A status file written before "locked" existed must still load."""
    status = statusfile.from_dict(
        {
            "schema": 1,
            "generated": "2026-09-10T12:00:00+00:00",
            "snapshots_ok": True,
            "zypper": {"error": "something else went wrong", "packages": []},
            "flatpak": {"error": None, "refs": []},
        }
    )
    assert status.zypper.locked is False


def test_read_missing_returns_none(tmp_path):
    assert statusfile.read(os.path.join(tmp_path, "nope.json")) is None


def test_write_is_atomic_and_world_readable(tmp_path):
    path = os.path.join(tmp_path, "status.json")
    statusfile.write(_sample(), path)
    mode = os.stat(path).st_mode & 0o777
    assert mode == 0o644


def test_read_survives_a_wrongly_shaped_file(tmp_path):
    """Anything unusable must read as None, not raise.

    read() is called from a QFileSystemWatcher slot, where an escaping
    exception aborts the process. These two shapes raise AttributeError and
    TypeError, neither of which is a ValueError.
    """
    for bad in (
        '{"zypper": {"packages": {"a": 1}}}',
        '{"zypper": {"download_size": [1]}}',
        '{"zypper": "not a mapping"}',
        "[]",
        "not json at all",
    ):
        path = tmp_path / "status.json"
        path.write_text(bad, encoding="utf-8")
        assert statusfile.read(str(path)) is None, bad


def test_write_fixes_the_directory_mode_regardless_of_umask(tmp_path):
    """pkexec does not reset the umask, so the checker must not inherit it.

    0700 would leave the GUI unable to read its own status file; 0777 would
    leave a world-writable directory in /run.
    """
    old = os.umask(0o077)
    try:
        target = tmp_path / "run" / "status.json"
        statusfile.write(UpdateStatus(), str(target))
        assert oct(os.stat(target.parent).st_mode & 0o777) == "0o755"
        assert oct(os.stat(target).st_mode & 0o777) == "0o644"
    finally:
        os.umask(old)


def test_failed_repos_survive_the_round_trip(tmp_path):
    path = os.path.join(tmp_path, "status.json")
    statusfile.write(_sample(), path)
    loaded = statusfile.read(path)
    # JSON has no tuples, so the pairs travel as lists and come back as tuples.
    assert loaded.zypper.failed_repos == [("vlc", "VLC")]


def test_a_status_file_without_failed_repos_reads_as_empty():
    """Added after SCHEMA 1 shipped, like "locked": an older file simply has no
    such key, which is not an error."""
    status = statusfile.from_dict({"zypper": {"packages": []}})
    assert status.zypper.failed_repos == []


def test_a_malformed_failed_repos_entry_is_skipped():
    """read() folds every failure into None, so nothing here may raise on a
    file written by some other version with a different shape."""
    status = statusfile.from_dict(
        {"zypper": {"failed_repos": [["vlc", "VLC"], "nonsense", ["only-one"], None]}}
    )
    assert status.zypper.failed_repos == [("vlc", "VLC")]


def test_a_needed_decision_survives_the_round_trip(tmp_path):
    path = os.path.join(tmp_path, "status.json")
    status = _sample()
    status.zypper.needs_decision = True
    statusfile.write(status, path)

    assert statusfile.read(path).zypper.needs_decision


def test_a_status_file_without_needs_decision_reads_as_no():
    status = statusfile.from_dict({"zypper": {"packages": []}})
    assert status.zypper.needs_decision is False
