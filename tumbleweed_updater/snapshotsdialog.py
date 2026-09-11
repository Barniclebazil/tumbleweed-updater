"""Snapshot manager dialog: list Btrfs snapshots and show changes, roll back,
or delete one, via ``helper/snapshots``.
"""

from __future__ import annotations

import json

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QAbstractItemView,
    QDialog,
    QDialogButtonBox,
    QHBoxLayout,
    QLabel,
    QMessageBox,
    QPlainTextEdit,
    QPushButton,
    QTreeWidget,
    QTreeWidgetItem,
    QVBoxLayout,
)

_TYPE_LABELS = {"single": "Single", "pre": "Pre", "post": "Post"}


class SnapshotsDialog(QDialog):
    def __init__(self, privileged, parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Tumbleweed Updater — Snapshots")
        self.resize(640, 460)
        self._privileged = privileged
        self._busy = False
        self._pending_action: str | None = None
        self._status_pair: tuple[int, int] | None = None
        self._snapshots: list[dict] = []

        layout = QVBoxLayout(self)

        self._hint = QLabel("Loading snapshots…")
        self._hint.setStyleSheet("color: palette(mid);")
        layout.addWidget(self._hint)

        self._tree = QTreeWidget()
        self._tree.setHeaderLabels(["#", "Type", "Date", "Description"])
        self._tree.setSelectionMode(QAbstractItemView.SingleSelection)
        self._tree.setRootIsDecorated(False)
        self._tree.setAlternatingRowColors(True)
        self._tree.itemSelectionChanged.connect(self._update_buttons)
        layout.addWidget(self._tree, 1)

        buttons = QHBoxLayout()
        self._btn_refresh = QPushButton("Refresh")
        self._btn_refresh.clicked.connect(self._load)
        self._btn_status = QPushButton("Show changes…")
        self._btn_status.clicked.connect(self._on_status)
        self._btn_rollback = QPushButton("Set as default on next boot…")
        self._btn_rollback.clicked.connect(self._on_rollback)
        self._btn_delete = QPushButton("Delete…")
        self._btn_delete.clicked.connect(self._on_delete)
        buttons.addWidget(self._btn_refresh)
        buttons.addStretch(1)
        buttons.addWidget(self._btn_status)
        buttons.addWidget(self._btn_rollback)
        buttons.addWidget(self._btn_delete)
        layout.addLayout(buttons)

        box = QDialogButtonBox(QDialogButtonBox.Close)
        box.rejected.connect(self.reject)
        box.accepted.connect(self.accept)
        layout.addWidget(box)

        self._privileged.snapshotsFinished.connect(self._on_finished)
        self._update_buttons()
        self._load()

    # -- running the helper -------------------------------------------------- #

    def _load(self) -> None:
        self._run(["list"])

    def _run(self, args: list[str]) -> None:
        if self._busy:
            return
        self._busy = True
        self._pending_action = args[0]
        self._hint.setText("Working…")
        self._set_controls_enabled(False)
        self._privileged.run_snapshots(args)

    def _set_controls_enabled(self, enabled: bool) -> None:
        self._btn_refresh.setEnabled(enabled)
        if enabled:
            self._update_buttons()
        else:
            for btn in (self._btn_status, self._btn_rollback, self._btn_delete):
                btn.setEnabled(False)

    def _on_finished(self, ok: bool, message: str, stdout: str) -> None:
        self._busy = False
        self._set_controls_enabled(True)
        action, self._pending_action = self._pending_action, None

        if action == "list":
            self._apply_list(ok, message, stdout)
        elif action == "status":
            self._show_status(ok, message, stdout)
        elif action in ("rollback", "delete"):
            self._after_mutation(action, ok, message)

    # -- list ------------------------------------------------------------ #

    def _apply_list(self, ok: bool, message: str, stdout: str) -> None:
        if not ok:
            self._hint.setText(f"Could not list snapshots: {message}")
            return
        try:
            data = json.loads(stdout) if stdout else {}
        except json.JSONDecodeError:
            data = {}
        error = data.get("error")
        if error:
            self._hint.setText(f"Could not list snapshots: {error}")
            return

        self._snapshots = data.get("snapshots", [])
        self._tree.clear()
        for s in sorted(self._snapshots, key=lambda s: s["number"], reverse=True):
            item = QTreeWidgetItem(
                [
                    str(s["number"]),
                    _TYPE_LABELS.get(s["type"], s["type"]),
                    s["date"] or "",
                    s["description"] or "",
                ]
            )
            item.setData(0, Qt.UserRole, s)
            self._tree.addTopLevelItem(item)
        for i in range(4):
            self._tree.resizeColumnToContents(i)

        count = len(self._snapshots)
        self._hint.setText(f"{count} snapshot(s)." if count else "No snapshots found.")

    def _selected(self) -> dict | None:
        items = self._tree.selectedItems()
        if not items:
            return None
        return items[0].data(0, Qt.UserRole)

    def _find_pre_post_partner(self, s: dict | None) -> tuple[int, int] | None:
        """Given a selected snapshot, return (pre, post) if it is one half of
        a pre/post pair - the only case "Show changes" makes sense for."""
        if s is None:
            return None
        if s["type"] == "post" and s.get("pre_number") is not None:
            return s["pre_number"], s["number"]
        if s["type"] == "pre":
            for other in self._snapshots:
                if other["type"] == "post" and other.get("pre_number") == s["number"]:
                    return s["number"], other["number"]
        return None

    def _update_buttons(self) -> None:
        s = self._selected()
        self._btn_rollback.setEnabled(s is not None)
        self._btn_delete.setEnabled(s is not None)
        self._btn_status.setEnabled(self._find_pre_post_partner(s) is not None)

    # -- show changes ------------------------------------------------------ #

    def _on_status(self) -> None:
        pair = self._find_pre_post_partner(self._selected())
        if pair is None:
            return
        self._status_pair = pair
        self._run(["status", str(pair[0]), str(pair[1])])

    def _show_status(self, ok: bool, message: str, stdout: str) -> None:
        if not ok:
            QMessageBox.warning(self, "Could not compare snapshots", message)
            return
        try:
            data = json.loads(stdout) if stdout else {}
        except json.JSONDecodeError:
            data = {}
        error = data.get("error")
        if error:
            QMessageBox.warning(self, "Could not compare snapshots", error)
            return

        changes = data.get("changes", [])
        text = "\n".join(f"{c['status']}\t{c['path']}" for c in changes) or "No file changes."
        pre, post = self._status_pair

        dlg = QDialog(self)
        dlg.setWindowTitle(f"Changes between snapshot {pre} and {post}")
        dlg.resize(560, 420)
        lay = QVBoxLayout(dlg)
        view = QPlainTextEdit(text)
        view.setReadOnly(True)
        view.setFont(self._tree.font())
        lay.addWidget(view)
        box = QDialogButtonBox(QDialogButtonBox.Close)
        box.rejected.connect(dlg.reject)
        box.accepted.connect(dlg.accept)
        lay.addWidget(box)
        dlg.exec()

    # -- rollback / delete -------------------------------------------------- #

    def _on_rollback(self) -> None:
        s = self._selected()
        if s is None:
            return
        if (
            QMessageBox.question(
                self,
                "Set as default on next boot?",
                f"Snapshot {s['number']} will become the default subvolume the "
                "next time this system boots. This does not change the "
                "running system — reboot to apply it.",
                QMessageBox.Yes | QMessageBox.No,
                QMessageBox.No,
            )
            != QMessageBox.Yes
        ):
            return
        self._run(["rollback", str(s["number"])])

    def _on_delete(self) -> None:
        s = self._selected()
        if s is None:
            return
        if (
            QMessageBox.question(
                self,
                "Delete snapshot?",
                f"Snapshot {s['number']} ({s['description'] or 'no description'}) "
                "will be permanently deleted.",
                QMessageBox.Yes | QMessageBox.No,
                QMessageBox.No,
            )
            != QMessageBox.Yes
        ):
            return
        self._run(["delete", str(s["number"])])

    def _after_mutation(self, action: str, ok: bool, message: str) -> None:
        if not ok:
            verb = "roll back" if action == "rollback" else "delete"
            QMessageBox.warning(
                self, "Snapshot action failed", f"Could not {verb} the snapshot:\n{message}"
            )
        self._load()
