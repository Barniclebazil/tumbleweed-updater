from tumbleweed_updater import paths


def test_installed_version_reads_current_package_file():
    # Reads the real, currently-checked-out __init__.py, so just check it
    # parses to a plausible version string rather than pinning an exact value.
    version = paths.installed_version()
    assert version is not None
    assert version.count(".") >= 1


def test_installed_version_missing_file(tmp_path, monkeypatch):
    monkeypatch.setattr(paths, "__file__", str(tmp_path / "paths.py"))
    assert paths.installed_version() is None


def test_destructive_snapshot_actions_use_their_own_helper():
    """Rollback and delete sit behind a separate polkit action, so that the
    cached authorisation the read-only listing keeps alive cannot reach them."""
    from tumbleweed_updater.privileged import _snapshots_helper

    assert _snapshots_helper(["list"]) == paths.HELPER_SNAPSHOTS
    assert _snapshots_helper(["status", "1", "2"]) == paths.HELPER_SNAPSHOTS
    assert _snapshots_helper(["rollback", "7"]) == paths.HELPER_SNAPSHOTS_MANAGE
    assert _snapshots_helper(["delete", "7"]) == paths.HELPER_SNAPSHOTS_MANAGE
    assert paths.HELPER_SNAPSHOTS != paths.HELPER_SNAPSHOTS_MANAGE
