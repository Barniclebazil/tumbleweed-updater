"""Preferences dialog."""

from __future__ import annotations

import os
import shutil

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QColor, QFont
from PySide6.QtWidgets import (
    QCheckBox,
    QColorDialog,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFontComboBox,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QSpinBox,
    QVBoxLayout,
)

from .intervals import INTERVALS
from .settings import (
    DEFAULT_TERM_BG,
    DEFAULT_TERM_FG,
    DEFAULT_TERM_FONT_SIZE,
    Prefs,
    SettingsStore,
)

_AUTOSTART = os.path.expanduser("~/.config/autostart/tumbleweed-updater.desktop")

_AUTOSTART_BODY = """\
[Desktop Entry]
Type=Application
Name=Tumbleweed Updater
Exec={exec} --tray
Icon=tumbleweed-updater
Terminal=false
X-GNOME-Autostart-enabled=true
"""


class _ColorButton(QPushButton):
    """A button that shows its colour and opens a colour picker when clicked."""

    colorChanged = Signal()

    def __init__(self, color: str, parent=None) -> None:
        super().__init__(parent)
        self._color = QColor(color)
        self.setMinimumWidth(96)
        self.clicked.connect(self._pick)
        self._refresh()

    def color_name(self) -> str:
        return self._color.name()

    def set_color(self, color: str) -> None:
        self._color = QColor(color)
        self._refresh()
        self.colorChanged.emit()

    def _pick(self) -> None:
        chosen = QColorDialog.getColor(self._color, self, "Choose colour")
        if chosen.isValid():
            self._color = chosen
            self._refresh()
            self.colorChanged.emit()

    def _refresh(self) -> None:
        text_col = "#000" if self._color.lightnessF() > 0.5 else "#fff"
        self.setText(self._color.name())
        self.setStyleSheet(
            f"background:{self._color.name()}; color:{text_col};"
            "padding:4px; border:1px solid palette(mid); border-radius:3px;"
        )


