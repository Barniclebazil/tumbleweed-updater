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
    assert loaded.flatpak.refs[0].installation == "user"
    assert loaded.snapshots_ok is False
    assert loaded.total == 3
    assert loaded.has_updates


def test_read_missing_returns_none(tmp_path):
    assert statusfile.read(os.path.join(tmp_path, "nope.json")) is None


def test_write_is_atomic_and_world_readable(tmp_path):
    path = os.path.join(tmp_path, "status.json")
    statusfile.write(_sample(), path)
    mode = os.stat(path).st_mode & 0o777
    assert mode == 0o644
