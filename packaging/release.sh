#!/bin/sh
# Cut a new release.
#
#   sh packaging/release.sh 0.2.1 "what changed in one line"
#
# Bumps the version in the three places it lives, adds a %changelog entry,
# runs the tests (if pytest is installed), commits, tags v<version>, and
# pushes. The GitHub "Release" workflow then builds and republishes the repo.

set -eu

NEW="${1:?usage: sh packaging/release.sh <version> [changelog line]}"
NOTE="${2:-Maintenance release.}"

case "$NEW" in
    *[!0-9.]* | "" | .* | *.) echo "version must look like 0.2.1" >&2; exit 1;;
esac

cd "$(dirname "$0")/.."

[ "$(git rev-parse --abbrev-ref HEAD)" = main ] || {
    echo "not on the main branch" >&2; exit 1; }
git diff --quiet && git diff --cached --quiet || {
    echo "working tree has uncommitted changes" >&2; exit 1; }
git fetch --quiet origin main
[ "$(git rev-parse HEAD)" = "$(git rev-parse origin/main)" ] || {
    echo "local main is not in sync with origin/main" >&2; exit 1; }
if git rev-parse "v$NEW" >/dev/null 2>&1; then
    echo "tag v$NEW already exists" >&2; exit 1
fi

AUTHOR="$(git config user.name) <$(git config user.email)>"
DATE="$(LC_ALL=C date -u '+%a %b %d %Y')"

sed -i "s/^__version__ = .*/__version__ = \"$NEW\"/" tumbleweed_updater/__init__.py
sed -i "s/^version = .*/version = \"$NEW\"/" pyproject.toml
sed -i "s/^Version:.*/Version:        $NEW/" packaging/tumbleweed-updater.spec

tmp="$(mktemp)"
awk -v v="$NEW" -v d="$DATE" -v a="$AUTHOR" -v n="$NOTE" '
    /^%changelog/ {
        print
        print "* " d " " a " - " v
        print "- " n
        print ""
        next
    }
    { print }
' packaging/tumbleweed-updater.spec > "$tmp" && mv "$tmp" packaging/tumbleweed-updater.spec

if python3 -c 'import pytest' 2>/dev/null; then
    QT_QPA_PLATFORM=offscreen python3 -m pytest -q
else
    echo "note: pytest not installed locally - skipping tests (CI will run them)"
fi

git add -A
git commit -m "Release $NEW: $NOTE"
git tag "v$NEW"
git push
git push origin "v$NEW"

echo
echo "Pushed v$NEW. Watch the build:   gh run watch"
echo "When it is green:                gh release view v$NEW"
