"""The two message boxes the app shows: a question and a failure.

ask() names its buttons after what they do, so nobody has to go back to the
question to work out what "Yes" would mean.

show_failure() leads with a plain sentence of the window's own. A helper's
message that is already plain (privileged.is_plain()) goes with it; anything
else is zypper's, snapper's or a helper's own wording, and sits under
"Show Details…", where it is still there for whoever needs it.

Callers use these as ``dialogs.ask(...)`` rather than importing the names, so
that tests can replace them.
"""

from __future__ import annotations

from PySide6.QtWidgets import QMessageBox

from .privileged import is_plain


def ask(
    parent,
    title: str,
    text: str,
    yes: str,
    no: str,
    *,
    default_yes: bool = False,
) -> bool:
    """Ask *text*; True if the user pressed the *yes* button.

    Escape and closing the box count as *no*.
    """
    box = QMessageBox(parent)
    box.setIcon(QMessageBox.Question)
    box.setWindowTitle(title)
    box.setText(text)
    yes_btn = box.addButton(yes, QMessageBox.AcceptRole)
    no_btn = box.addButton(no, QMessageBox.RejectRole)
    box.setDefaultButton(yes_btn if default_yes else no_btn)
    box.setEscapeButton(no_btn)
    box.exec()
    return box.clickedButton() is yes_btn


def show_failure(parent, title: str, lead: str, message: str = "") -> None:
    """Say *lead*, with *message* beside it if plain or under details if not."""
    box = QMessageBox(parent)
    box.setIcon(QMessageBox.Warning)
    box.setWindowTitle(title)
    if message and is_plain(message):
        box.setText(f"{lead}\n\n{message}")
    else:
        box.setText(lead)
        if message:
            box.setDetailedText(message)
    box.exec()
