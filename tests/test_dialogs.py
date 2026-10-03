"""The question and failure boxes every dialog in the app goes through."""

import pytest
from PySide6.QtWidgets import QApplication, QMessageBox

from tumbleweed_updater import dialogs, intervals, privileged, repos


@pytest.fixture(scope="module")
def app():
    return QApplication.instance() or QApplication([])


def test_a_plain_message_is_said_and_anything_else_goes_under_details(
    app, monkeypatch
):
    shown = []
    monkeypatch.setattr(
        QMessageBox,
        "exec",
        lambda self: shown.append((self.text(), self.detailedText())),
    )

    dialogs.show_failure(None, "Title", "Lead.", privileged.NOT_AUTHORISED)
    dialogs.show_failure(None, "Title", "Lead.", "zypper exited 4")
    dialogs.show_failure(None, "Title", "Lead.")

    assert shown[0] == (f"Lead.\n\n{privileged.NOT_AUTHORISED}", "")
    assert shown[1] == ("Lead.", "zypper exited 4")
    assert shown[2] == ("Lead.", "")


@pytest.mark.parametrize("press, expected", [("Go ahead", True), ("Leave it", False)])
def test_ask_is_true_only_for_the_button_named_for_yes(
    app, monkeypatch, press, expected
):
    def click(box):
        # Press the button by its label, as the user would.
        next(b for b in box.buttons() if b.text() == press).click()

    monkeypatch.setattr(QMessageBox, "exec", click)

    assert dialogs.ask(None, "Title", "Text?", "Go ahead", "Leave it") is expected


def test_every_sentence_the_helpers_write_for_the_user_counts_as_plain():
    for message in (
        privileged.NOT_AUTHORISED,
        privileged.HELPER_MISSING,
        privileged.HELPER_FAILED,
        privileged.NO_PASSWORD_PROMPT,
        privileged.PASSWORD_SERVICE_DOWN,
        privileged.PKEXEC_MISSING,
        repos.LOCKED_MESSAGE,
        *intervals.FAILURES,
    ):
        assert privileged.is_plain(message), message
    assert not privileged.is_plain("zypper exited 4")


def test_every_schedule_has_words_for_settings_to_show():
    assert set(intervals.LABELS) == set(intervals.INTERVALS)