class SettingsDialog(QDialog):
    def __init__(self, store: SettingsStore, privileged, parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Tumbleweed Updater — Settings")
        self._store = store
        self._privileged = privileged
        self._prefs = store.load()

        layout = QVBoxLayout(self)
        form = QFormLayout()
        layout.addLayout(form)

        self._interval = QComboBox()
        for label in INTERVALS:
            self._interval.addItem(label)
        self._interval.setCurrentText(self._prefs.check_interval)
        form.addRow("Check for updates:", self._interval)

        hint = QLabel(
            "The check runs as a system service (systemd timer) so it works "
            "even when this window is closed. Changing it needs admin rights."
        )
        hint.setWordWrap(True)
        hint.setStyleSheet("color: palette(mid); font-size: 9pt;")
        form.addRow("", hint)

        self._on_launch = QCheckBox("Also check when this app starts")
        self._on_launch.setChecked(self._prefs.check_on_launch)
        form.addRow("", self._on_launch)

        self._autostart = QCheckBox("Start automatically at login (in the tray)")
        self._autostart.setChecked(os.path.exists(_AUTOSTART))
        form.addRow("", self._autostart)

        self._notify = QCheckBox("Show a notification when updates appear")
        self._notify.setChecked(self._prefs.notify_on_updates)
        form.addRow("", self._notify)

        self._flatpak = QCheckBox("Include Flatpak updates")
        self._flatpak.setChecked(self._prefs.include_flatpak)
        form.addRow("", self._flatpak)

        self._dup_args = QLineEdit(self._prefs.zypper_dup_args)
        self._dup_args.setPlaceholderText("(none)")
        form.addRow("Extra 'zypper dup' options:", self._dup_args)

        layout.addWidget(self._build_terminal_group())

        buttons = QDialogButtonBox(
            QDialogButtonBox.Save | QDialogButtonBox.Cancel
        )
        buttons.accepted.connect(self._save)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    # -- terminal appearance ---------------------------------------------- #

    def _build_terminal_group(self) -> QGroupBox:
        box = QGroupBox("Terminal appearance")
        grid = QFormLayout(box)

        self._use_system_font = QCheckBox("Use the system fixed-width font")
        self._use_system_font.setChecked(not self._prefs.term_font_family)
        self._use_system_font.toggled.connect(self._on_font_toggle)
        grid.addRow("", self._use_system_font)

        self._font_family = QFontComboBox()
        self._font_family.setFontFilters(QFontComboBox.MonospacedFonts)
        if self._prefs.term_font_family:
            self._font_family.setCurrentFont(QFont(self._prefs.term_font_family))
        self._font_family.setEnabled(bool(self._prefs.term_font_family))
        self._font_family.currentFontChanged.connect(lambda _f: self._preview())
        grid.addRow("Font:", self._font_family)

        self._font_size = QSpinBox()
        self._font_size.setRange(6, 32)
        self._font_size.setValue(self._prefs.term_font_size or DEFAULT_TERM_FONT_SIZE)
        self._font_size.setSuffix(" pt")
        self._font_size.valueChanged.connect(lambda _v: self._preview())
        grid.addRow("Size:", self._font_size)

        self._bg_btn = _ColorButton(self._prefs.term_bg or DEFAULT_TERM_BG)
        self._fg_btn = _ColorButton(self._prefs.term_fg or DEFAULT_TERM_FG)
        for btn in (self._bg_btn, self._fg_btn):
            btn.colorChanged.connect(self._preview)
        colors = QHBoxLayout()
        colors.addWidget(QLabel("Background:"))
        colors.addWidget(self._bg_btn)
        colors.addSpacing(12)
        colors.addWidget(QLabel("Text:"))
        colors.addWidget(self._fg_btn)
        colors.addStretch(1)
        reset = QPushButton("Reset")
        reset.clicked.connect(self._reset_terminal)
        colors.addWidget(reset)
        grid.addRow("Colours:", colors)

        self._preview_label = QLabel(
            "glibc  5.2.32-1.1 → 5.2.37-1.1\nChoose from above [1/2/c] (c): "
        )
        self._preview_label.setMinimumHeight(52)
        self._preview_label.setTextInteractionFlags(Qt.NoTextInteraction)
        grid.addRow("Preview:", self._preview_label)

        self._preview()
        return box

    def _on_font_toggle(self, use_system: bool) -> None:
        self._font_family.setEnabled(not use_system)
        self._preview()

    def _reset_terminal(self) -> None:
        self._use_system_font.setChecked(True)
        self._font_size.setValue(DEFAULT_TERM_FONT_SIZE)
        self._bg_btn.set_color(DEFAULT_TERM_BG)
        self._fg_btn.set_color(DEFAULT_TERM_FG)
        self._preview()

    def _chosen_font_family(self) -> str:
        if self._use_system_font.isChecked():
            return ""
        return self._font_family.currentFont().family()

    def _preview(self) -> None:
        family = self._chosen_font_family()
        font = QFont(family) if family else QFont()
        if not family:
            font.setStyleHint(QFont.Monospace)
            font.setFamily("monospace")
        font.setPointSize(self._font_size.value())
        self._preview_label.setFont(font)
        self._preview_label.setStyleSheet(
            f"background:{self._bg_btn.color_name()};"
            f"color:{self._fg_btn.color_name()};"
            "padding:6px; border-radius:3px;"
        )

    # -- persistence ---------------------------------------------------------- #

    def _save(self) -> None:
        new = Prefs(
            check_interval=self._interval.currentText(),
            check_on_launch=self._on_launch.isChecked(),
            start_in_tray=self._prefs.start_in_tray,
            notify_on_updates=self._notify.isChecked(),
            zypper_dup_args=self._dup_args.text().strip(),
            include_flatpak=self._flatpak.isChecked(),
            term_font_family=self._chosen_font_family(),
            term_font_size=self._font_size.value(),
            term_bg=self._bg_btn.color_name(),
            term_fg=self._fg_btn.color_name(),
        )
        self._store.save(new)
        self._apply_autostart(self._autostart.isChecked())

        if new.check_interval != self._prefs.check_interval:
            self._privileged.intervalFinished.connect(self._interval_done)
            self._privileged.set_interval(new.check_interval)
        else:
            self.accept()

    def _interval_done(self, ok: bool, message: str) -> None:
        if not ok:
            QMessageBox.warning(
                self,
                "Could not change the schedule",
                f"The update schedule was not changed:\n{message}",
            )
        self.accept()

    @staticmethod
    def _apply_autostart(enabled: bool) -> None:
        if enabled:
            os.makedirs(os.path.dirname(_AUTOSTART), exist_ok=True)
            exec_path = shutil.which("tumbleweed-updater") or "tumbleweed-updater"
            with open(_AUTOSTART, "w", encoding="utf-8") as fh:
                fh.write(_AUTOSTART_BODY.format(exec=exec_path))
        else:
            try:
                os.unlink(_AUTOSTART)
            except FileNotFoundError:
                pass
