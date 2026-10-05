---
name: run-app
description: Launch Tumbleweed Updater from this checkout on the live KDE Wayland session, alongside any installed copy, and take screenshots of it. Use to run, start or screenshot the app, or to check a GUI change by eye (icons, banners, layout, dark and light themes) rather than only through the offscreen tests.
argument-hint: "[--tray]"
---

# Run the app from the checkout

The tests run Qt offscreen, so they cannot show what the window looks like.
These steps run the checkout's GUI on the real session and take screenshots
that you can Read.

## 1. Know what you are testing

1. **The GUI comes from the checkout. The helpers do not.**
   `paths.resolve_helper()` prefers the installed copy in
   `/usr/libexec/tumbleweed-updater/`, and pkexec refuses a helper that is not
   root-owned. So "Check now", "Update now" and "Snapshots…" run the
   *installed* helpers. A change under `helper/`, or in a Qt-free module a
   helper imports, is only exercised after an install. You may run it
   yourself when the user wants the change installed: `sudo -A make install`
   (with `SUDO_ASKPASS` set, see below) or the `pkexec` form, either of which
   asks the user for the password in a pop-up. Never try plain `sudo` or `!
   sudo`: there is no terminal to read the password from, so it fails. Do not
   install while the installed copy is running `zypper dup`
   (`pgrep -a zypper` first), and restart the tray copy afterwards so it runs
   the new code.

   ```sh
   sudo -A make install
   # or, if SUDO_ASKPASS is not set:
   pkexec /bin/sh -c "cd '$PWD' && sh packaging/install.sh"
   ```
2. An installed copy is usually already running from autostart
   (`/usr/bin/tumbleweed-updater --tray`). It holds the single-instance socket
   `$XDG_RUNTIME_DIR/tumbleweed-updater.instance`, and a plain
   `python3 -m tumbleweed_updater` would hand over to it and exit. **Do not
   kill the installed copy to make room for the checkout.** If it is running
   an update, its `zypper dup` is a child of it. Step 2 gives the checkout copy
   its own socket instead. The one time to stop it is right after an install,
   so it picks up the new code, and only when `pgrep -a zypper` shows no
   update running:

   ```sh
   pkill -TERM -f '^/usr/bin/python3 /usr/bin/tumbleweed-updater'
   setsid -f /usr/bin/tumbleweed-updater --tray >/dev/null 2>&1
   ```
3. Both copies share the user's settings (`QSettings`) and the status file.
   Do not change settings in the checkout copy unless that is what is being
   tested, and say so if you do.
4. On start the window may run an update check through the installed `check`
   helper. That helper changes nothing on the system, but it holds zypper's
   lock for about 30 seconds.

## 2. Launch

Pass `--tray` through only if the arguments ask for it.

```sh
[ -d .venv ] || make venv
# A short runtime dir of our own: a Unix socket path must fit in 108 bytes,
# which rules out the scratchpad. WAYLAND_DISPLAY is made absolute because it
# is normally resolved relative to XDG_RUNTIME_DIR. Work it out on its own
# line: in a prefix assignment, bash would already see the new XDG_RUNTIME_DIR.
RT="$XDG_RUNTIME_DIR/tumbleweed-updater-dev"
WL="$XDG_RUNTIME_DIR/${WAYLAND_DISPLAY:-wayland-0}"
mkdir -p -m 0700 "$RT"
XDG_RUNTIME_DIR="$RT" WAYLAND_DISPLAY="$WL" \
  setsid -f sh -c 'echo $$ > "$0/pid"; exec .venv/bin/python3 -m tumbleweed_updater "$@"' "$RT" \
  > "$RT/log" 2>&1
# Wait for it to be listening, which means the window is up.
for i in $(seq 1 20); do [ -S "$RT/tumbleweed-updater.instance" ] && break; sleep 0.5; done
sleep 2; cat "$RT/log"
```

If the socket never appears, show the log. Do not retry in a loop.

## 3. Screenshot

Write screenshots to the scratchpad and Read them.

```sh
spectacle -b -n -a -o "<scratchpad>/window.png"    # the active window: the app, if it took focus
spectacle -b -n -m -o "<scratchpad>/monitor.png"   # the whole monitor, for the tray and popups
```

1. If `-a` captured some other window, use `-m` and crop.
2. Faint or low-contrast text is easy to miss at screenshot scale. To check a
   suspect area, crop it and stretch its contrast with `QImage` under
   `QT_QPA_PLATFORM=offscreen`, then Read the result.
3. To test the other colour scheme, ask the user to switch it in System
   Settings. Do not change the desktop theme yourself. The window icon and the
   tray rebuild on `colorSchemeChanged`, so the app does not need a restart.

## 4. Stop

```sh
RT="$XDG_RUNTIME_DIR/tumbleweed-updater-dev"
[ -f "$RT/pid" ] && kill "$(cat "$RT/pid")"
sleep 1; rm -rf "$RT"
```

If a check was still running, its root helper outlives the window, finishes
on its own and writes the status file as usual. That is harmless. Stopping
the checkout copy during an *update* is not, so never stop it while its
terminal is running `zypper dup`.

Then confirm the installed copy, if there was one, is still running:

```sh
ps -eo pid=,args= | awk '$3 == "/usr/bin/tumbleweed-updater"'
```

## 5. Report

Say what was launched (`--tray` or not), what each screenshot shows, and
anything that looked wrong. Keep "this is how the checkout's GUI looks" apart
from "this is what the installed helpers did".
