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
  `data/icons/styles/<name>.svg` (`currentColor` stroke): idle → palette text
  colour, "updates" → openSUSE orange. Style list is `settings.ICON_STYLES`.
  Changing it in the dialog → `MainWindow.settingsApplied` → `app` → `tray.reload()`.
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
  `exec.path` annotation pins the program, never its argv.
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
  `autostart.py` must stay Qt-free (imported by the root helpers, or by both
  the dialog and `app.py`).
* User preferences → `settings.py` (`Prefs` dataclass + `QSettings`). Anything
  system-wide (the timer cadence) is applied by a helper, never written directly
  by the GUI. `MainWindow.open_settings()` re-reads `Prefs` after the dialog
  closes and pushes terminal appearance into `TerminalWidget.apply_appearance()`
  (which reflows the pyte grid for the new font metrics) and into the update
  list's font/palette via `MainWindow._apply_list_appearance()`, so the list
  matches the terminal's configured font and colours.
