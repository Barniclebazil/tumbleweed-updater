# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this is

A system-tray update manager for openSUSE Tumbleweed on KDE Plasma (a
`mintupdate`-style tool). Python 3 + PySide6 (Qt 6) for the GUI, `pyte` for the
embedded terminal emulator. No compiled code.

## Commands

```sh
make test                       # full pytest suite (headless, offscreen Qt)
python3 -m pytest -q tests/test_terminal.py::test_pty_runs_and_reports_exit   # one test
python3 -m tumbleweed_updater   # run from the checkout  (== make run)
make install / make uninstall   # install to PREFIX (default /usr); needs root
sudo sh packaging/install.sh    # same, for systems without make (DESTDIR= to stage)
make lint                       # pyflakes
```

Tests set `QT_QPA_PLATFORM=offscreen` via `tests/conftest.py`. There is no
network in tests; the zypper/flatpak parsers are exercised with fixtures.

### Running against a pip-installed PySide6

The system package is `python3-pyside6`; a venv should be created with
`--system-site-packages` so it is picked up. If PySide6 is installed from pip
instead, its wheel expects a standalone `libgthread-2.0.so.0` which modern glib
(≥ 2.80) has folded into `libglib`. Work around it with a symlink on
`LD_LIBRARY_PATH`:

```sh
ln -s /usr/lib64/libglib-2.0.so.0 /some/dir/libgthread-2.0.so.0
LD_LIBRARY_PATH=/some/dir python3 -m pytest -q
```

## Architecture

Two cooperating halves that talk through **one JSON file**, not D-Bus:

```
GUI (user)                          privileged helpers (root, via pkexec)
─────────────────────────────       ─────────────────────────────────────
tray.py   TrayIcon                  helper/check       zypper refresh + dry-run
mainwindow.py  window + list        helper/run-update  interactive `zypper dup`
terminal.py + pty_session.py        helper/set-interval systemd timer drop-in
runner.py  command queue            helper/snapshots   list/compare via snapper
                    │                           helper/snapshots-manage
                    │                              rollback/delete via snapper
                    │  writes                    │
                    └── reads ── /run/tumbleweed-updater/status.json ──┘
```

* **`statusfile.py`** is the schema/contract between the two halves. The root
  `helper/check` writes it; `app.py` watches it with `QFileSystemWatcher` and
  feeds it to the window via `MainWindow.apply_zypper_status()`.
* **`sources.py`** is pure/stdlib-only (no Qt) so the root helpers can import it.
  `parse_zypper_dup_xml()` parses `zypper --xmlout dup --dry-run` per
  `/usr/share/zypper/xml/xmlout.rnc`; the solvable element uses `kind=` (not
  `type=`) and `edition`/`edition-old`.
* **`intervals.py`** is likewise Qt-free — the label→`OnCalendar=` map shared by
  `settings.py` and `helper/set-interval`. **`dupargs.py`** is the same idea for
  the other direction: the allow-list of `zypper dup` options that
  `helper/run-update` will accept, shared with `settingsdialog.py` so the dialog
  can reject an option before it is saved rather than at update time.
* **`icons.py`** renders each tray/window icon from one monochrome SVG in
  `data/icons/styles/<name>.svg` (`currentColor` stroke). **Tray**: idle →
  palette text colour so it follows the theme, "updates" → `#f67400`, which is
  Breeze's orange and not openSUSE's, chosen to stand out in a panel.
  **Window, task manager, task switcher** (`window_icon()`): openSUSE green
  `#73ba25`. **Window, task manager, task switcher** (`window_icon(style)`):
  the same thing the tray shows when idle, so it is white on a dark theme and
  dark on a light one. That is only true because `App._refresh_app_icon()`
  rebuilds it on `styleHints().colorSchemeChanged`, as `tray.py` does for
  itself — a palette read once at startup is a colour, not a theme. Verified on
  this machine that the title bar follows it: the session is Wayland, KWin
  advertises `xdg_toplevel_icon_manager_v1` and Qt 6.11 implements it, so
  `setWindowIcon()` is what the decoration draws rather than the desktop file.
  The **launcher entry** is the exception, `data/icons/tumbleweed-updater.svg`,
  which carries a literal `#73ba25` rather than `currentColor`: the launcher is
  handed that file as it is, there is no runtime to tint it in, and
  `currentColor` with nothing to inherit from resolves to black, which is what
  once put a black mark in Kickoff. Style list is `settings.ICON_STYLES`.
  Changing it in the dialog → `MainWindow.settingsApplied` → `app` →
  `tray.reload()` + `MainWindow.reload_icon()`.
