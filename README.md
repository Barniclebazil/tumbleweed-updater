# Tumbleweed Updater

A system-tray update manager for openSUSE Tumbleweed on KDE Plasma.

Features:

1. Lives in the system tray. The icon follows the Plasma light/dark theme while
   the system is up to date and turns orange when updates are waiting.
2. Shows a window listing the pending `zypper dup` and Flatpak updates.
3. Runs the upgrade in an embedded terminal, so you answer `zypper`'s prompts
   (the resolver's "Choose from above solutions", vendor changes, and so on) as
   if you had run `zypper dup` yourself.
4. Takes Btrfs snapshots through `zypper` itself via `snapper-zypp-plugin`, the
   same pre/post snapshots a manual `sudo zypper dup` produces. The app warns if
   that plugin is missing.
5. Checks for updates in the background with a systemd timer. The cadence
   (hourly to weekly, or manual) is set from the app's settings. On a laptop
   the scheduled check is skipped while running on battery.
6. Lets you browse the Btrfs snapshots snapper has taken, see what changed
   in a pre/post pair, roll back to one, or delete one (Menu → Snapshots…).
7. Returns to a clean state once an update is done. Closing the window to the
   tray clears the terminal and collapses it, so the next time you open the
   window you are not still looking at the last update's output. When that
   happens is configurable in the settings, and you can clear the log yourself
   at any time with the "Hide log" button or the terminal's right-click menu.
8. Copes with PackageKit. PackageKit holds the system package lock while it
   runs, which is what makes `zypper` fail with "System management is locked".
   The app waits for it instead of failing, and offers to switch off Plasma's
   own update notifier, which is the thing that keeps waking it. Discover is
   not affected either way.
9. Copes with a software source it cannot reach. A third-party repository whose
   server is down no longer stops the whole upgrade. `zypper dup` refuses to
   run when a repository fails to refresh during its own run, so the helper
   refreshes everything itself first and then runs the upgrade with
   `--no-refresh`: everything reachable is fresh from a moment ago, and the
   missing source is covered by the metadata already on disk. Nothing is
   disabled and nothing has to be put back. The window names the source in
   plain words rather than repeating `zypper`'s error, and offers to stop
   asking until tomorrow. If the source stays away long enough that the
   metadata on disk is no use either, the window says how long it has been
   gone and that it needs replacing or removing.

## PackageKit and Plasma's update notifier

`zypper` needs the libzypp lock, and only one process may hold it. On a stock
Plasma install the usual holder is `packagekitd`, which nothing starts
deliberately: `packagekit.service` is D-Bus activated, so anything at all asking
PackageKit a question launches it as root. It takes the lock when a job starts
and releases it the moment that job finishes. A repository refresh has been
measured here at anything from 15 seconds to over two minutes, depending on how
much metadata it fetches. The app handles this in two ways.

1. It waits rather than failing. Before each check and each upgrade it looks at
   `/run/zypp.pid`, and if PackageKit is the holder it waits for it to finish.
   This turns many failures into delays, though not all of them: a long refresh
   can outlast the wait, and the check then reports the lock as it did before.
   Nothing is cancelled, stopped or killed: PackageKit is left alone to complete
   its job. It also waits for this app's own background check, which takes the
   same lock through `zypper` and is the other thing likely to be holding it.
   It does not wait for anybody else: if your own `zypper` in a terminal has the
   lock the app says so straight away rather than sitting behind something that
   may run for an hour. There is no setting for any of this — waiting is simply
   what it does.
2. The first time the app runs it offers to switch off Plasma's own update
   notifier, which is the only thing on a stock install that keeps waking
   PackageKit in the first place. This app already reports the same `zypper` and
   Flatpak updates. The setting lives under Settings → "Turn off Plasma's own
   update notifier" and writes
   `~/.config/autostart/org.kde.discover.notifier.desktop` with `Hidden=true`,
   so to undo it by hand:

   ```sh
   rm ~/.config/autostart/org.kde.discover.notifier.desktop
   ```

   That takes effect at the next login. **Discover itself keeps working
   normally.** Installing, removing and managing repositories are all
   unaffected. What stops is Plasma's passive notification that updates exist.

Asking PackageKit to quit is deliberately not attempted, because it does not
work. `org.freedesktop.PackageKit.SuggestDaemonQuit` reports success but is
ignored while any job is running, which is exactly and only when the lock is
held. Cancelling the job outright would work, but needs an admin password every
time. That is why item 2 above, and not item 1, is the real fix.

## Screenshots

1. The update list, showing pending `zypper dup` and Flatpak updates with
   the version change and architecture for each package.

   ![Update list](screenshots/update-list.png)

2. Settings: check interval, update behaviour, tray icon style and terminal
   appearance.

   ![Settings](screenshots/settings.png)

3. The embedded terminal running `zypper dup`, where you answer its prompts
   directly.

   ![Terminal](screenshots/terminal.png)

## Requirements

`python3-pyside6`, `python3-pyte`, `zypper`, `polkit` (with a polkit agent such
as `polkit-kde-agent-6`), optionally `flatpak`, and `snapper-zypp-plugin` for
snapshots. The RPM installed below declares all of these, so `zypper` pulls
them in automatically.

## Install

```sh
sudo zypper addrepo -f \
  https://barniclebazil.github.io/tumbleweed-updater/tumbleweed-updater.repo
sudo zypper install tumbleweed-updater
```

Once installed, the background-check timer is enabled. Launch "Tumbleweed
Updater" from the application menu the first time. To have it start in the
system tray at every login, tick "Start automatically at login" in Settings.

## Run

```sh
tumbleweed-updater          # open the window
tumbleweed-updater --tray   # start hidden in the tray (used for autostart)
tumbleweed-updater --update # open the window and start the update
```

## Icon credits

The "Tumbleweed" and "openSUSE" tray icon styles are the openSUSE project's own
logos, recoloured to a single `currentColor` so they follow the Plasma theme:

1. `data/icons/styles/tumbleweed.svg` — from the openSUSE wiki,
   [File:Tumbleweed-logo.svg](https://en.opensuse.org/File:Tumbleweed-logo.svg).
2. `data/icons/styles/opensuse.svg` — from the openSUSE artwork repository,
   [logos/buttons/button-colour-transparent.svg](https://github.com/openSUSE/artwork/blob/master/logos/buttons/button-colour-transparent.svg).

Both marks are trademarks of SUSE LLC and are used here only to identify the
distribution this tool updates.

The window's own icon, `data/icons/styles/tumbleweed-window.svg`, is drawn
here rather than taken from anywhere: a title bar asks for 14 pixels, and
neither logo above is legible that small.
