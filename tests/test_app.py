from tumbleweed_updater.app import _relaunch_argv


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