* **Update options** — `settings.dup_args_from_prefs()` turns the "Update
  behaviour" toggles into `zypper dup` args (`-y --auto-agree-with-licenses`,
  `--allow-vendor-change`, `--download in-advance`) plus the free-text field,
  de-duplicated. `helper/run-update [--cleanup] <args…>` checks every option
  against `dupargs.py` first (polkit matches only the helper's path, never its
  arguments, and the update action's authorisation stays cached for minutes),
  runs `zypper clean` after on `--cleanup`, and maps zypper exit **102/103**
  (reboot/restart needed) to success. `runner.py` also treats 0/102/103 as OK.
  `MainWindow._on_update_clicked()` prints the exact argv into the terminal
  before starting, since the free-text options field lives in the user's config.
* **`terminal.py`** is a real terminal: `pty_session.py` runs the child on a PTY
  wired to a `QSocketNotifier`; `_Screen` subclasses `pyte.Screen` to keep a
  scrollback deque. `runner.py` drives a queue of steps (zypper dup → flatpak
  system → flatpak user) through a single `TerminalWidget`, stopping on the
  first non-zero exit.
* **`app.py`** owns the `QApplication`, single-instance `QLocalServer`, tray,
  window, and `PrivilegedRunner`. `MainWindow.stateChanged` → `TrayIcon`.
* **`packagekit.py`** (Qt-free) reads `/run/zypp.pid` and waits on it. Measured
  behaviour, not assumed: packagekitd takes the lock when a transaction starts
  and releases it the instant that transaction ends (15-30s for a refresh); an
  idle daemon does **not** hold it, even though it lives on for
  `ShutdownTimeout`. So **asking it to quit is useless and is not implemented**
  — `SuggestDaemonQuit` returns success immediately but is ignored while any
  transaction is listed, which is exactly when the lock is held; and
  `Transaction.Cancel` needs `cancel-foreign`, which is `auth_admin_keep` even
  for an active session, so it would raise a password prompt to save seconds.
  `wait_for_lock()` waits, and only for PackageKit: another `zypper` can hold
  the lock for many minutes, so that case returns at once naming the holder.
  libzypp **truncates** the pid file rather than unlinking it, so "free" means
  missing, empty, unparseable, or a pid with no `/proc` entry. Match on
  `/proc/<pid>/cmdline`, never `comm`: libzypp renames packagekitd's main
  thread to `Zypp-main`, so `pgrep packagekitd` finds nothing. Both helpers take
  `--no-wait-for-packagekit` (exact string match, since polkit pins the path but
  not argv); the systemd timer passes nothing, so the scheduled check always
  waits, which is why the Settings toggle only governs GUI-initiated runs.
  `helper/check` puts `still_locked` into `ZypperResult.locked`, which
  `statusfile` carries to the GUI so `MainWindow._render()` can give the orange
  banner its "Wait for it and retry" button (`workers.LockWaiter` keeps the poll
  off the UI thread). The retry loop (5 attempts, 10s apart) is the real fix for
  the failure this was built for; not running the notifier at all is the better
  one.
* **`autostart.py`** (Qt-free) owns both this app's own XDG autostart entry and
  the `Hidden=true` override that switches off Plasma's Discover update notifier
  — the only thing on a stock Plasma install that wakes PackageKit. `app.py`
  asks about it once (`_should_ask_about_notifier`, gated on
  `MainWindow.firstShown` so a `--tray` start does not pop a modal over an empty
  desktop) and `settingsdialog.py` exposes it; the tickbox reads the override
  **from disk**, not `QSettings`, since the user can also flip it in System
  Settings. `notifier_pids()` matches the basename of `argv[0]` for our own uid
  only: `pgrep -f` would match an editor with the source open, and
  `/proc/<pid>/comm` truncates to 15 characters. SIGTERM only — Plasma's
  generated unit has `Restart=no`, and the override covers the next login anyway.
  Masking `packagekit.service` was considered and rejected: it breaks Discover's
  install/remove/repositories and `packagekit-offline-update.service`.
* **`repos.py`** (Qt-free) is zypper's software sources: `list_repos()` parses
  `zypper --xmlout repos --details` (which needs **no root**, so the GUI calls it
  directly), `set_enabled()` wraps `zypper modifyrepo --disable/--enable`, and
  `failed_aliases()` mines a failed `zypper refresh` for the sources it could
  not reach. There is no machine-readable refresh output, so that last one
  matches the `[alias|url]` token zypper prints, which is the same in every
  language — the "Skipping repository 'VLC'" line carries the translated
  *display name*, not the alias. Every alias it yields is checked against the
  real source list before anything acts on it. **A source that cannot be
  reached does not stop `helper/run-update`**: it treats a failed refresh as
  fatal only for exit 7 (lock) and runs the dup regardless. Whether the *dup*
  then runs is zypper's call, and measured behaviour splits in two: with usable
  metadata for the missing source still on disk it upgrades normally, and with
  none it refuses outright (exit 4, "dist-upgrade … must not continue if
  enabled repositories fail to refresh … If a failing repository is actually
  not needed, it must be disabled"). `--no-refresh` does not get round it. So
  nothing here promises the other updates will install: `_stopped_by()` turns
  that refusal into one plain line naming the source and the button, and the
  banner says "were checked as usual", not "can still be installed". It also
  **no longer offers to switch a source off for good**, which was a trap: on a
  real machine, switching off the source 14 installed packages came from left
  every one of them orphaned, so the next `dup --dry-run` got a solver question
  per orphan, answered none (it is `--non-interactive`), and computed nothing
  at all — the window read "Could not check for system updates" with no route
  back but the opposite button. Whatever the banner offers has to be
  reversible, so it offers the upgrade instead.
  **`run-update --without-unreachable`** takes zypper's advice for the length
  of one upgrade: switch the source off, dup, switch it back on
  (`_upgrade_without()`). `MainWindow._ask_about_unreachable_sources()` offers
  it from "Update now" — leave it out just this once / try anyway / cancel —
  and the banner's own button (`_on_update_without_unreachable()`) takes the
  same route without asking, its label having said so already. The GUI passes
  only the flag, never an alias: which sources are
  unreachable is worked out by the helper, as root, from its own refresh. Two
  things guard it. A note under `/var/lib/tumbleweed-updater/`
  (`repos.remember_to_restore()`, written before anything is touched) that
  `helper/check` acts on at the start of its next run, for the endings the
  helper does not live to see; `/run` would be wrong here, since the point is
  to survive a reboot. And a dry run, because leaving a source out orphans
  everything installed from it and `man zypper` is explicit that dist-upgrade
  "removes orphaned packages if they prevent the upgrade of wanted packages" —
  without asking, since the default options include `-y`. So `_extra_removals()`
  compares the plan against the one the user was shown (the status file) and
  stops if it has grown, or if the second dry run could not answer — which on
  this machine is the orphaned-package case above, and
  `sources.parse_zypper_dup_xml()` has already turned that into a sentence
  (`_NEEDS_A_DECISION`, triggered by a `<prompt>` with no `<install-summary>`:
  the element name is not translated, its text is). `_split_own_options()` strips this helper's own flags
  off the front, and only off the front, so a later `--cleanup` is still
  refused by `dupargs`.
  `helper/check` records the failures in `ZypperResult.failed_repos` even when
  the dry run still found packages (it used to throw the message away in
  exactly that case) — and note that its dry run uses `--no-refresh`, so it can
  list packages that the real dup will then refuse to install.
  `MainWindow._render_banner()` turns the failures into plain
  language: "software source", never "repository", and the display name, never
  the alias. The banner's one button switches the source off via
  `helper/repos`; `SettingsStore.disabled_sources()` remembers which sources
  *this app* switched off, so the offer to switch one back on never appears for
  the debug/source/installation-medium repos every system has disabled anyway.
  Nothing writes to that list any more (see above) — it is kept for anyone who
  pressed the old button, since `_on_switch_source_back_on()` is their whole
  way back. When the banner offers "Update without X" it sets
  `_banner_offers_leave_out`, and `_update_buttons()` relabels the window's own
  button "Update with X anyway" (which then runs without asking, since the
  label already answered). Neither is greyed out: keeping the source in is the
  route that works while zypper still has usable details for it on disk, and
  the app cannot tell in advance which case it is in.
  `_ask_about_unreachable_sources()` still runs when the banner's one button
  went to something else, a held lock in particular. Beside it sits a second
  banner button, **"Try again tomorrow"** (`_banner_btn_alt`), for the case the
  banner's own last sentence recommends: the source is usually somebody else's
  server having a bad afternoon and there is nothing useful to do until it is
  back. It stores tomorrow's date in `SettingsStore.set_deferred_until()`, and
  while that is in force the headline reads "Update check deferred until
  dd/mm/yyyy", `_emit_state()` emits `TrayState.IDLE` so the icon stops looking
  like there is something to attend to, `app._should_notify()` stays quiet, and
  the banner shrinks to one line with no buttons. Three things end it: "Check
  now" (`_on_check_clicked()` clears it, which covers the tray menu and the
  re-checks after a run), a check that comes back with no error and no failed
  sources (`apply_zypper_status()` — nothing to hide from any more), and the
  date arriving, which `deferred_until()` notices and tidies away on the next
  read. Everything else the banner says is unaffected: a failed check, a held
  lock and a missing snapshot plugin are real problems, not what was put off.
  The banner itself is **not orange** for this (`_BANNER_STYLES["plain"]`):
  one rule now, orange for something wrong with this computer, the window's own
  text for everything else. `_render_banner()` sets `problem` for a failed
  check, a held lock and a missing snapshot plugin, and deliberately not for an
  unreachable source or a source the user switched off themselves.
  That button is greyed out (`MainWindow._update_banner_button()`) while a
  check, an update or another source change is running: a check starts by
  itself as soon as an update finishes and holds zypp's lock for half a minute,
  and `zypper modifyrepo` arriving in that window came back with zypper's own
  "Close this application before trying again", which reads as the app being
  broken. `repos.set_enabled()` replaces that message for exit 7 anyway, since
  the systemd timer's check can hold the lock without the GUI knowing.
  `run-update` captures the refresh output through a **PTY**, not a pipe: on a
  pipe zypper drops its colour and a prompt with no trailing newline (the GPG
  key question) would sit unseen while the app looked hung.
* **`snapshots.py`** is pure/stdlib-only (no Qt), parsing `snapper --jsonout
  list` (which nests snapshots under the config name, e.g. `{"root": [...]}`,
  and uses hyphenated keys like `pre-number`) and `snapper status <n1>..<n2>`
  (plain `"<code> <path>"` lines — `status` has no JSON mode). The helpers are
  the only way to reach it: even listing needs root, since `snapper list`
  refuses to run as a normal user. Reading (`helper/snapshots`: list, status)
  and changing (`helper/snapshots-manage`: rollback, delete) are deliberately
  **two helpers under two polkit actions** — see the privilege model below.
  `snapshotsdialog.py` (Menu → Snapshots…) drives both on demand via
  `PrivilegedRunner.run_snapshots()`/`snapshotsFinished`, which routes to the
  right helper by the action word — there is no background polling or
  status-file entry for this, unlike `check`.

### Privilege model (important)

* `zypper dup --dry-run` **requires root even for a dry run**, so the GUI can
  never compute the update list itself — that is `helper/check`'s job.
* Elevation is `pkexec <helper>` matched to a **custom polkit action** by the
  `org.freedesktop.policykit.exec.path` annotation in
  `data/org.opensuse.tumbleweedupdater.policy`. `check` is passwordless for an
  active local session (`<allow_active>yes</allow_active>`, it changes nothing);
  `run-update`, `set-interval` and `snapshots` need admin auth
  (`auth_admin_keep`) — `snapshots` needs it even just to list, since
  `snapper list` itself refuses to run as a normal user. `snapshots-manage`
  (rollback/delete) is plain `auth_admin` on purpose: `_keep` caches the
  authorisation for minutes, and the cached listing must not be reusable to
  destroy a snapshot. For the same reason the helpers validate their own
  arguments (`set-interval` against `intervals.py`, `run-update` against
  `dupargs.py`, both snapshot helpers against `int()`): the
  `exec.path` annotation pins the program, never its argv. `check` is also the
  only helper that changes a source without its own polkit action — it puts
  back one an interrupted `run-update` left off — which is safe because it can
  only ever *enable*, only from a root-owned note under `/var/lib`, and only
  for an alias that is still in the real source list.
* `snapshots-manage` and `repos` are both plain `auth_admin`. For `repos` the
  reason is the `check` action above: it costs an active local session no
  authentication at all, so a source change must not be able to ride anything
  cached. Reading the source list is not a helper at all — `zypper repos` works
  unprivileged.
* `pkexec` refuses to run a helper that is not **root-owned and not
  world-writable**. That means the `pkexec` paths only work after
  `make install`; from a bare checkout the UI runs but "Check now" / "Update
  now" / "Snapshots…" will fail. `paths.resolve_helper()` prefers the
  installed copy and falls back to `helper/` for the UI-only case.
* The pre/post Btrfs snapshots around `zypper dup` itself are **not** taken
  here — `zypper dup` triggers `snapper-zypp-plugin` for those. `helper/check`
  only reports whether that plugin is installed; the window shows a warning
  banner if it is not. Browsing/rolling back/deleting the resulting snapshots
  *is* handled here, via `helper/snapshots` (see `snapshots.py` above).

### Packaging

`packaging/install.sh` is the single source of truth for install layout;
`Makefile` mirrors it and `packaging/tumbleweed-updater.spec`'s `%install`
just calls it (`DESTDIR=… PREFIX=… SITELIB=… sh packaging/install.sh`). All
three plus `paths.py` must agree on every location. `packaging/build-rpm.sh`
rolls the `.tar.xz`, runs `rpmbuild -bb`, and copies the result to `dist/`.
`packaging/release.sh <version> <note>` bumps the version in all three places
(`__init__.py`, `pyproject.toml`, spec `Version:`) + changelog, then commits,
tags `v<version>` and pushes — the `release.yml` workflow does the rest. Layout: Python package →
`%{python3_sitelib}`; helpers → `/usr/libexec/tumbleweed-updater/`; plus the
polkit policy, the systemd `check` service/timer + `system-preset` (enables the
timer on install), hicolor SVG icons, a second icon copy under
`/usr/share/tumbleweed-updater/` (found by `resources.py`), and the `.desktop`
file. Dependencies (`python3-pyside6`, `python3-pyte`, `polkit`, …) are declared
as RPM `Requires:` — they are not auto-detected since nothing ships dist-info.

## Conventions

* GUI modules may import Qt freely; `sources.py`, `statusfile.py`,
  `intervals.py`, `dupargs.py`, `paths.py`, `snapshots.py`, `packagekit.py`,
  `autostart.py`, `repos.py` must stay Qt-free (imported by the root helpers,
  or by both the dialog and `app.py`).
* Anything the user reads about a failure is written for someone who has never
  heard of a repository: no "repository", "metadata", "refresh" or exit codes
  in a banner or a dialog. zypper's own words stay untouched in the terminal
  underneath, which is the record of what actually happened.
* User preferences → `settings.py` (`Prefs` dataclass + `QSettings`). Anything
  system-wide (the timer cadence) is applied by a helper, never written directly
  by the GUI. `MainWindow.open_settings()` re-reads `Prefs` after the dialog
  closes and pushes terminal appearance into `TerminalWidget.apply_appearance()`
  (which reflows the pyte grid for the new font metrics) and into the update
  list's font/palette via `MainWindow._apply_list_appearance()`, so the list
  matches the terminal's configured font and colours.
