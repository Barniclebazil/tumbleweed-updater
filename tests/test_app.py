import os

from datetime import date, timedelta

from tumbleweed_updater.app import (
    _relaunch_argv,
    _should_ask_about_notifier,
    _should_notify,
    _socket_path,
)
from tumbleweed_updater.settings import Prefs


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


def test_notifier_question_is_asked_once_when_there_is_something_to_ask_about():
    assert _should_ask_about_notifier(
        Prefs(), system_entry=True, already_off=False
    ) is True


def test_notifier_question_is_not_repeated():
    assert _should_ask_about_notifier(
        Prefs(plasma_notifier_asked=True), system_entry=True, already_off=False
    ) is False


def test_notifier_question_is_skipped_without_a_system_entry():
    # Not Plasma, or discover6-notifier simply is not installed.
    assert _should_ask_about_notifier(
        Prefs(), system_entry=False, already_off=False
    ) is False


def test_notifier_question_is_skipped_when_it_is_already_off():
    assert _should_ask_about_notifier(
        Prefs(), system_entry=True, already_off=True
    ) is False


# --------------------------------------------------------------------------- #
# The desktop notification.
# --------------------------------------------------------------------------- #


def _notify(**kwargs):
    args = dict(
        notify=True, notify_on_updates=True, total=42, last_total=0, deferred=None
    )
    args.update(kwargs)
    return _should_notify(**args)


def test_a_new_count_is_worth_a_notification():
    assert _notify() is True


def test_the_first_status_of_the_session_is_not():
    """last_total < 0 means nothing has been seen yet, and firing on that would
    notify about the same updates on every launch."""
    assert _notify(last_total=-1) is False


def test_an_unchanged_count_is_not():
    assert _notify(total=42, last_total=42) is False


def test_nothing_to_report_is_not():
    assert _notify(total=0) is False


def test_the_preference_is_honoured():
    assert _notify(notify_on_updates=False) is False


def test_a_deferred_check_stays_quiet():
    """The user put this off: the tray has gone back to idle, and a popup
    saying there are 42 updates cannot be right at the same time."""
    assert _notify(deferred=date.today() + timedelta(days=1)) is False
