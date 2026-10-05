"""What the window says when pkexec or a helper fails.

pkexec exits 127 for a refused password, for no password window, for polkit
not running and for a program that is not there, so the exit code alone used
to put "Part of Tumbleweed Updater is missing" in front of all four. The
stderr lines below are pkexec's own, copied from polkit 127.
"""

import os
import stat

import pytest
from PySide6.QtCore import QEventLoop, QTimer
from PySide6.QtWidgets import QApplication

from tumbleweed_updater import privileged
from tumbleweed_updater.privileged import PrivilegedRunner, _explain_exit

NOT_AUTHORIZED = (
    "Error executing command as another user: Not authorized\n\n"
    "This incident has been reported.\n"
)
DISMISSED = "Error executing command as another user: Request dismissed\n"
NO_AGENT = (
    "Error executing command as another user: No authentication agent found.\n"
)
NO_AUTHORITY = (
    "Error getting authority: Error initializing authority: Could not "
    "connect: No such file or directory\n"
)
NO_PROGRAM = (
    "Cannot run program /usr/libexec/tumbleweed-updater/set-interval: "
    "No such file or directory\n"
)


@pytest.fixture(scope="module")
def app():
    return QApplication.instance() or QApplication([])


@pytest.fixture
def runner(app):
    """A PrivilegedRunner owned by the application, as app.py makes its own.

    Not a free-standing one: a runner, the QProcess it owns and the handlers
    connected between them refer to each other, so a runner left to Python
    is freed by the cycle collector whenever that happens to run. Freeing it
    that way deleted its QProcess twice, which crashed the suite at random
    in CI (05/10/2026, caught under gdb: ~QProcess on freed memory). The app
    never frees its runner while running, so only the tests met this.
    """
    return PrivilegedRunner(app)


def _wait(pred, timeout=5000):
    loop = QEventLoop()
    t = QTimer()
    t.setInterval(20)
    t.timeout.connect(lambda: loop.quit() if pred() else None)
    t.start()
    g = QTimer()
    g.setSingleShot(True)
    g.timeout.connect(loop.quit)
    g.start(timeout)
    loop.exec()
    return pred()


@pytest.mark.parametrize(
    "code, stderr, expected",
    [
        (127, NOT_AUTHORIZED, privileged.NOT_AUTHORISED),
        (126, DISMISSED, privileged.NOT_AUTHORISED),
        (126, "", privileged.NOT_AUTHORISED),
        (127, NO_AGENT, privileged.NO_PASSWORD_PROMPT),
        (127, NO_AUTHORITY, privileged.PASSWORD_SERVICE_DOWN),
        (127, NO_PROGRAM, privileged.HELPER_MISSING),
        (1, "", privileged.HELPER_FAILED),
    ],
)
def test_each_pkexec_failure_gets_its_own_sentence(code, stderr, expected):
    assert _explain_exit(code, stderr) == expected


def test_an_unknown_127_is_not_called_a_missing_part():
    # Kept as it is, so the window shows it under details.
    message = _explain_exit(127, "pkexec must be setuid root\n")
    assert message == "pkexec must be setuid root"
    assert not privileged.is_plain(message)


def test_a_helper_quoting_pkexec_words_is_not_read_as_pkexec():
    # Exit 1 is the helper's own, whatever words its output happens to carry.
    assert _explain_exit(1, "Not authorized to frobnicate\n") == (
        "Not authorized to frobnicate"
    )


def test_no_pkexec_at_all_says_so(runner, monkeypatch, tmp_path):
    monkeypatch.setenv("PATH", str(tmp_path))
    results = []
    runner.intervalFinished.connect(lambda ok, msg: results.append((ok, msg)))

    assert runner.set_interval("weekly")
    assert _wait(lambda: results != [])
    assert results == [(False, privileged.PKEXEC_MISSING)]


def test_a_refused_password_through_a_real_process(runner, monkeypatch, tmp_path):
    # A stand-in pkexec that fails the way the real one does after three
    # wrong passwords, or when the password window falls over.
    fake = tmp_path / "pkexec"
    fake.write_text(
        "#!/bin/sh\n"
        "printf 'Error executing command as another user: Not authorized\\n\\n"
        "This incident has been reported.\\n' >&2\n"
        "exit 127\n"
    )
    fake.chmod(fake.stat().st_mode | stat.S_IXUSR)
    monkeypatch.setenv("PATH", f"{tmp_path}{os.pathsep}/usr/bin{os.pathsep}/bin")
    results = []
    runner.intervalFinished.connect(lambda ok, msg: results.append((ok, msg)))

    assert runner.set_interval("weekly")
    assert _wait(lambda: results != [])
    assert results == [(False, privileged.NOT_AUTHORISED)]
