"""The update window: a summary, the package list, and the embedded terminal."""

from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
from functools import partial

from PySide6.QtCore import QProcess, Qt, Signal
from PySide6.QtGui import QAction, QColor, QPalette
from PySide6.QtWidgets import (
    QAbstractItemView,
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

from . import APP_NAME, __version__
from .icons import window_icon
from .repos import list_repos
from .runner import UpdateRunner
from .settings import SettingsStore, dup_args_from_prefs
from .settingsdialog import SettingsDialog
from .snapshotsdialog import SnapshotsDialog
from .sources import Action, UpdateStatus, human_bytes
from .statusfile import read as read_status
from .terminal import TerminalWidget, build_terminal_font
from .tray import TrayState
from .workers import FlatpakChecker, LockWaiter

# Two looks for the one banner, and the rule for choosing is whether something
# is wrong with this computer. Orange says so. Everything else - a statement of
# fact like "VLC is switched off", and a source that cannot be reached at the
# moment - is written in the window's own text, because an orange bar tells a
# user their machine is in trouble when it is not.
#
# The warning rules are scoped by object name because a plain "background: ..."
# on the banner cascades into the button inside it, which then loses every
# trace of being a button and reads as a line of text. The plain variant wants
# exactly that cascade to stay out of the way, so it sets nothing but the
# background and lets the button keep the theme's own look.
_BANNER_STYLES = {
    "warning": """
        #banner { background: #f67400; color: white; border-radius: 4px; }
        #banner QPushButton {
            background: rgba(0, 0, 0, 0.22);
            color: white;
            border: 1px solid rgba(255, 255, 255, 0.7);
            border-radius: 3px;
            padding: 4px 12px;
        }
        #banner QPushButton:hover { background: rgba(0, 0, 0, 0.38); }
        #banner QPushButton:disabled {
            color: rgba(255, 255, 255, 0.5);
            border-color: rgba(255, 255, 255, 0.3);
        }
    """,
    # No box, no colour, nothing overridden: the text sits in the window like
    # any other sentence and the button keeps the theme's own look. This is
    # what a software source being briefly unreachable gets. It is somebody
    # else's server having a bad day, the update has a way round it, and
    # dressing that up as an alert is what made a routine problem look like a
    # broken computer.
    "plain": """
        #banner { background: transparent; color: palette(text); }
    """,
}

# Room around the orange box; the plain text lines up with the headline above
# it instead.
_BANNER_MARGINS = {"warning": (8, 6, 8, 6), "plain": (0, 2, 0, 2)}

# The window's own update button when there is nothing special to say. It is
# relabelled while the banner is offering the other half of the choice; see
# _update_buttons().
_UPDATE_BUTTON_TEXT = "Update now…"

_ACTION_LABELS = {
    Action.UPGRADE: "upgrade",
    Action.DOWNGRADE: "downgrade",
    Action.INSTALL: "new",
    Action.REINSTALL: "reinstall",
    Action.REMOVE: "remove",
    Action.CHANGE_ARCH: "arch change",
}


def _missing_sources_text(failed: list[tuple[str, str]], total: int) -> str:
    """The notice for software sources that could not be reached.

    Written for someone who has never heard of a repository: what happened,
    what it means for the programs that came from the source, and that it is
    probably not their problem to fix. The user sees the source's display name;
    the alias stays internal.

    It says the source was left out "when checking for updates", which is the
    literal truth and was not what this used to claim. Nothing has been left
    out of an *update* at this point: no update has run. The check refreshed
    every source, this one failed, zypper skipped it, and the dry run then
    counted what the rest had to offer.

    Nor does it promise the rest "can still be installed", which it did once.
    That is true only while zypper still has usable details for the missing
    source on disk. Once those go stale it refuses the upgrade outright - dup
    is the one command that will not run against an incomplete set of sources,
    and it says so itself: "If a failing repository is actually not needed, it
    must be disabled." The way past that is the button beside this text.
    """
    names = [name for _alias, name in failed]
    if len(names) == 1:
        opening = (
            "This application could not reach the software source "
            f'"{names[0]}", so that source was left out when checking for '
            "updates."
        )
        theirs = "that software source"
        again = "the software source can be reached again"
    else:
        opening = (
            f"This application could not reach {len(names)} of your software "
            f"sources ({', '.join(names)}), so those sources were left out "
            "when checking for updates."
        )
        theirs = "those software sources"
        again = "the software sources can be reached again"
    rest = (
        f"The other {total} updates were checked as usual."
        if total
        else "Everything else was checked as usual."
    )
    return (
        f"{opening} {rest} Programs you have installed from {theirs} keep "
        f"working, however they will not get updates until {again}. This is "
        "usually a temporary problem at the other end, so it is worth trying "
        "again tomorrow."
    )


def _day(day) -> str:
    """A date the way the user writes one."""
    return day.strftime("%d/%m/%Y")


def _deferred_sources_text(failed: list[tuple[str, str]], day) -> str:
    """The banner while the check is deferred: one line, no buttons.

    The full explanation is the right thing to read once and the wrong thing to
    keep reading after deciding to ignore it. The headline carries the date as
    well; this says which source it was about.
    """
    names = [name for _alias, name in failed]
    subject = (
        names[0]
        if len(names) == 1
        else f"{len(names)} of your software sources ({', '.join(names)})"
    )
    return f"{subject} could not be reached. This was put off until {_day(day)}."


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
    restartRequested = Signal()  # "Restart App" clicked on the update notice
    quitRequested = Signal()  # Menu -> Quit; the app owns the confirmation
    # Emitted the first time the window is actually put on screen. Anything
    # that must not pop up over an empty desktop (the app can start straight
    # into the tray) waits for this.
    firstShown = Signal()

    def __init__(self, settings: SettingsStore, privileged) -> None:
        super().__init__()
        self._settings = settings
        self._privileged = privileged
        self._status = UpdateStatus()
        self._flatpak_checked = False
        # Set for real by _render_banner(); needed before that, because
        # _build_ui() reaches _update_buttons() through _set_running().
        self._banner_offers_leave_out = False

        self.setWindowTitle(APP_NAME)
        self.setWindowIcon(window_icon(self._settings.load().icon_style))
        self.resize(760, 620)

        self._build_ui()

        self._has_been_shown = False
        self._flatpak = FlatpakChecker(self)
        self._flatpak.finished.connect(self._on_flatpak_result)
        self._lock_waiter = LockWaiter(self)
        self._lock_waiter.finished.connect(self._on_lock_wait_done)

        self._runner = UpdateRunner(self._terminal, self)
        self._runner.stepStarted.connect(lambda label: self._statusbar(label))
        self._runner.finished.connect(self._on_run_finished)
        self._terminal.clearRequested.connect(self._reset_log_view)

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

        self._update_notice = QWidget()
        self._update_notice.setAttribute(Qt.WA_StyledBackground, True)
        self._update_notice.setStyleSheet(
            "background: #2a7fff; color: white; border-radius: 4px;"
        )
        notice_l = QHBoxLayout(self._update_notice)
        notice_l.setContentsMargins(8, 6, 8, 6)
        self._update_label = QLabel()
        self._update_label.setWordWrap(True)
        notice_l.addWidget(self._update_label, 1)
        restart_btn = QPushButton("Restart App")
        restart_btn.clicked.connect(self.restartRequested.emit)
        notice_l.addWidget(restart_btn)
        self._update_notice.hide()
        outer.addWidget(self._update_notice)

        self._banner = QWidget()
        self._banner.setObjectName("banner")  # the style rules select on this
        self._banner.setAttribute(Qt.WA_StyledBackground, True)
        self._banner.setStyleSheet(_BANNER_STYLES["warning"])
        # Stacked, not side by side: these messages are a few sentences long
        # now, and a button sitting at the end of a wrapped paragraph reads as
        # part of the sentence rather than as something to press.
        banner_l = QVBoxLayout(self._banner)
        self._banner_layout = banner_l
        banner_l.setContentsMargins(*_BANNER_MARGINS["warning"])
        banner_l.setSpacing(6)
        self._banner_label = QLabel()
        self._banner_label.setWordWrap(True)
        # These three carry zypper's and the helpers' own words. QLabel would
        # otherwise sniff them for markup and render it.
        for label in (self._headline, self._subline, self._banner_label):
            label.setTextFormat(Qt.PlainText)
        banner_l.addWidget(self._banner_label)
        # Both buttons' labels and jobs depend on what the banner is saying, so
        # each is wired once to a dispatcher and _show_banner() sets the rest.
        # The alternative sits to the *left* of the primary one, the way a
        # dialog puts its lesser choice there.
        self._banner_btn = QPushButton()
        self._banner_action = None
        self._banner_btn.clicked.connect(self._on_banner_button)
        self._banner_btn.hide()
        self._banner_btn_alt = QPushButton()
        self._banner_alt_action = None
        self._banner_btn_alt.clicked.connect(self._on_banner_alt_button)
        self._banner_btn_alt.hide()
        btn_row = QHBoxLayout()
        btn_row.setContentsMargins(0, 0, 0, 0)
        btn_row.addStretch(1)
        btn_row.addWidget(self._banner_btn_alt)
        btn_row.addWidget(self._banner_btn)
        banner_l.addLayout(btn_row)
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
        self._btn_hide_log = QPushButton("Hide log")
        self._btn_hide_log.setToolTip(
            "Clear the terminal and collapse it out of the way."
        )
        self._btn_hide_log.clicked.connect(self._reset_log_view)
        self._btn_hide_log.hide()
        self._progress = QProgressBar()
        self._progress.setRange(0, 0)
        self._progress.setMaximumWidth(140)
        self._progress.hide()
        self._btn_update = QPushButton(_UPDATE_BUTTON_TEXT)
        self._btn_update.setDefault(True)
        self._btn_update.clicked.connect(self._on_update_button_clicked)
        self._btn_cancel = QPushButton("Cancel")
        self._btn_cancel.clicked.connect(self._runner_cancel)
        self._btn_cancel.hide()
        buttons.addWidget(self._btn_check)
        buttons.addWidget(self._btn_hide_log)
        buttons.addWidget(self._progress)
        buttons.addStretch(1)
        buttons.addWidget(self._btn_cancel)
        buttons.addWidget(self._btn_update)
        outer.addLayout(buttons)

        self.setCentralWidget(central)

        settings_act = QAction("Settings…", self)
        settings_act.triggered.connect(self.open_settings)
        snapshots_act = QAction("Snapshots…", self)
        snapshots_act.triggered.connect(self._open_snapshots)
        about_act = QAction("About…", self)
        about_act.triggered.connect(self._open_about)
        quit_act = QAction("Quit", self)
        # Not QApplication.quit directly: that would skip the "an update is
        # still running" confirmation the tray's Quit goes through, and
        # tearing down the terminal SIGHUPs a zypper transaction in flight.
        quit_act.triggered.connect(self.quitRequested.emit)
        menu = self.menuBar().addMenu("&Menu")
        menu.addAction(settings_act)
        menu.addAction(snapshots_act)
        menu.addSeparator()
        menu.addAction(about_act)
        menu.addSeparator()
        menu.addAction(quit_act)

        self.statusBar()

    # -- external API -------------------------------------------------------- #

    def apply_zypper_status(self, status: UpdateStatus) -> None:
        """Called when the status file (written by the root checker) changes."""
        # The background check runs every few hours whether or not the user put
        # anything off. If it comes back clean the thing they were avoiding has
        # gone, and there is no reason to keep hiding the updates from them.
        if not status.zypper.error and not status.zypper.failed_repos:
            self._settings.set_deferred_until(None)
        self._status.zypper = status.zypper
        self._status.generated = status.generated
        self._status.snapshots_ok = status.snapshots_ok
        self._render()

    def show_update_available(self, new_version: str) -> None:
        """Called once the running app is older than its own installed files."""
        self._update_label.setText(
            f"Tumbleweed Updater has been updated to version {new_version}. "
            "Restart the app to use it."
        )
        self._update_notice.show()

    def trigger_check(self) -> None:
        self._on_check_clicked()

    def trigger_update(self) -> None:
        self.show_and_raise()
        self._on_update_clicked()

    @property
    def runner_active(self) -> bool:
        return self._runner.is_running

    def reload_icon(self) -> None:
        """Rebuild the window icon: the style changed, or the theme did."""
        self.setWindowIcon(window_icon(self._settings.load().icon_style))

    def show_and_raise(self) -> None:
        self.showNormal()
        self.raise_()
        self.activateWindow()
        if not self._has_been_shown:
            self._has_been_shown = True
            self.firstShown.emit()

    # -- checking ---------------------------------------------------------- #

    def _on_check_clicked(self) -> None:
        if self._privileged.check_running or self._runner.is_running:
            return
        # Asking for a check is the plain opposite of putting one off. This is
        # the one route that clears it outright, and it covers the window's own
        # button, the tray menu's, and the re-checks that follow an update run
        # or a wait for the lock.
        self._settings.set_deferred_until(None)
        # Started before the UI is touched, so that _set_busy() sees the check
        # as running and greys the banner's button out with the rest.
        self._privileged.run_check(self._settings.load().wait_for_packagekit)
        self._set_busy(True, "Checking for updates…")
        self.stateChanged.emit(TrayState.BUSY, "Checking for updates…")
        self._flatpak.start()

    def _on_wait_for_lock_clicked(self) -> None:
        """Wait for PackageKit to finish, then check again."""
        if self._privileged.check_running or self._runner.is_running:
            return
        self._banner_btn.setEnabled(False)
        self._statusbar("Waiting for PackageKit to finish…")
        self._lock_waiter.start()

    def _on_lock_wait_done(self, free: bool, detail: str) -> None:
        self._statusbar(detail)
        # Re-check either way. helper/check waits again as root anyway, so a
        # timeout here costs nothing, and the fresh status decides whether the
        # button comes back.
        self._on_check_clicked()

    def _on_check_finished(self, ok: bool, message: str) -> None:
        self._set_busy(False, "")
        if not ok:
            self._show_banner(f"Update check failed: {message}")
        else:
            self._hide_banner()
            self._statusbar("Update check complete.")
        # Re-read the status file directly rather than relying on the app's
        # file-system watcher having already fired — don't let a missed or
        # delayed watch event leave the window showing stale data.
        status = read_status()
        if status is not None:
            self.apply_zypper_status(status)
        else:
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

    def _on_update_button_clicked(self) -> None:
        """The window's own update button, whichever it is currently saying.

        "Update now…" still has the question to ask; "Update with X anyway" is
        the answer, so asking again would be asking twice.
        """
        self._on_update_clicked(
            leave_unreachable_out=False if self._banner_offers_leave_out else None
        )

    def _on_defer_clicked(self) -> None:
        """Stop asking about this until tomorrow.

        No confirmation. It changes nothing on the computer, and "Check now" is
        two inches away and undoes it.
        """
        tomorrow = date.today() + timedelta(days=1)
        self._settings.set_deferred_until(tomorrow)
        self._statusbar(f"Put off until {_day(tomorrow)}.")
        self._render()

    def _on_update_without_unreachable(self) -> None:
        """The banner's button: update with the missing sources left out.

        Takes no argument, because which sources are unreachable is worked out
        by the helper, as root, from its own refresh. Nothing here is passed
        down but the decision itself.
        """
        self._on_update_clicked(leave_unreachable_out=True)

    def _on_update_clicked(self, leave_unreachable_out: bool | None = None) -> None:
        """Start an update run.

        *leave_unreachable_out* is None when the user pressed "Update now" and
        has not been asked yet, and True when they arrived by a route that has
        already said what it will do - the banner's button. It is never False
        from a caller; that is only what the question can answer.

        Qt calls this with no arguments (the clicked(bool) signal is adapted to
        the slot's arity), so the default has to be the "ask me" case.
        """
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

        dup_args = dup_args_from_prefs(prefs)

        without_unreachable = False
        if do_zypper and self._status.zypper.failed_repos:
            if leave_unreachable_out is None:
                answer = self._ask_about_unreachable_sources()
                if answer is None:
                    return
                without_unreachable = answer
            else:
                without_unreachable = leave_unreachable_out

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
            # Spell the command out: the free-text options field is stored in
            # the user's config, so this is the only place the exact argument
            # list that will run as root is visible.
            lines.append("")
            lines.append("  $ zypper dup " + " ".join(dup_args))
            if without_unreachable:
                names = [n for _a, n in self._status.zypper.failed_repos]
                lines.append("")
                lines.append(
                    f"  {', '.join(names)} will be left out of this update and "
                    "switched back on when it finishes."
                )

        steps = self._runner.build_queue(
            do_zypper=do_zypper,
            dup_args=dup_args,
            cleanup=prefs.cleanup_after_update,
            wait_for_packagekit=prefs.wait_for_packagekit,
            without_unreachable=without_unreachable,
            do_flatpak_system=do_fp_sys,
            do_flatpak_user=do_fp_user,
        )
        self._terminal_box.show()
        self._update_log_controls()
        self._terminal.append_notice("\n".join(lines))
        self._set_running(True)
        self.stateChanged.emit(TrayState.BUSY, "Installing updates…")
        self._runner.start(steps)
        self._terminal.setFocus()

    def _ask_about_unreachable_sources(self) -> bool | None:
        """Offer to leave the unreachable sources out of this one update.

        Returns True to leave them out, False to try with them left in, and
        None to call the whole thing off.

        Asked here rather than decided in the helper because it is a change to
        the machine, however briefly, and a user who is told what is happening
        can make sense of the terminal underneath. Asked *before* the upgrade
        rather than after it fails because the failure is zypper's paragraph
        about orphaned packages, and by then the person has already been given
        a fright for something that is only somebody else's server being down.
        """
        names = [name for _alias, name in self._status.zypper.failed_repos]
        one = len(names) == 1
        # listed names them, subject opens a sentence about them, pronoun
        # stands in for them mid-sentence.
        listed = names[0] if one else ", ".join(names)
        subject = names[0] if one else "They"
        pronoun = "it" if one else "them"
        verb = "is" if one else "are"

        box = QMessageBox(self)
        box.setIcon(QMessageBox.Question)
        box.setWindowTitle(f"{listed} can’t be reached")
        box.setText(
            f"{listed} can’t be reached at the moment, and the update "
            f"usually won’t go ahead while {pronoun} {verb} switched on."
            "\n\n"
            f"{subject} can be left out of this one update and switched back "
            "on the moment it finishes, so nothing about your computer "
            "changes permanently. Anything you installed from "
            f"{pronoun} stays where it is."
        )
        leave_out = box.addButton(
            "Leave it out just this once" if len(names) == 1
            else "Leave them out just this once",
            QMessageBox.AcceptRole,
        )
        # Worth keeping for the case the banner cannot tell apart: when zypper
        # still has usable details on disk the upgrade works with the source
        # left in, and leaving it out is then needless.
        anyway = box.addButton("Try anyway", QMessageBox.DestructiveRole)
        box.addButton(QMessageBox.Cancel)
        box.setDefaultButton(leave_out)
        box.exec()

        clicked = box.clickedButton()
        if clicked is leave_out:
            return True
        if clicked is anyway:
            return False
        return None

    def _runner_cancel(self) -> None:
        if self._runner.cancel():
            self._statusbar("Stopping after the current step…")
        else:
            self._statusbar("Nothing to cancel.")

    def _on_run_finished(self, ok: bool, message: str) -> None:
        self._set_running(False)
        self._statusbar(message)
        if ok and self._status.zypper.need_reboot:
            self._handle_reboot_needed()
        if not ok:
            self._show_banner(message)
        # A run that failed keeps its log whatever the preference says: the
        # transcript is the only record of what went wrong.
        if ok and self._settings.load().reset_after_update == "on_finish":
            self._reset_log_view()
        # Re-check so the list and counts reflect reality. This puts its own
        # message in the status bar, so it has to come after the reset.
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

        # Read once and passed down, so the headline, the banner and the tray
        # cannot disagree within a single pass.
        deferred = self._settings.deferred_until()

        checked = _relative_time(self._status.generated)
        if z.error:
            # A check that actually failed is not something the user put off,
            # so it still wins the headline.
            self._headline.setText("Could not check for system updates")
        elif deferred is not None:
            self._headline.setText(f"Update check deferred until {_day(deferred)}")
        elif total == 0:
            self._headline.setText("Your system is up to date")
        else:
            self._headline.setText(f"{total} update(s) available")
        self._render_banner(z, total, deferred)

        bits = [f"Last checked {checked}"]
        if z.count and z.download_size:
            bits.append(f"download {human_bytes(z.download_size)}")
        if z.count and z.space_diff:
            bits.append(f"disk {human_bytes(z.space_diff)}")
        self._subline.setText(" · ".join(bits))

        self._update_buttons()
        self._emit_state(deferred)

    def _add_group(self, title: str, rows: list[tuple[str, str, str]]) -> None:
        parent = QTreeWidgetItem([title, "", ""])
        font = parent.font(0)
        font.setBold(True)
        parent.setFont(0, font)
        self._tree.addTopLevelItem(parent)
        for name, change, arch in rows:
            parent.addChild(QTreeWidgetItem([name, change, arch]))

    def _emit_state(self, deferred=None) -> None:
        z = self._status.zypper
        total = z.count + (
            self._status.flatpak.count if self._include_flatpak() else 0
        )
        if self._runner.is_running or self._privileged.check_running:
            return
        if z.error:
            self.stateChanged.emit(TrayState.ERROR, z.error)
        elif deferred is not None:
            # The whole point of putting it off: the icon stops looking like
            # there is something to attend to.
            self.stateChanged.emit(
                TrayState.IDLE, f"Update check deferred until {_day(deferred)}"
            )
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
        # Two buttons offering an update need to say how they differ, or the
        # user is left guessing which one this situation calls for. Neither is
        # greyed out: leaving the source in is not a mistake, and it is the one
        # that works while zypper still has usable details for it on disk.
        if self._banner_offers_leave_out:
            names = [name for _alias, name in z.failed_repos]
            self._btn_update.setText(
                f"Update with {names[0]} anyway"
                if len(names) == 1
                else "Update with them anyway"
            )
        else:
            self._btn_update.setText(_UPDATE_BUTTON_TEXT)

    def _set_busy(self, busy: bool, text: str) -> None:
        self._btn_check.setEnabled(not busy)
        self._progress.setVisible(busy)
        self._update_banner_button()
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
        self._update_banner_button()
        self._update_log_controls()

    def _update_log_controls(self) -> None:
        # isVisibleTo(), not isVisible(): a child of a window that has never
        # been shown reports isVisible() == False, which is wrong both while the
        # app sits in the tray and under the offscreen platform the tests use.
        self._btn_hide_log.setVisible(
            self._terminal_box.isVisibleTo(self._splitter)
            and not self._runner.is_running
        )

    def _reset_log_view(self) -> None:
        """Put the window back into its just-launched state.

        The app hides to the tray rather than quitting, so without this the last
        update's transcript - and the terminal's 20,000-line scrollback - stay
        around for the life of the process. A run still in flight keeps its log
        whichever path got here: it is the only view onto what is happening.
        """
        if self._runner.is_running:
            return
        self._terminal.reset()
        self._terminal_box.hide()
        self.statusBar().clearMessage()
        self._update_log_controls()

    def _statusbar(self, text: str) -> None:
        self.statusBar().showMessage(text, 8000)

    def _show_banner(
        self,
        text: str,
        button: str = "",
        on_click=None,
        alt_button: str = "",
        alt_on_click=None,
        tone: str = "warning",
    ) -> None:
        self._banner_label.setText(text)
        if tone not in _BANNER_STYLES:
            tone = "warning"
        self._banner.setStyleSheet(_BANNER_STYLES[tone])
        self._banner_layout.setContentsMargins(*_BANNER_MARGINS[tone])
        self._banner_action = on_click
        self._banner_btn.setText(button)
        self._banner_btn.setVisible(bool(button))
        self._banner_alt_action = alt_on_click
        self._banner_btn_alt.setText(alt_button)
        self._banner_btn_alt.setVisible(bool(alt_button))
        self._banner.show()
        self._update_banner_button()

    def _hide_banner(self) -> None:
        self._banner_action = None
        self._banner_alt_action = None
        self._banner.hide()

    def _update_banner_button(self) -> None:
        """Grey the banner's button out while the package system is ours.

        Every action it offers ends in a helper that needs zypper's lock, and
        this window is the thing most likely to be holding it: a check starts
        by itself as soon as an update run finishes, and takes half a minute.
        Clicking through that window used to reach zypper and come back with
        its refusal, which the user reads as the app breaking rather than as
        two of its own jobs colliding.
        """
        busy = self._busy_with_the_package_system()
        self._banner_btn.setEnabled(not busy)
        self._banner_btn_alt.setEnabled(not busy)

    def _on_banner_button(self) -> None:
        if self._banner_action is not None:
            self._banner_action()

    def _on_banner_alt_button(self) -> None:
        if self._banner_alt_action is not None:
            self._banner_alt_action()

    # -- banner ------------------------------------------------------------ #

    def _render_banner(self, z, total: int, deferred=None) -> None:
        """Decide what the banner says.

        More than one of these can be true at once - a source that could not be
        reached *and* no snapshot plugin, say - so the messages are joined
        rather than one silently hiding another. The button belongs to the
        first message that wants one, since there is only ever one button.
        """
        parts: list[str] = []
        problem = False
        button = ""
        on_click = None
        alt_button = ""
        alt_on_click = None
        # Read by _update_buttons(), which runs straight after this and gives
        # the window's own button the other half of the choice. False until
        # something below claims it, including on the path that hides the
        # banner entirely.
        self._banner_offers_leave_out = False

        if z.error:
            parts.append(z.error)
            problem = True
            # A lock is the one check failure the user can do something about
            # from here, so it is the one that gets a button.
            if z.locked:
                button = "Wait for it and retry"
                on_click = self._on_wait_for_lock_clicked

        if z.failed_repos and deferred is not None:
            # Put off until tomorrow, so the paragraph and both buttons go and
            # one line stays. Nothing else in this method is suppressed: a
            # failed check, a held lock and a missing snapshot plugin are real
            # problems and are not what the user put off.
            parts.append(_deferred_sources_text(z.failed_repos, deferred))
        elif z.failed_repos:
            # Deliberately does not set `problem`. A source that cannot be
            # reached is not something wrong with this computer, and the button
            # below goes straight past it, so it gets plain text rather than
            # the orange bar.
            parts.append(_missing_sources_text(z.failed_repos, total))
            # The upgrade, with the unreachable sources left out for its
            # duration and put back afterwards. This used to offer to switch
            # one off for good, which was a trap: measured on a real machine,
            # switching off a source that installed packages came from leaves
            # them orphaned, and the next check cannot compute anything at all
            # (zypper raises a solver question per orphan and, non-interactive,
            # gives up). Whatever is offered here has to be reversible, and
            # this is.
            if not button and z.count:
                names = [name for _alias, name in z.failed_repos]
                button = (
                    f"Update without {names[0]}"
                    if len(names) == 1
                    else "Update without them"
                )
                on_click = self._on_update_without_unreachable
                alt_button = "Try again tomorrow"
                alt_on_click = self._on_defer_clicked
                self._banner_offers_leave_out = True

        for alias, name in self._sources_we_switched_off():
            parts.append(
                f"{name} is switched off, so its programs aren't being updated."
            )
            if not button:
                button = f"Switch {name} back on"
                on_click = partial(self._on_switch_source_back_on, alias, name)

        if not z.error and total and not self._status.snapshots_ok and z.count:
            parts.append(
                "snapper-zypp-plugin is not installed — running the upgrade "
                "will NOT create a Btrfs snapshot. Install it with: "
                "zypper install snapper-zypp-plugin"
            )
            problem = True

        if not parts:
            self._hide_banner()
            return
        self._show_banner(
            "\n\n".join(parts),
            button=button,
            on_click=on_click,
            alt_button=alt_button,
            alt_on_click=alt_on_click,
            # One rule: orange for something wrong with this computer, plain
            # text for everything else. A failed check, a held lock and a
            # missing snapshot plugin set `problem`; an unreachable source and
            # a source the user switched off themselves do not.
            tone="warning" if problem else "plain",
        )

    def _sources_we_switched_off(self) -> list[tuple[str, str]]:
        """Sources this app disabled that are still disabled, as (alias, name).

        Only ones this app switched off: most systems have sources disabled on
        purpose (the debug and source repositories, the installation medium),
        and offering to turn those back on would be noise. Aliases that have
        since vanished from zypper's configuration are forgotten, so a deleted
        source cannot leave a permanent note behind.

        Listing costs a `zypper repos` (about 15ms, no network, no root) and
        only happens when the list is non-empty, which for almost everyone
        means never.
        """
        remembered = self._settings.disabled_sources()
        if not remembered:
            return []
        listing = list_repos()
        if listing.error:
            return []
        known = {r.alias for r in listing.repos}
        still_there = [a for a in remembered if a in known]
        if len(still_there) != len(remembered):
            self._settings.set_disabled_sources(still_there)
        out = []
        for alias in still_there:
            repo = listing.by_alias(alias)
            if repo is not None and not repo.enabled:
                out.append((repo.alias, repo.label))
        return out

    # There is deliberately no "switch this source off for good" here any
    # more. It was the banner's button until a real machine showed what it
    # costs: switch off a source that installed packages came from, and every
    # one of them is orphaned, so the next check gets a solver question per
    # orphan, answers none of them, and computes nothing at all. The window
    # then said "Could not check for system updates" with no way back except
    # this method's opposite. Whatever the banner offers has to be reversible,
    # so it now offers the upgrade with the source left out for its duration.
    # _on_switch_source_back_on() stays, for anything an older version of this
    # app switched off.

    def _on_switch_source_back_on(self, alias: str, name: str) -> None:
        if self._busy_with_the_package_system():
            return
        self._change_source(alias, name, enabled=True)

    def _busy_with_the_package_system(self) -> bool:
        """Is one of our own jobs holding zypper's lock?

        What _update_banner_button() greys the button on, and checked again on
        the way in because the button is not the only route here: a click
        already in flight when a check starts would otherwise get through.
        """
        return (
            self._privileged.check_running
            or self._privileged.repos_running
            or self._runner.is_running
        )

    def _change_source(self, alias: str, name: str, enabled: bool) -> None:
        self._banner_btn.setEnabled(False)
        self._statusbar(f"Switching {name} {'back on' if enabled else 'off'}…")

        def done(ok: bool, message: str) -> None:
            self._privileged.reposFinished.disconnect(done)
            if not ok:
                self._update_banner_button()
                self._statusbar(f"Could not change {name}.")
                QMessageBox.warning(
                    self,
                    f"Could not change {name}",
                    f"{name} was left as it was.\n\n{message}",
                )
                return
            remembered = set(self._settings.disabled_sources())
            if enabled:
                remembered.discard(alias)
            else:
                remembered.add(alias)
            self._settings.set_disabled_sources(sorted(remembered))
            self._statusbar(
                f"{name} is now {'switched on' if enabled else 'switched off'}."
            )
            # Check again: the package list and the banner both depend on which
            # sources are in use.
            self._on_check_clicked()

        self._privileged.reposFinished.connect(done)
        if not self._privileged.set_repo_enabled(alias, enabled):
            self._privileged.reposFinished.disconnect(done)
            self._update_banner_button()

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

    # -- snapshots --------------------------------------------------------- #

    def _open_snapshots(self) -> None:
        dlg = SnapshotsDialog(self._privileged, self)
        dlg.exec()

    # -- about ------------------------------------------------------------ #

    def _open_about(self) -> None:
        QMessageBox.about(
            self,
            f"About {APP_NAME}",
            f"<b>{APP_NAME}</b><br>Version {__version__}"
            "<br><br>A tray-based update manager for openSUSE Tumbleweed on KDE."
            '<br><br><a href="https://github.com/Barniclebazil/tumbleweed-updater">'
            "github.com/Barniclebazil/tumbleweed-updater</a>",
        )

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
        elif self._settings.load().reset_after_update == "on_close":
            self._reset_log_view()
        # Hide to tray instead of quitting.
        event.ignore()
        self.hide()
