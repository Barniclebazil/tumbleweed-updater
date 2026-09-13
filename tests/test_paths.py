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
