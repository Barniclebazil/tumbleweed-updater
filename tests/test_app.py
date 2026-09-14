import os

from tumbleweed_updater.app import _relaunch_argv, _socket_path


def test_relaunch_argv_checkout_module_run(monkeypatch):
    # `python3 -m tumbleweed_updater` sets sys.argv[0] to __main__.py's path;
    # re-executing that path directly would lose the package context its
    # relative import needs, so -m must be re-added.
    monkeypatch.setattr(
        "sys.argv", ["/repo/tumbleweed_updater/__main__.py", "--tray"]
    )
    monkeypatch.setattr("sys.executable", "/usr/bin/python3")
    assert _relaunch_argv() == [
        "/usr/bin/python3",
        "-m",
        "tumbleweed_updater",
        "--tray",
    ]


def test_relaunch_argv_installed_launcher(monkeypatch):
    # The installed launcher script uses an absolute import, so it can be
    # re-run by path as-is.
    monkeypatch.setattr("sys.argv", ["/usr/bin/tumbleweed-updater", "--tray"])
    monkeypatch.setattr("sys.executable", "/usr/bin/python3")
    assert _relaunch_argv() == ["/usr/bin/python3", "/usr/bin/tumbleweed-updater", "--tray"]


def test_socket_lives_in_the_per_user_runtime_dir(monkeypatch, tmp_path):
    """Never /tmp: a predictable path there is connectable by any local user,
    who could then trigger an update prompt on this desktop, and squattable so
    that the real app mistakes it for a running instance and exits."""
    monkeypatch.setenv("XDG_RUNTIME_DIR", str(tmp_path))
    path = _socket_path()
    assert path == str(tmp_path / "tumbleweed-updater.instance")
    assert os.path.isabs(path)
