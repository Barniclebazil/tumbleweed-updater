#!/bin/sh
# Install Tumbleweed Updater without make/RPM.
#
#   sudo sh packaging/install.sh            install into /usr
#   sudo sh packaging/install.sh --uninstall
#   DESTDIR=/tmp/stage sh packaging/install.sh   stage without root (for testing)
#
# Run from the repository root.

set -eu

PREFIX="${PREFIX:-/usr}"
DESTDIR="${DESTDIR:-}"
SITELIB="${SITELIB:-$(python3 -c 'import sysconfig; print(sysconfig.get_path("purelib"))')}"

BINDIR="$PREFIX/bin"
LIBEXECDIR="$PREFIX/libexec/tumbleweed-updater"
DATADIR="$PREFIX/share"
POLKITDIR="$DATADIR/polkit-1/actions"
UNITDIR="$PREFIX/lib/systemd/system"
ICONDIR="$DATADIR/icons/hicolor/scalable/apps"
APPSDIR="$DATADIR/applications"
RESDIR="$DATADIR/tumbleweed-updater"
PRESETDIR="$PREFIX/lib/systemd/system-preset"

d() { echo "$DESTDIR$1"; }

if [ "${1:-}" = "--uninstall" ]; then
    rm -rf  "$(d "$SITELIB")/tumbleweed_updater"
    rm -f   "$(d "$BINDIR")/tumbleweed-updater"
    rm -rf  "$(d "$LIBEXECDIR")"
    rm -f   "$(d "$POLKITDIR")/org.opensuse.tumbleweedupdater.policy"
    rm -f   "$(d "$UNITDIR")/tumbleweed-updater-check.service"
    rm -f   "$(d "$UNITDIR")/tumbleweed-updater-check.timer"
    rm -f   "$(d "$PRESETDIR")/50-tumbleweed-updater.preset"
    rm -f   "$(d "$ICONDIR")/tumbleweed-updater.svg"
    rm -rf  "$(d "$RESDIR")"
    rm -f   "$(d "$APPSDIR")/org.opensuse.TumbleweedUpdater.desktop"
    rm -f   "$(d "/etc/systemd/system/tumbleweed-updater-check.timer.d/override.conf")"
    rmdir   "$(d "/etc/systemd/system/tumbleweed-updater-check.timer.d")" 2>/dev/null || true
    echo "Removed. You may want: sudo systemctl disable --now tumbleweed-updater-check.timer"
    exit 0
fi

install -d "$(d "$SITELIB")/tumbleweed_updater"
install -m644 tumbleweed_updater/*.py "$(d "$SITELIB")/tumbleweed_updater/"

install -d "$(d "$BINDIR")"
install -m755 packaging/tumbleweed-updater.launcher "$(d "$BINDIR")/tumbleweed-updater"

install -d "$(d "$LIBEXECDIR")"
install -m755 helper/check        "$(d "$LIBEXECDIR")/check"
install -m755 helper/set-interval "$(d "$LIBEXECDIR")/set-interval"
install -m755 helper/run-update   "$(d "$LIBEXECDIR")/run-update"
install -m755 helper/snapshots    "$(d "$LIBEXECDIR")/snapshots"
install -m755 helper/snapshots-manage "$(d "$LIBEXECDIR")/snapshots-manage"

install -d "$(d "$POLKITDIR")"
install -m644 data/org.opensuse.tumbleweedupdater.policy "$(d "$POLKITDIR")/"

install -d "$(d "$UNITDIR")"
install -m644 data/systemd/tumbleweed-updater-check.service "$(d "$UNITDIR")/"
install -m644 data/systemd/tumbleweed-updater-check.timer   "$(d "$UNITDIR")/"

install -d "$(d "$PRESETDIR")"
install -m644 data/systemd/50-tumbleweed-updater.preset "$(d "$PRESETDIR")/"

install -d "$(d "$ICONDIR")"
install -m644 data/icons/tumbleweed-updater.svg "$(d "$ICONDIR")/"

install -d "$(d "$RESDIR")/icons/styles"
install -m644 data/icons/tumbleweed-updater.svg "$(d "$RESDIR")/icons/"
install -m644 data/icons/styles/*.svg "$(d "$RESDIR")/icons/styles/"

install -d "$(d "$APPSDIR")"
install -m644 data/org.opensuse.TumbleweedUpdater.desktop "$(d "$APPSDIR")/"

if [ -z "$DESTDIR" ]; then
    systemctl daemon-reload || true
    systemctl preset tumbleweed-updater-check.timer || true
    systemctl start tumbleweed-updater-check.timer 2>/dev/null || true
    command -v gtk-update-icon-cache >/dev/null 2>&1 && \
        gtk-update-icon-cache -qtf "$DATADIR/icons/hicolor" || true
    echo
    echo "Installed. Background update checks are enabled (every 3 h)."
    echo "Populate the list now with:  sudo systemctl start tumbleweed-updater-check.service"
    echo "Launch 'Tumbleweed Updater' from the menu, or run: tumbleweed-updater"
fi
