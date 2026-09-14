"""A closed snapshots dialog must let go of the shared privileged runner.

The runner outlives the dialog. When a closed dialog stayed connected to it,
every later result was delivered to the stale instance too: harmless for a
listing, but "Show changes" reached _show_status with a _status_pair of None
and raised TypeError out of a Qt slot, which aborts the process.
"""

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest

from PySide6.QtCore import QCoreApplication, QEvent, QObject, Signal
from PySide6.QtWidgets import QApplication, QMainWindow

from tumbleweed_updater.snapshotsdialog import SnapshotsDialog

_LIST_RESULT = (
    '{"error": null, "snapshots": [{"number": 1, "type": "single", '
    '"date": "2026-09-14", "description": "x", "cleanup": "", '
    '"pre_number": null}]}'
)


class _StubRunner(QObject):
    snapshotsFinished = Signal(bool, str, str)

    def __init__(self) -> None:
        super().__init__()
        self.calls: list[list[str]] = []

    def run_snapshots(self, args: list[str]) -> bool:
        self.calls.append(args)
        return True


@pytest.fixture(scope="module")
def app():
    return QApplication.instance() or QApplication([])


def _open_and_close(runner, parent) -> None:
    dialog = SnapshotsDialog(runner, parent)
    dialog.close()
    QApplication.processEvents()
    # WA_DeleteOnClose deletes through the deferred-delete queue, which
    # processEvents() on its own does not flush outside a running event loop.
    QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)


def test_closed_dialogs_stop_receiving_results(app):
    runner = _StubRunner()
    window = QMainWindow()

    _open_and_close(runner, window)
    _open_and_close(runner, window)

    assert window.findChildren(SnapshotsDialog) == []

    runner.calls.clear()
    runner.snapshotsFinished.emit(True, "", _LIST_RESULT)
    assert runner.calls == []


def test_a_stale_dialog_cannot_be_driven_into_show_status(app):
    """The exact crash: one dialog closed mid-flight, another asking for a diff."""
    runner = _StubRunner()
    window = QMainWindow()

    stale = SnapshotsDialog(runner, window)
    stale._pending_action = "status"
    stale._status_pair = None
    stale.close()
    QApplication.processEvents()
    QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)

    runner.snapshotsFinished.emit(True, "", '{"error": null, "changes": []}')


def test_the_live_dialog_still_gets_its_result(app):
    runner = _StubRunner()
    window = QMainWindow()

    dialog = SnapshotsDialog(runner, window)
    runner.snapshotsFinished.emit(True, "", _LIST_RESULT)

    assert dialog._tree.topLevelItemCount() == 1
    assert "1 snapshot" in dialog._hint.text()
    dialog.close()
