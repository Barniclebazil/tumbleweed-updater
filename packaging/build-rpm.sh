#!/bin/sh
# Build a binary RPM of Tumbleweed Updater.
#
#   sh packaging/build-rpm.sh              build only
#   sh packaging/build-rpm.sh --install   build, then install/upgrade it
#
# Needs: rpm-build  (sudo zypper install rpm-build)
# Run from the repository root. Produces an .rpm; zypper pulls python3-pyside6,
# python3-pyte, polkit, ... automatically when it is installed.

set -eu

DO_INSTALL=no
[ "${1:-}" = "--install" ] && DO_INSTALL=yes

NAME=tumbleweed-updater
SPEC="packaging/$NAME.spec"
VERSION=$(sed -n 's/^Version:[[:space:]]*//p' "$SPEC" | head -n1)

command -v rpmbuild >/dev/null 2>&1 || {
    echo "rpmbuild not found. Install it with: sudo zypper install rpm-build" >&2
    exit 1
}

TOP=$(rpm --eval '%{_topdir}')
mkdir -p "$TOP/SOURCES" "$TOP/SPECS" "$TOP/BUILD" "$TOP/RPMS" "$TOP/SRPMS"

echo ">>> Creating $NAME-$VERSION.tar.xz"
staging=$(mktemp -d)
trap 'rm -rf "$staging"' EXIT
mkdir "$staging/$NAME-$VERSION"
tar --exclude=.git --exclude=__pycache__ --exclude='*.pyc' \
    --exclude=.pytest_cache --exclude='./venv' --exclude='./.venv' \
    --exclude='./packaging/*.tar.*' --exclude='./*.rpm' \
    -cf - . | tar -xf - -C "$staging/$NAME-$VERSION"
tar -C "$staging" -cJf "$TOP/SOURCES/$NAME-$VERSION.tar.xz" "$NAME-$VERSION"

cp "$SPEC" "$TOP/SPECS/"

echo ">>> rpmbuild -bb"
rpmbuild -bb "$TOP/SPECS/$NAME.spec"

RPM=$(find "$TOP/RPMS" -name "$NAME-$VERSION-*.noarch.rpm" | head -n1)
echo
echo ">>> Built: $RPM"

if [ "$DO_INSTALL" = yes ]; then
    echo ">>> Installing (locally built RPMs are unsigned)"
    sudo zypper install --allow-unsigned-rpm -f "$RPM"
    echo
    echo "Restart the running app to pick up the new version:"
    echo "  quit it from the tray, then: tumbleweed-updater"
else
    echo "Install it (pulls dependencies):"
    echo "  sudo zypper install --allow-unsigned-rpm $RPM"
fi
