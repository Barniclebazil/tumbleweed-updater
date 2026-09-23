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
                    │                           helper/repos       switch a source
                    │                              on/off (old button's way back)
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
  palette text colour so it follows the theme, `UPDATES` and `INSTALLING` →
  `#f67400`, which is Breeze's orange and not openSUSE's, chosen to stand out
  in a panel. Orange means one thing, there are updates, so `TrayState.CHECKING`
  has **no icon of its own**: `TrayIcon.set_state()` takes the tooltip and the
  state of the menu's "Update now…" from it and then returns, leaving the mark
  saying whatever it knew a moment ago. A check turning the panel orange every
  few hours was attention asked for with nothing to say. The menu item is still
  greyed for `CHECKING`, since that is what stops the tray starting an update
  while a check holds zypper's lock.
  **Window, task manager, task switcher** (`window_icon(style)`):
  the same thing the tray shows when idle, so it is white on a dark theme and
  dark on a light one. That is only true because `App._refresh_app_icon()`
  rebuilds it on `styleHints().colorSchemeChanged`, as `tray.py` does for
  itself — a palette read once at startup is a colour, not a theme. Verified on
  this machine that the title bar follows it: the session is Wayland, KWin
  advertises `xdg_toplevel_icon_manager_v1` and Qt 6.11 implements it, so
  `setWindowIcon()` is what the decoration draws rather than the desktop file.
  **The title bar cannot draw a half-transparent pixel.** Measured, not
  assumed: three test windows were given the same mark rendered three ways and
  the screenshot's pixels dumped. With ordinary antialiasing every partly
  covered pixel came back *darker than the title bar behind it*, near black,
  and only the fully opaque ones came through white; with the alpha forced to
  nothing or all, the mark drew exactly as designed. That, not the artwork, is
  why three attempts at this icon in a row looked like a smudge. The same
  probe established the size: the decoration asks for **14px** (a coloured
  test pixmap at one size proves which buffer it takes), so `_SIZES` starts at
  12, and without a 14 in it Qt handed over the 16 scaled down, which softened
  everything again.
  So the window icon takes its own drawing where a style ships one:
  `<style>-window.svg` (`_WINDOW_SUFFIX`, `_window_svg()`), rendered with
  `_render(..., title_bar=True)`, which skips `_DEEPEN` and **hardens** every
  pixmap up to `_HARDEN_UPTO` (24) to all-or-nothing alpha at `_HARDEN_AT`.
  Above that it stays smooth, for the task switcher, which composites
  properly. Only `tumbleweed` ships one: two rings that meet, on a **14-unit
  grid** so one unit is one pixel. The crossing is gone deliberately — the
  openSUSE logo and Lucide's `infinity` both draw the mark as a line crossing
  itself, and at this size the two strokes fuse into a white lump.
  `_DEEPEN` (supersample, then lay the result over itself once or twice at
  24px and below) stays for everything else, and is what keeps the tray's own
  artwork from going grey at small sizes. The tray, the settings preview and
  the launcher all still draw `tumbleweed.svg`. The title bar, the task
  manager and the task switcher share the one QIcon from `setWindowIcon()`, so
  they cannot differ.
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
  `wait_for_lock()` waits for two holders and no others. PackageKit, per above;
  and **our own helpers**, via `holder_is_ours()`. That second one exists
  because both helpers shell out, so what lands in the pid file is a plain
  `zypper` and there is nothing in it to say whose — the answer is only in the
  ancestry, so `holder_is_ours()` walks `PPid` (from `/proc/<pid>/status`, not
  `stat`, whose second field can contain spaces) up to four hops looking for a
  helper path as a **whole token** of an ancestor's `cmdline`; a shebang gives
  `/usr/bin/python3\0/usr/libexec/tumbleweed-updater/check\0`, and pkexec and
  the systemd unit both leave the helper as zypper's direct parent, so one hop
  is the real case. A stranger's `zypper` still returns at once, because it can
  hold the lock for many minutes. `describe_holder()` knows the same thing, so
  the terminal says "this application's own update check is using the package
  system" instead of naming a pid that turns out to be ours.
  libzypp **truncates** the pid file rather than unlinking it, so "free" means
  missing, empty, unparseable, or a pid with no `/proc` entry. Match on
  `/proc/<pid>/cmdline`, never `comm`: libzypp renames packagekitd's main
  thread to `Zypp-main`, so `pgrep packagekitd` finds nothing. **Both helpers
  always wait**, and neither takes an option saying otherwise. It used to be a
  Settings toggle and a `--no-wait-for-packagekit` flag on each; there was
  never a case for switching it off (PackageKit's transactions are short, the
  alternative is a hard failure, and nothing is cancelled or killed), and the
  scheduled check could not read the preference anyway, running as root from a
  timer with no session. `helper/check` now refuses *any* argument, which is
  simpler than an allow-list of one.
  `helper/check` puts `still_locked` into `ZypperResult.locked`, which
  `statusfile` carries to the GUI so `MainWindow._render()` can give the orange
  banner its "Wait for it and retry" button (`workers.LockWaiter` keeps the poll
  off the UI thread, and passes `workers.our_helpers()` as `ours=` so a lock
  held by the timer's own check is waited for rather than reported as
  "held by zypper (pid N)"). The retry loop (5 attempts, 10s apart) is the real fix for
  the failure this was built for; not running the notifier at all is the better
  one.
  **Two of our own jobs must never race for the lock**, which they used to.
  Pressing "Update now" during a check started a second job wanting the same
  lock; the check lost, spent 40s on its retries, and replaced the window's
  list of updates with an orange bar naming our own zypper's pid. Three things
  now stop it, one per direction plus one for the damage.
  `MainWindow._update_buttons()` greys the update button on
  `_busy_with_the_package_system()` (check, repos **or** runner) rather than on
  the runner alone, `_set_busy()` calls it so the state changes the moment a
  check starts, and `_on_update_clicked()` asks the same question again on the
  way in, because the button is not the only route (the tray menu, and a click
  already in flight). `helper/run-update` passes the check helper's path as
  `wait_for_lock(ours=…)`, since the systemd timer's check is invisible to the
  GUI. And `helper/check` **exits without writing** when `holder_is_ours()`
  says our own upgrade has the lock: a check during a `dup` tells the user
  nothing, and `MainWindow._on_run_finished()` starts a fresh one the moment
  the upgrade ends. Both helpers list the installed path *and* the bare
  `paths.HELPER_*` constant, since one side may be running from a checkout.
  Residual, accepted: an upgrade asking for the lock while a check is between
  retries still takes it, and that check still fails — which is what the next
  paragraph is for.
  A check that failed **on the lock** no longer throws away the list it could
  not replace. `MainWindow._lost_the_lock()` spots `locked` + an error + no
  packages arriving over a list the window already has, and
  `apply_zypper_status()` keeps the old result with only the error and the flag
  taken from the new one — `generated` deliberately untouched, so "Last checked"
  keeps pointing at the check that produced the list. `_render()` and
  `_emit_state()` therefore say "Could not check for system updates" / emit
  `TrayState.ERROR` only when `z.error and not z.count`. Any other failed check
  still clears the window, because then the app genuinely does not know. The
  banner's wording for a lock is `_locked_text()`, not `z.error`: zypper's own
  sentence is "System management is locked by the application with pid 38917
  (zypper). Close this application before trying again", which breaks every
  house rule at once and names a pid that is usually ours.
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
  real source list before anything acts on it.
  **A source that cannot be reached is got past by the order of two commands,
  not by changing anything.** Measured on this machine against a VLC repo that
  had been down for days: `zypper dup` refuses to run when a repository fails
  to refresh **during its own run** — "dist-upgrade … must not continue if
  enabled repositories fail to refresh … If a failing repository is actually
  not needed, it must be disabled", exit 4 — and it prints that paragraph even
  though the metadata for the missing source is still on disk and perfectly
  usable. So `helper/run-update` refreshes first itself and then, if anything
  came back unreachable, runs `zypper --no-refresh dup` (`_upgrade(...,
  no_refresh=True)`; `--no-refresh` is global, so it goes before `dup`).
  Everything reachable was refreshed seconds earlier, the missing source is
  covered by what is on disk, and there is no failed refresh in the dup's own
  run for it to refuse over. `helper/check` has been proving this works all
  along: `_refresh()` then `sources.check_zypper()`, which is `--no-refresh`,
  is where the window's package list comes from while VLC is unreachable.
  **Switching the unreachable source off is never the answer**, and two
  versions of that idea have now been removed. A source zypper has no usable
  details for is already equivalent to a disabled one, so disabling it cannot
  be what unblocks anything — it can only orphan what was installed from it.
  Measured: switching off the VLC source orphaned all 18 of its packages,
  including VideoLAN's own `libavcodec62`/`libavutil60`/`libswscale9`, which
  openSUSE also ships under a different vendor; the solver then raised a
  question per orphan, `--non-interactive` answered none, and nothing at all
  was computed. That is what `sources.parse_zypper_dup_xml()` turns into
  `NEEDS_A_DECISION` (triggered by a `<prompt>` with no `<install-summary>`:
  the element name is not translated, its text is). So neither
  `run-update --without-unreachable` nor the older "switch it off for good"
  button exists any more, and nothing writes to
  `SettingsStore.disabled_sources()` — that list and
  `_on_switch_source_back_on()` are kept only as the way back for anyone who
  pressed the old button. `_split_own_options()` strips this helper's own flags
  off the front, and only off the front, so a later `--cleanup` is still
  refused by `dupargs`; `--without-unreachable` now fails that allow-list like
  any other unknown option.
  `_stopped_by()` covers the one case left: the dup failed even with
  `--no-refresh`, which means the details on disk have gone stale too and no
  button will fix it, so it names the source and says it needs replacing or
  removing.
  `helper/check` records the failures in `ZypperResult.failed_repos` even when
  the dry run still found packages.
  `MainWindow._render_banner()` turns the failures into plain
  language: "software source", never "repository", and the display name, never
  the alias. **It offers nothing to press** beyond the deferral, because there
  is nothing left to decide. `SettingsStore.note_unreachable_sources()` /
  `unreachable_since()` remember the day each source first failed (written from
  `apply_zypper_status()`, forgotten the moment a check reaches it again), and
  past `_STALE_SOURCE_DAYS` = 3 the last sentence of `_missing_sources_text()`
  stops saying "worth trying again tomorrow" and starts saying how long the
  source has been gone and that it wants replacing or removing in YaST →
  Software Repositories. When the check worked nothing out *and* a source was
  unreachable *and* the lock was not the problem (`stuck` in `_render_banner()`),
  `_stuck_sources_text()` replaces the raw error with the same advice — that is
  the situation the update genuinely cannot get itself past.
  The banner's second button, **"Try again tomorrow"** (`_banner_btn_alt`), is
  now its only one: the source is usually somebody else's server having a bad
  afternoon and there is nothing useful to do until it is back. It stores
  tomorrow's date in `SettingsStore.set_deferred_until()`, and
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
  It is the one button `_update_banner_button()` does **not** grey out while
  the package system is busy, since all it writes is a date in this user's
  preferences.
  The banner itself is **not orange** for an unreachable source
  (`_BANNER_STYLES["plain"]`): one rule, orange for something wrong with this
  computer, the window's own text for everything else. `_render_banner()` sets
  `problem` for a failed check (including the stuck case above), a held lock
  and a missing snapshot plugin, and deliberately not for an unreachable source
  the update can get past, or a source the user switched off themselves.
  **Failures of our own jobs are state, not a one-off banner.** Because
  `_render_banner()` rebuilds the whole banner from the status on every
  render, a message set directly with `_show_banner()` is wiped by the next
  render — which is how a failed pkexec check lost its message on the very next
  line, and a failed run lost its own when the re-check after it came back.
  So `_check_failure` (cleared by the next successful check) and `_run_failure`
  (cleared when a run starts or the log is reset) live on the window and
  `_render_banner()` puts them first, orange. `_run_failure` also stops
  `closeEvent()` clearing the log on "on_close", since a failed run keeps its
  log whatever `RESET_AFTER_UPDATE` says.
  The primary banner button — now only "Wait for it and retry" and "Switch X
  back on" — is greyed out (`MainWindow._update_banner_button()`) while a
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
  `exec.path` annotation pins the program, never its argv. `check` used to be
  the one helper that changed a source without its own polkit action, putting
  back one an interrupted `run-update` had left off; no helper switches a
  source off any more, so nothing changes a source outside `helper/repos`.
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
rolls the `.tar.xz`, runs `rpmbuild -bb`, and copies the result to `dist/`;
`packaging/make-repo.sh` (called by `release.yml`) turns `dist/*.rpm` into the
zypper repository published on GitHub Pages, signed when `GPG_PRIVATE_KEY` is set.
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
