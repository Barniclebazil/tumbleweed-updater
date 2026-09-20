"""XDG autostart entries: our own, and the Hidden=true override for Plasma's."""

import os

import pytest

from tumbleweed_updater import autostart


@pytest.fixture(autouse=True)
def isolated_config_home(tmp_path, monkeypatch):
    # autostart_dir() reads the environment at call time precisely so this
    # works; pinning ~/.config at import would rewrite the real user's entry.
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))


@pytest.fixture
def fake_system_entry(tmp_path, monkeypatch):
    """A stand-in for /etc/xdg/autostart/org.kde.discover.notifier.desktop."""
    system = tmp_path / "xdg-autostart"
    system.mkdir()
    (system / autostart.PLASMA_NOTIFIER_ENTRY).write_text(
        "[Desktop Entry]\n"
        "Name=Discover\n"
        "Name[de]=Entdecken\n"
        "Exec=/usr/libexec/DiscoverNotifier --check-delay 20\n"
        "Icon=system-software-update\n"
        "Type=Application\n"
        "NoDisplay=true\n"
        "OnlyShowIn=KDE\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(autostart, "SYSTEM_AUTOSTART_DIRS", (str(system),))
    return system


# -- our own entry --------------------------------------------------------- #


def test_desktop_exec_is_quoted_when_it_has_to_be():
    assert autostart.desktop_exec("/usr/bin/tumbleweed-updater") == "/usr/bin/tumbleweed-updater"
    assert autostart.desktop_exec("/home/a b/tw") == '"/home/a b/tw"'
    assert autostart.desktop_exec("/opt/$x/tw") == '"/opt/\\$x/tw"'


def test_own_entry_follows_xdg_config_home(tmp_path, monkeypatch):
    monkeypatch.setattr(autostart.shutil, "which", lambda _n: "/usr/bin/tw")
    target = tmp_path / "autostart" / "tumbleweed-updater.desktop"

    autostart.set_own_autostart(True)
    assert "Exec=/usr/bin/tw --tray" in target.read_text(encoding="utf-8")
    assert autostart.own_autostart_enabled() is True

    autostart.set_own_autostart(False)
    assert not target.exists()
    assert autostart.own_autostart_enabled() is False


# -- read_keys ------------------------------------------------------------- #


def test_read_keys_ignores_translations_and_later_groups(tmp_path):
    path = tmp_path / "x.desktop"
    path.write_text(
        "[Desktop Entry]\nName=Discover\nName[de]=Entdecken\nExec=/bin/x\n"
        "\n[Desktop Action Other]\nName=Wrong\n",
        encoding="utf-8",
    )
    keys = autostart.read_keys(str(path), ("Name", "Exec"))
    assert keys == {"Name": "Discover", "Exec": "/bin/x"}


def test_read_keys_on_a_missing_file_is_empty(tmp_path):
    assert autostart.read_keys(str(tmp_path / "nope"), ("Name",)) == {}


# -- the Hidden=true override ---------------------------------------------- #


def test_is_installed_follows_the_system_directory(fake_system_entry):
    assert autostart.is_installed() is True


def test_is_installed_is_false_without_a_system_entry(tmp_path, monkeypatch):
    monkeypatch.setattr(autostart, "SYSTEM_AUTOSTART_DIRS", (str(tmp_path / "empty"),))
    assert autostart.is_installed() is False


def test_set_hidden_writes_a_valid_override(tmp_path, fake_system_entry):
    autostart.set_hidden(autostart.PLASMA_NOTIFIER_ENTRY, True)
    body = (tmp_path / "autostart" / autostart.PLASMA_NOTIFIER_ENTRY).read_text()

    assert "Hidden=true" in body
    # It still has to be a valid entry, and it copies the original's values
    # rather than inventing them.
    assert "Type=Application" in body
    assert "Name=Discover" in body
    assert "Exec=/usr/libexec/DiscoverNotifier --check-delay 20" in body
    assert autostart.is_hidden() is True


def test_set_hidden_false_removes_the_override(tmp_path, fake_system_entry):
    autostart.set_hidden(autostart.PLASMA_NOTIFIER_ENTRY, True)
    autostart.set_hidden(autostart.PLASMA_NOTIFIER_ENTRY, False)
    assert not (tmp_path / "autostart" / autostart.PLASMA_NOTIFIER_ENTRY).exists()
    assert autostart.is_hidden() is False


def test_set_hidden_false_is_a_no_op_when_nothing_is_there(fake_system_entry):
    autostart.set_hidden(autostart.PLASMA_NOTIFIER_ENTRY, False)  # must not raise


def test_is_hidden_is_false_for_an_override_without_the_key(tmp_path, fake_system_entry):
    d = tmp_path / "autostart"
    d.mkdir()
    (d / autostart.PLASMA_NOTIFIER_ENTRY).write_text(
        "[Desktop Entry]\nType=Application\nName=Discover\nExec=/bin/x\n"
    )
    assert autostart.is_hidden() is False


# -- finding and stopping the running notifier ----------------------------- #


def _fake_proc(tmp_path, entries):
    proc = tmp_path / "proc"
    proc.mkdir()
    for pid, cmdline in entries.items():
        d = proc / str(pid)
        d.mkdir()
        (d / "cmdline").write_bytes(cmdline)
    return str(proc)


def test_notifier_pids_matches_argv0_not_the_whole_command_line(tmp_path):
    proc = _fake_proc(
        tmp_path,
        {
            111: b"/usr/libexec/DiscoverNotifier\0--check-delay\00020\0",
            # This is why `pgrep -f DiscoverNotifier` cannot be used.
            222: b"/usr/bin/vim\0DiscoverNotifier.cpp\0",
            333: b"",
        },
    )
    assert autostart.notifier_pids(proc) == [111]


def test_notifier_pids_skips_other_users(tmp_path, monkeypatch):
    proc = _fake_proc(tmp_path, {111: b"/usr/libexec/DiscoverNotifier\0"})
    # Nothing here should ever signal a process we do not own - that is what
    # keeps this unprivileged.
    monkeypatch.setattr(autostart.os, "getuid", lambda: os.stat(proc).st_uid + 1)
    assert autostart.notifier_pids(proc) == []


def test_notifier_pids_on_a_missing_proc_is_empty(tmp_path):
    assert autostart.notifier_pids(str(tmp_path / "nope")) == []


def test_stop_notifier_sends_sigterm_only(tmp_path, monkeypatch):
    proc = _fake_proc(tmp_path, {111: b"/usr/libexec/DiscoverNotifier\0"})
    sent = []
    monkeypatch.setattr(autostart.os, "kill", lambda pid, sig: sent.append((pid, sig)))
    monkeypatch.setattr(autostart.time, "sleep", lambda _s: None)

    assert autostart.stop_notifier(proc, timeout_s=0.0) == 1
    assert sent == [(111, autostart.signal.SIGTERM)]


def test_stop_notifier_tolerates_a_process_that_already_went_away(tmp_path, monkeypatch):
    proc = _fake_proc(tmp_path, {111: b"/usr/libexec/DiscoverNotifier\0"})

    def boom(pid, sig):
        raise ProcessLookupError

    monkeypatch.setattr(autostart.os, "kill", boom)
    monkeypatch.setattr(autostart.time, "sleep", lambda _s: None)
    assert autostart.stop_notifier(proc, timeout_s=0.0) == 0


def test_suppress_writes_the_override_and_stops_the_process(fake_system_entry, monkeypatch):
    monkeypatch.setattr(autostart, "stop_notifier", lambda *a, **k: 1)
    ok, detail = autostart.suppress_plasma_notifier(True)
    assert ok is True
    assert autostart.is_hidden() is True
    assert "off" in detail


def test_suppress_false_restores_and_says_when(fake_system_entry, monkeypatch):
    monkeypatch.setattr(autostart, "stop_notifier", lambda *a, **k: 0)
    autostart.suppress_plasma_notifier(True)
    ok, detail = autostart.suppress_plasma_notifier(False)
    assert ok is True
    assert autostart.is_hidden() is False
    assert "login" in detail
