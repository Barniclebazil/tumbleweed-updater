# Tumbleweed Updater

A tray-based update manager for **openSUSE Tumbleweed** on **KDE Plasma**, in the
spirit of Linux Mint's `mintupdate`.

* Lives in the system tray. The icon follows the Plasma light/dark theme while
  the system is up to date and turns **openSUSE orange** when updates are
  waiting.
* Shows a window listing the pending **`zypper dup`** and **Flatpak** updates.
* Runs the upgrade in an **embedded terminal** so you answer `zypper`'s prompts
  (the resolver's "Choose from above solutions", vendor changes, …) exactly as
  if you had run `zypper dup` yourself.
* **Btrfs snapshots** are taken by `zypper` itself via `snapper-zypp-plugin`
  (the same pre/post snapshots you get from a manual `sudo zypper dup`); the app
  warns if that plugin is missing.
* A **systemd timer** checks for updates in the background; the cadence
  (hourly … weekly, or manual) is set from the app's settings.

## Requirements

`python3-pyside6`, `python3-pyte`, `zypper`, `polkit` (+ a polkit agent such as
`polkit-kde-agent-6`), optionally `flatpak`, and `snapper-zypp-plugin` for
snapshots. The RPM declares all of these.

## Install

### From the repository (recommended — gets updates via `zypper dup`)

Once a release is published (GitHub Pages repo, see below):

```sh
sudo zypper addrepo -f -G \
  https://barniclebazil.github.io/tumbleweed-updater/tumbleweed-updater.repo
sudo zypper install tumbleweed-updater
```

(`-G` skips the GPG check for an unsigned repo; drop it once signing is set up.)

### Build the RPM yourself

```sh
sudo zypper install rpm-build
sh packaging/build-rpm.sh --install
```

Either way `zypper` resolves `python3-pyside6`, `python3-pyte`, `polkit`, …
itself, and the background-check timer is enabled by the package's systemd
preset.

### Straight into the filesystem (no RPM)

```sh
sudo zypper install python313-pyside6 python313-pyte snapper-zypp-plugin
sudo sh packaging/install.sh          # or: sudo make install
```

Uninstall with `sudo sh packaging/install.sh --uninstall`
(`sudo rpm -e tumbleweed-updater` for the RPM).

The privileged parts (background check, the upgrade itself) go through `pkexec`,
which requires the helper scripts to be **installed** (root-owned under
`/usr/libexec/tumbleweed-updater/`). Running straight from a source checkout
works for the UI but not for `pkexec`-backed actions.

## Run

```sh
tumbleweed-updater          # open the window
tumbleweed-updater --tray   # start hidden in the tray (used for autostart)
```

## Updating the app itself

The app updates your *system*, not itself. The installed copy lives in
`%{python3_sitelib}/tumbleweed_updater/` and is independent of your source
checkout. After changing the code:

```sh
sh packaging/build-rpm.sh --install   # rebuild + zypper upgrade in one step
```

then quit the running instance from the tray and relaunch it (the background
check helper picks up new code on its next run by itself).

For hands-off updates like the rest of Tumbleweed, cut a tagged release
(see *Publishing releases*): the GitHub Pages repo updates, and any machine that
added it with `zypper addrepo` then picks up the new version on `zypper dup`.

## Publishing releases

To ship a new version:

```sh
sh packaging/release.sh 0.2.1 "one-line summary of what changed"
```

That bumps the version in `tumbleweed_updater/__init__.py`, `pyproject.toml` and
the spec, adds a changelog entry, runs the tests, commits, tags `v0.2.1`, and
pushes.

`.github/workflows/ci.yml` runs the tests and builds the RPM on every push.
`.github/workflows/release.yml` fires on the `v*` tag: it attaches the RPM to a
GitHub Release and republishes the zypper repo to GitHub Pages at
<https://barniclebazil.github.io/tumbleweed-updater/>. Machines that added the
repo pick up the new version on their next `zypper dup`.

Add a `GPG_PRIVATE_KEY` repository secret (ASCII-armored private key) to get a
signed repo; then the published `.repo` sets `gpgcheck=1` automatically.

## Development

```sh
python3 -m venv --system-site-packages .venv   # picks up system PySide6
.venv/bin/pip install -e '.[dev]'
make test
python3 -m tumbleweed_updater
```

See `CLAUDE.md` for the architecture.
