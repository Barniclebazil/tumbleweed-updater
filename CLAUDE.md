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
runner.py  command queue
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
  `settings.py` and `helper/set-interval`.
* **`terminal.py`** is a real terminal: `pty_session.py` runs the child on a PTY
  wired to a `QSocketNotifier`; `_Screen` subclasses `pyte.Screen` to keep a
  scrollback deque. `runner.py` drives a queue of steps (zypper dup → flatpak
  system → flatpak user) through a single `TerminalWidget`, stopping on the
  first non-zero exit.
* **`app.py`** owns the `QApplication`, single-instance `QLocalServer`, tray,
  window, and `PrivilegedRunner`. `MainWindow.stateChanged` → `TrayIcon`.

### Privilege model (important)

* `zypper dup --dry-run` **requires root even for a dry run**, so the GUI can
  never compute the update list itself — that is `helper/check`'s job.
* Elevation is `pkexec <helper>` matched to a **custom polkit action** by the
  `org.freedesktop.policykit.exec.path` annotation in
  `data/org.opensuse.tumbleweedupdater.policy`. `check` is passwordless for an
  active local session (`<allow_active>yes</allow_active>`, it changes nothing);
  `run-update` and `set-interval` need admin auth (`auth_admin_keep`).
* `pkexec` refuses to run a helper that is not **root-owned and not
  world-writable**. That means the `pkexec` paths only work after
  `make install`; from a bare checkout the UI runs but "Check now" / "Update
  now" will fail. `paths.resolve_helper()` prefers the installed copy and falls
  back to `helper/` for the UI-only case.
* Btrfs snapshots are **not** managed here — `zypper dup` triggers
  `snapper-zypp-plugin` itself. `helper/check` only reports whether that plugin
  is installed; the window shows a warning banner if it is not.

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
  `intervals.py`, `paths.py` must stay Qt-free (imported by the root helpers).
* User preferences → `settings.py` (`Prefs` dataclass + `QSettings`). Anything
  system-wide (the timer cadence) is applied by a helper, never written directly
  by the GUI. `MainWindow.open_settings()` re-reads `Prefs` after the dialog
  closes and pushes terminal appearance into `TerminalWidget.apply_appearance()`
  (which reflows the pyte grid for the new font metrics).
