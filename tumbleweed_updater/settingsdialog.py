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

from .dupargs import FLAGS, VALUED, unknown_args
from .icons import idle_icon, text_color
from .intervals import INTERVALS
from .settings import (
    DEFAULT_TERM_BG,
    DEFAULT_TERM_FG,
    DEFAULT_TERM_FONT_SIZE,
    ICON_STYLES,
    REBOOT_ACTIONS,
    RESET_AFTER_UPDATE,
    Prefs,
    SettingsStore,
)

def _autostart_path() -> str:
    """Where the XDG autostart entry goes.

    Read at call time and through XDG_CONFIG_HOME, rather than pinned to
    ~/.config at import: that is what the spec says, and it keeps the tests out
    of the real user's configuration.
    """
    base = os.environ.get("XDG_CONFIG_HOME") or os.path.expanduser("~/.config")
    return os.path.join(base, "autostart", "tumbleweed-updater.desktop")

_AUTOSTART_BODY = """\
[Desktop Entry]
Type=Application
Name=Tumbleweed Updater
Exec={exec} --tray
Icon=tumbleweed-updater
Terminal=false
X-GNOME-Autostart-enabled=true
"""


def _desktop_exec(path: str) -> str:
    """Quote *path* for a desktop file's Exec= key.

    Per the Desktop Entry spec: reserved characters mean the argument must be
    double-quoted, and backslash, double quote, backtick and dollar are escaped
    with a backslash inside those quotes.
    """
    if not any(c in path for c in ' \t\n"\'\\><~|&;$*?#()`'):
        return path
    escaped = path
    for ch in "\\`$\"":
        escaped = escaped.replace(ch, "\\" + ch)
    return f'"{escaped}"'


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
        self.setAttribute(Qt.WA_DeleteOnClose)
        self._store = store
        self._privileged = privileged
        self._prefs = store.load()
        self._interval_connected = False
        self.finished.connect(self._disconnect_runner)

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
        self._autostart.setChecked(os.path.exists(_autostart_path()))
        form.addRow("", self._autostart)

        self._notify = QCheckBox("Show a notification when updates appear")
        self._notify.setChecked(self._prefs.notify_on_updates)
        form.addRow("", self._notify)

        self._flatpak = QCheckBox("Include Flatpak updates")
        self._flatpak.setChecked(self._prefs.include_flatpak)
        form.addRow("", self._flatpak)

        layout.addWidget(self._build_update_group())

        self._icon_style = QComboBox()
        for key, label in ICON_STYLES.items():
            self._icon_style.addItem(label, key)
        cur = self._icon_style.findData(self._prefs.icon_style)
        self._icon_style.setCurrentIndex(cur if cur >= 0 else 0)
        self._icon_preview = QLabel()
        self._icon_preview.setFixedSize(28, 28)
        self._icon_style.currentIndexChanged.connect(lambda _i: self._preview_icon())
        icon_row = QHBoxLayout()
        icon_row.addWidget(self._icon_style, 1)
        icon_row.addWidget(self._icon_preview)
        form.addRow("Tray icon:", icon_row)
        self._preview_icon()

        layout.addWidget(self._build_terminal_group())

        buttons = QDialogButtonBox(
            QDialogButtonBox.Save | QDialogButtonBox.Cancel
        )
        buttons.accepted.connect(self._save)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    # -- update behaviour ----------------------------------------------------- #

    def _build_update_group(self) -> QGroupBox:
        box = QGroupBox("Update behaviour")
        grid = QFormLayout(box)

        self._allow_vendor = QCheckBox("Allow packages to change vendor")
        self._allow_vendor.setChecked(self._prefs.dup_allow_vendor_change)
        self._allow_vendor.setToolTip(
            "Adds --allow-vendor-change. Normally zypper dup keeps each package "
            "with the repository that first provided it. Enable this only if you "
            "deliberately use a third-party repo such as Packman (multimedia "
            "codecs) and want its builds to replace the openSUSE ones.\n\n"
            "Warning: it also lets any enabled repo - including one added by "
            "mistake - take over system packages."
        )
        grid.addRow("", self._allow_vendor)

        self._non_interactive = QCheckBox("Install without asking me to confirm")
        self._non_interactive.setChecked(self._prefs.dup_non_interactive)
        self._non_interactive.setToolTip(
            "Adds -y --auto-agree-with-licenses, so zypper never pauses for "
            "'Continue? [y/n]' and auto-accepts licence agreements.\n\n"
            "Warning: if the upgrade hits a dependency conflict, zypper "
            "automatically applies its first proposed fix, which can remove or "
            "downgrade packages unexpectedly. On a rolling release, leave this "
            "off unless it is a routine update and you will still check the "
            "terminal output."
        )
        grid.addRow("", self._non_interactive)

        self._download_first = QCheckBox("Download all packages before installing")
        self._download_first.setChecked(self._prefs.dup_download_in_advance)
        self._download_first.setToolTip(
            "Adds --download in-advance. Downloads every package first, then "
            "installs them in one go. Safer on an unreliable connection - a "
            "dropped download cannot leave the system half-upgraded - but uses "
            "more disk during the update."
        )
        grid.addRow("", self._download_first)

        self._cleanup = QCheckBox("Free up disk space after updating")
        self._cleanup.setChecked(self._prefs.cleanup_after_update)
        self._cleanup.setToolTip(
            "Runs 'zypper clean' after a successful update to delete the "
            "downloaded package files (they are not needed once installed). "
            "Frees disk space; completely safe."
        )
        grid.addRow("", self._cleanup)

        self._reboot_action = QComboBox()
        for key, label in REBOOT_ACTIONS.items():
            self._reboot_action.addItem(label, key)
        idx = self._reboot_action.findData(self._prefs.reboot_action)
        self._reboot_action.setCurrentIndex(idx if idx >= 0 else 0)
        self._reboot_action.setToolTip(
            "Kernel, glibc, systemd and dbus updates need a reboot to take "
            "effect."
        )
        grid.addRow("When an update needs a reboot:", self._reboot_action)

        self._reset_after = QComboBox()
        for key, label in RESET_AFTER_UPDATE.items():
            self._reset_after.addItem(label, key)
        idx = self._reset_after.findData(self._prefs.reset_after_update)
        self._reset_after.setCurrentIndex(idx if idx >= 0 else 0)
        self._reset_after.setToolTip(
            "The terminal below the package list keeps the last update's output "
            "until this point, then clears itself and collapses out of the way.\n\n"
            "An update that failed always keeps its log, whichever option is "
            "chosen - it is the only record of what went wrong. So does one that "
            "is still running. You can also clear the log yourself at any time "
            "with the 'Hide log' button or the terminal's right-click menu."
        )
        grid.addRow("Reset the window after an update:", self._reset_after)

        self._dup_args = QLineEdit(self._prefs.zypper_dup_args)
        self._dup_args.setPlaceholderText("(none)")
        self._dup_args.setToolTip(
            "Appended to 'zypper dup' after the options set by the checkboxes "
            "above. Only options the privileged helper accepts are allowed:\n"
            + ", ".join(sorted(FLAGS | set(VALUED)))
        )
        grid.addRow("Extra 'zypper dup' options:", self._dup_args)

        return box

    # -- tray icon ---------------------------------------------------------- #

    def _preview_icon(self) -> None:
        style = self._icon_style.currentData()
        self._icon_preview.setPixmap(idle_icon(style, text_color()).pixmap(24, 24))

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
        # The helper refuses anything outside its allow-list, so catch it here
        # where the user can still see which word was the problem.
        rejected = unknown_args(self._dup_args.text().split())
        if rejected:
            QMessageBox.warning(
                self,
                "Unsupported zypper dup option",
                "These will not be accepted by the update helper:\n\n"
                + " ".join(rejected)
                + "\n\nAllowed options are:\n"
                + ", ".join(sorted(FLAGS | set(VALUED))),
            )
            return
        new = Prefs(
            check_interval=self._interval.currentText(),
            check_on_launch=self._on_launch.isChecked(),
            notify_on_updates=self._notify.isChecked(),
            zypper_dup_args=self._dup_args.text().strip(),
            include_flatpak=self._flatpak.isChecked(),
            term_font_family=self._chosen_font_family(),
            term_font_size=self._font_size.value(),
            term_bg=self._bg_btn.color_name(),
            term_fg=self._fg_btn.color_name(),
            icon_style=self._icon_style.currentData(),
            dup_allow_vendor_change=self._allow_vendor.isChecked(),
            dup_non_interactive=self._non_interactive.isChecked(),
            dup_download_in_advance=self._download_first.isChecked(),
            cleanup_after_update=self._cleanup.isChecked(),
            reboot_action=self._reboot_action.currentData(),
            reset_after_update=self._reset_after.currentData(),
        )
        self._store.save(new)
        self._apply_autostart(self._autostart.isChecked())

        if new.check_interval != self._prefs.check_interval:
            # One connection per dialog, dropped again as soon as the answer
            # arrives: the runner is shared and outlives us, so a connection
            # left behind would warn once per settings dialog ever opened.
            self._privileged.intervalFinished.connect(self._interval_done)
            self._interval_connected = True
            if not self._privileged.set_interval(new.check_interval):
                self._disconnect_runner()
                QMessageBox.warning(
                    self,
                    "Could not change the schedule",
                    "Another schedule change is still in progress. The rest of "
                    "your settings were saved.",
                )
                self.accept()
        else:
            self.accept()

    def _disconnect_runner(self, _result: int = 0) -> None:
        if not self._interval_connected:
            return
        self._interval_connected = False
        try:
            self._privileged.intervalFinished.disconnect(self._interval_done)
        except (RuntimeError, TypeError):
            pass  # already gone

    def _interval_done(self, ok: bool, message: str) -> None:
        self._disconnect_runner()
        if not ok:
            QMessageBox.warning(
                self,
                "Could not change the schedule",
                f"The update schedule was not changed:\n{message}",
            )
        self.accept()

    @staticmethod
    def _apply_autostart(enabled: bool) -> None:
        path = _autostart_path()
        if enabled:
            os.makedirs(os.path.dirname(path), exist_ok=True)
            exec_path = shutil.which("tumbleweed-updater") or "tumbleweed-updater"
            with open(path, "w", encoding="utf-8") as fh:
                fh.write(_AUTOSTART_BODY.format(exec=_desktop_exec(exec_path)))
        else:
            try:
                os.unlink(path)
            except FileNotFoundError:
                pass
