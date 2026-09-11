"""The update window: a summary, the package list, and the embedded terminal."""

from __future__ import annotations

from datetime import datetime, timezone

from PySide6.QtCore import QProcess, Qt, Signal
from PySide6.QtGui import QAction, QColor, QPalette
from PySide6.QtWidgets import (
    QAbstractItemView,
    QApplication,
    QCheckBox,
    QHBoxLayout,
    QLabel,
    QMainWindow,
    QMessageBox,
    QProgressBar,
    QPushButton,
    QSplitter,
    QTreeWidget,
    QTreeWidgetItem,
    QVBoxLayout,
    QWidget,
)

from . import APP_NAME
from .icons import window_icon
from .runner import UpdateRunner
from .settings import SettingsStore, dup_args_from_prefs
from .settingsdialog import SettingsDialog
from .sources import Action, UpdateStatus, human_bytes
from .terminal import TerminalWidget, build_terminal_font
from .tray import TrayState
from .workers import FlatpakChecker

_ACTION_LABELS = {
    Action.UPGRADE: "upgrade",
    Action.DOWNGRADE: "downgrade",
    Action.INSTALL: "new",
    Action.REINSTALL: "reinstall",
    Action.REMOVE: "remove",
    Action.CHANGE_ARCH: "arch change",
}


def _relative_time(iso: str) -> str:
    if not iso:
        return "never"
    try:
        when = datetime.fromisoformat(iso)
    except ValueError:
        return "unknown"
    if when.tzinfo is None:
        when = when.replace(tzinfo=timezone.utc)
    delta = datetime.now(timezone.utc) - when
    secs = int(delta.total_seconds())
    if secs < 90:
        return "just now"
    if secs < 3600:
        return f"{secs // 60} min ago"
    if secs < 86400:
        return f"{secs // 3600} h ago"
    return f"{secs // 86400} d ago"


