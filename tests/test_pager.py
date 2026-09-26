"""The pager handed to zypper.

zypper decides whether its pager is less by taking the last four characters of
$PAGER, and a shorter value makes it abort with std::out_of_range. Measured on
zypper 1.14.101 with PAGER=cat: every package installed, then answering "y" to
"View the notifications now?" crashed it with exit 250 and the whole run was
reported as failed.
"""

import importlib.machinery
import importlib.util
from pathlib import Path

from tumbleweed_updater import pty_session

REPO_ROOT = Path(__file__).resolve().parent.parent
_loader = importlib.machinery.SourceFileLoader(
    "helper_run_update", str(REPO_ROOT / "helper" / "run-update")
)
_spec = importlib.util.spec_from_loader("helper_run_update", _loader)
helper_run_update = importlib.util.module_from_spec(_spec)
_loader.exec_module(helper_run_update)


def test_the_pagers_are_long_enough_for_zypper():
    for pager in (helper_run_update.PAGER, pty_session.PAGER):
        assert pager.startswith("/"), pager
        assert len(pager) >= 4, pager


def test_the_helper_and_the_terminal_agree():
    assert helper_run_update.PAGER == pty_session.PAGER