class MainWindow(QMainWindow):
    stateChanged = Signal(object, str)  # TrayState, tooltip
    checkRequested = Signal()
    settingsApplied = Signal()  # emitted after the settings dialog is accepted

    def __init__(self, settings: SettingsStore, privileged) -> None:
        super().__init__()
        self._settings = settings
        self._privileged = privileged
        self._status = UpdateStatus()
        self._flatpak_checked = False

        self.setWindowTitle(APP_NAME)
        self.setWindowIcon(window_icon(self._settings.load().icon_style))
        self.resize(760, 620)

        self._build_ui()

        self._flatpak = FlatpakChecker(self)
        self._flatpak.finished.connect(self._on_flatpak_result)

        self._runner = UpdateRunner(self._terminal, self)
        self._runner.stepStarted.connect(lambda label: self._statusbar(label))
        self._runner.finished.connect(self._on_run_finished)

        self._privileged.checkFinished.connect(self._on_check_finished)

        self._render()

    # -- construction ---------------------------------------------------- #

    def _build_ui(self) -> None:
        central = QWidget()
        outer = QVBoxLayout(central)
        outer.setContentsMargins(12, 12, 12, 12)
        outer.setSpacing(8)

        self._headline = QLabel()
        self._headline.setStyleSheet("font-size: 15pt; font-weight: 600;")
        self._subline = QLabel()
        self._subline.setStyleSheet("color: palette(mid);")
        outer.addWidget(self._headline)
        outer.addWidget(self._subline)

        self._banner = QLabel()
        self._banner.setWordWrap(True)
        self._banner.setStyleSheet(
            "background: #f67400; color: white; border-radius: 4px; padding: 6px;"
        )
        self._banner.hide()
        outer.addWidget(self._banner)

        self._splitter = QSplitter(Qt.Vertical)
        outer.addWidget(self._splitter, 1)

        top = QWidget()
        top_l = QVBoxLayout(top)
        top_l.setContentsMargins(0, 0, 0, 0)

        self._chk_system = QCheckBox("System upgrade — zypper dup")
        self._chk_flatpak = QCheckBox("Flatpak updates")
        for chk in (self._chk_system, self._chk_flatpak):
            chk.setChecked(True)
            chk.toggled.connect(self._update_buttons)
            top_l.addWidget(chk)

        self._tree = QTreeWidget()
        self._tree.setHeaderLabels(["Package", "Change", "Arch"])
        self._tree.setRootIsDecorated(True)
        self._tree.setSelectionMode(QAbstractItemView.NoSelection)
        self._tree.setAlternatingRowColors(True)
        self._tree.header().setStretchLastSection(False)
        self._tree.setColumnWidth(0, 320)
        self._tree.setColumnWidth(1, 260)
        top_l.addWidget(self._tree, 1)
        self._splitter.addWidget(top)

        p = self._settings.load()
        self._apply_list_appearance(p)

        self._terminal_box = QWidget()
        tb_l = QVBoxLayout(self._terminal_box)
        tb_l.setContentsMargins(0, 0, 0, 0)
        tb_l.addWidget(QLabel("Terminal — answer zypper's prompts here:"))
        self._terminal = TerminalWidget(
            font_family=p.term_font_family,
            font_size=p.term_font_size,
            bg=p.term_bg,
            fg=p.term_fg,
        )
        tb_l.addWidget(self._terminal, 1)
        self._splitter.addWidget(self._terminal_box)
        self._terminal_box.hide()
        self._splitter.setStretchFactor(0, 3)
        self._splitter.setStretchFactor(1, 4)

        buttons = QHBoxLayout()
        self._btn_check = QPushButton("Check now")
        self._btn_check.clicked.connect(self._on_check_clicked)
        self._progress = QProgressBar()
        self._progress.setRange(0, 0)
        self._progress.setMaximumWidth(140)
        self._progress.hide()
        self._btn_update = QPushButton("Update now…")
        self._btn_update.setDefault(True)
        self._btn_update.clicked.connect(self._on_update_clicked)
        self._btn_cancel = QPushButton("Cancel")
        self._btn_cancel.clicked.connect(self._runner_cancel)
        self._btn_cancel.hide()
        buttons.addWidget(self._btn_check)
        buttons.addWidget(self._progress)
        buttons.addStretch(1)
        buttons.addWidget(self._btn_cancel)
        buttons.addWidget(self._btn_update)
        outer.addLayout(buttons)

        self.setCentralWidget(central)

        settings_act = QAction("Settings…", self)
        settings_act.triggered.connect(self.open_settings)
        quit_act = QAction("Quit", self)
        quit_act.triggered.connect(QApplication.instance().quit)
        menu = self.menuBar().addMenu("&Menu")
        menu.addAction(settings_act)
        menu.addSeparator()
        menu.addAction(quit_act)

        self.statusBar()

    # -- external API -------------------------------------------------------- #

    def apply_zypper_status(self, status: UpdateStatus) -> None:
        """Called when the status file (written by the root checker) changes."""
        self._status.zypper = status.zypper
        self._status.generated = status.generated
        self._status.snapshots_ok = status.snapshots_ok
        self._render()

    def trigger_check(self) -> None:
        self._on_check_clicked()

    def trigger_update(self) -> None:
        self.show_and_raise()
        self._on_update_clicked()

    @property
    def runner_active(self) -> bool:
        return self._runner.is_running

    def show_and_raise(self) -> None:
        self.showNormal()
        self.raise_()
        self.activateWindow()

    # -- checking ---------------------------------------------------------- #

    def _on_check_clicked(self) -> None:
        if self._privileged.check_running or self._runner.is_running:
            return
        self._set_busy(True, "Checking for updates…")
        self.stateChanged.emit(TrayState.BUSY, "Checking for updates…")
        self._privileged.run_check()
        self._flatpak.start()

    def _on_check_finished(self, ok: bool, message: str) -> None:
        self._set_busy(False, "")
        if not ok:
            self._show_banner(f"Update check failed: {message}")
        else:
            self._hide_banner()
            self._statusbar("Update check complete.")
        # The status file watcher re-renders; render now too in case it was a
        # no-op write.
        self._render()

    def _on_flatpak_result(self, result) -> None:
        self._status.flatpak = result
        self._flatpak_checked = True
        self._render()

    def _apply_list_appearance(self, prefs) -> None:
        self._tree.setFont(build_terminal_font(prefs.term_font_family, prefs.term_font_size))
        base = QColor(prefs.term_bg)
        pal = self._tree.palette()
        pal.setColor(QPalette.Base, base)
        pal.setColor(
            QPalette.AlternateBase,
            base.lighter(112) if base.lightness() < 128 else base.darker(106),
        )
        pal.setColor(QPalette.Text, QColor(prefs.term_fg))
        self._tree.setPalette(pal)

    # -- updating -------------------------------------------------------- #

    def _on_update_clicked(self) -> None:
        if self._runner.is_running:
            return
        prefs = self._settings.load()
        do_zypper = self._chk_system.isChecked() and self._status.zypper.count > 0
        flatpak_refs = self._status.flatpak.refs if prefs.include_flatpak else []
        do_fp_sys = self._chk_flatpak.isChecked() and any(
            r.installation == "system" for r in flatpak_refs
        )
        do_fp_user = self._chk_flatpak.isChecked() and any(
            r.installation == "user" for r in flatpak_refs
        )
        if not (do_zypper or do_fp_sys or do_fp_user):
            return

        lines = ["The following will run in the terminal below:"]
        if do_zypper:
            note = (
                "zypper dup (a Btrfs snapshot is created automatically)"
                if self._status.snapshots_ok
                else "zypper dup — WARNING: snapper-zypp-plugin is missing, "
                "no snapshot will be taken"
            )
            lines.append(f"  • {note}")
        if do_fp_sys:
            lines.append("  • flatpak update (system)")
        if do_fp_user:
            lines.append("  • flatpak --user update")

        if do_zypper:
            notes = []
            if prefs.dup_allow_vendor_change:
                notes.append("allow packages to change vendor/repository")
            if prefs.dup_non_interactive:
                notes.append(
                    "skip confirmation prompts — zypper auto-applies its first "
                    "fix for any conflict"
                )
            if prefs.dup_download_in_advance:
                notes.append("download everything before installing")
            if prefs.cleanup_after_update:
                notes.append("clear the package cache afterwards")
            if notes:
                lines.append("")
                lines.append("Options in effect:")
                lines += [f"  • {n}" for n in notes]

        steps = self._runner.build_queue(
            do_zypper=do_zypper,
            dup_args=dup_args_from_prefs(prefs),
            cleanup=prefs.cleanup_after_update,
            do_flatpak_system=do_fp_sys,
            do_flatpak_user=do_fp_user,
        )
        self._terminal_box.show()
        self._terminal.append_notice("\n".join(lines))
        self._set_running(True)
        self.stateChanged.emit(TrayState.BUSY, "Installing updates…")
        self._runner.start(steps)
        self._terminal.setFocus()

    def _runner_cancel(self) -> None:
        self._runner.cancel()

    def _on_run_finished(self, ok: bool, message: str) -> None:
        self._set_running(False)
        self._statusbar(message)
        if ok and self._status.zypper.need_reboot:
            self._handle_reboot_needed()
        if not ok:
            self._show_banner(message)
        # Re-check so the list and counts reflect reality.
        self._on_check_clicked()

    def _handle_reboot_needed(self) -> None:
        body = (
            "The update installed components that need a reboot to take effect "
            "(kernel, glibc, systemd, …)."
        )
        if self._settings.load().reboot_action == "offer":
            if (
                QMessageBox.question(
                    self,
                    "Reboot now?",
                    body + "\n\nReboot now?",
                    QMessageBox.Yes | QMessageBox.No,
                    QMessageBox.No,
                )
                == QMessageBox.Yes
            ):
                # logind allows an active local session to reboot without pkexec.
                QProcess.startDetached("systemctl", ["reboot"])
        else:
            QMessageBox.information(self, "Reboot recommended", body)

    # -- rendering ----------------------------------------------------------- #

    def _include_flatpak(self) -> bool:
        return self._settings.load().include_flatpak

    def _render(self) -> None:
        z = self._status.zypper
        f = self._status.flatpak
        fp_count = f.count if self._include_flatpak() else 0
        total = z.count + fp_count

        self._tree.clear()
        if z.count:
            self._add_group(
                f"System upgrade — {z.count} package(s)",
                [
                    (p.name, f"{_ACTION_LABELS.get(p.action, '')} · {p.summary_line}"
                     if p.summary_line else _ACTION_LABELS.get(p.action, ""), p.arch)
                    for p in z.packages
                ],
            )
        if fp_count:
            self._add_group(
                f"Flatpak — {f.count} app(s)",
                [
                    (r.ref_id, f"→ {r.version}" if r.version else "update",
                     f"{r.installation} · {r.origin}")
                    for r in f.refs
                ],
            )
        self._tree.expandAll()

        # A category defaults to "checked" when it first has something to do;
        # an explicit uncheck is kept as long as the category stays available.
        for chk, count in (
            (self._chk_system, z.count),
            (self._chk_flatpak, fp_count),
        ):
            if count == 0:
                chk.setChecked(False)
                chk.setEnabled(False)
            else:
                if not chk.isEnabled():
                    chk.setChecked(True)
                chk.setEnabled(not self._runner.is_running)

        checked = _relative_time(self._status.generated)
        if z.error:
            self._headline.setText("Could not check for system updates")
            self._show_banner(z.error)
        elif total == 0:
            self._headline.setText("Your system is up to date")
            self._hide_banner()
        else:
            self._headline.setText(f"{total} update(s) available")
            if not self._status.snapshots_ok and z.count:
                self._show_banner(
                    "snapper-zypp-plugin is not installed — running the upgrade "
                    "will NOT create a Btrfs snapshot. Install it with: "
                    "zypper install snapper-zypp-plugin"
                )
            else:
                self._hide_banner()

        bits = [f"Last checked {checked}"]
        if z.count and z.download_size:
            bits.append(f"download {human_bytes(z.download_size)}")
        if z.count and z.space_diff:
            bits.append(f"disk {human_bytes(z.space_diff)}")
        self._subline.setText(" · ".join(bits))

        self._update_buttons()
        self._emit_state()

    def _add_group(self, title: str, rows: list[tuple[str, str, str]]) -> None:
        parent = QTreeWidgetItem([title, "", ""])
        font = parent.font(0)
        font.setBold(True)
        parent.setFont(0, font)
        self._tree.addTopLevelItem(parent)
        for name, change, arch in rows:
            parent.addChild(QTreeWidgetItem([name, change, arch]))

    def _emit_state(self) -> None:
        z = self._status.zypper
        total = z.count + (
            self._status.flatpak.count if self._include_flatpak() else 0
        )
        if self._runner.is_running or self._privileged.check_running:
            return
        if z.error:
            self.stateChanged.emit(TrayState.ERROR, z.error)
        elif total > 0:
            self.stateChanged.emit(
                TrayState.UPDATES, f"{total} update(s) available"
            )
        else:
            self.stateChanged.emit(TrayState.IDLE, "Up to date")

    # -- ui state helpers ------------------------------------------------- #

    def _update_buttons(self) -> None:
        z = self._status.zypper
        fp = self._status.flatpak.count if self._include_flatpak() else 0
        has = (self._chk_system.isChecked() and z.count > 0) or (
            self._chk_flatpak.isChecked() and fp > 0
        )
        self._btn_update.setEnabled(has and not self._runner.is_running)

    def _set_busy(self, busy: bool, text: str) -> None:
        self._btn_check.setEnabled(not busy)
        self._progress.setVisible(busy)
        if text:
            self._statusbar(text)

    def _set_running(self, running: bool) -> None:
        self._btn_update.setVisible(not running)
        self._btn_cancel.setVisible(running)
        self._btn_check.setEnabled(not running)
        self._chk_system.setEnabled(not running and self._status.zypper.count > 0)
        self._chk_flatpak.setEnabled(
            not running and self._status.flatpak.count > 0
        )
        self._progress.setVisible(running)

    def _statusbar(self, text: str) -> None:
        self.statusBar().showMessage(text, 8000)

    def _show_banner(self, text: str) -> None:
        self._banner.setText(text)
        self._banner.show()

    def _hide_banner(self) -> None:
        self._banner.hide()

    # -- settings -------------------------------------------------------- #

    def open_settings(self) -> None:
        dlg = SettingsDialog(self._settings, self._privileged, self)
        dlg.exec()
        p = self._settings.load()
        self._terminal.apply_appearance(
            font_family=p.term_font_family,
            font_size=p.term_font_size,
            bg=p.term_bg,
            fg=p.term_fg,
        )
        self._apply_list_appearance(p)
        self.setWindowIcon(window_icon(p.icon_style))
        self._render()
        self.settingsApplied.emit()

    # -- window lifecycle ----------------------------------------------- #

    def closeEvent(self, event) -> None:  # noqa: N802
        if self._runner.is_running:
            if (
                QMessageBox.question(
                    self,
                    "Update in progress",
                    "An update is still running. Hide the window and keep it "
                    "running in the background?",
                    QMessageBox.Yes | QMessageBox.No,
                    QMessageBox.Yes,
                )
                != QMessageBox.Yes
            ):
                event.ignore()
                return
        # Hide to tray instead of quitting.
        event.ignore()
        self.hide()
