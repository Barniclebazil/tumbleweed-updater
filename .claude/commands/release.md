---
description: Commit the working tree, push main, then cut a tagged release
argument-hint: <version> "<one-line changelog note>"
---

Cut release **$1** of Tumbleweed Updater.

Changelog note for this release: **$2**

If either argument is missing, ask for it rather than inventing one. The note
becomes the RPM `%changelog` entry and the subject of the release commit, so it
is permanent and public: one line, plain prose, no markdown.

Work through these in order and stop at the first failure.

## 1. Commit whatever is outstanding

Check `git status`. If the tree is already clean and the work is committed, go
straight to step 2.

Otherwise, run the checks first — system `python3` on this machine has PySide6
and pyte but **no pytest or pyflakes**, so use the repo's venv, creating it if
it is missing (`.venv/` is gitignored):

```sh
[ -d .venv ] || { python3 -m venv --system-site-packages .venv && .venv/bin/pip install pytest pyflakes; }
.venv/bin/python3 -m pyflakes tumbleweed_updater helper tests
QT_QPA_PLATFORM=offscreen .venv/bin/python3 -m pytest -q
```

Do not cut a release on a red suite. Then commit everything with a message
describing what actually changed, read from the diff rather than from $2.

## 2. Push main

```sh
git push
```

`packaging/release.sh` refuses to run unless the tree is clean **and** local
`main` matches `origin/main`, so this has to happen before step 4.

## 3. Stop and confirm

This is the gate. Print, and wait for an explicit yes:

1. The version bump $1 will apply, and the three files it lives in:
   `tumbleweed_updater/__init__.py`, `pyproject.toml` and
   `packaging/tumbleweed-updater.spec`.
2. The `%changelog` line that will be prepended, i.e. $2.
3. The tag that will be pushed: `v$1`.

Say plainly what that tag sets off, because none of it is undoable: pushing it
triggers `.github/workflows/release.yml`, which builds the RPM, publishes a
GitHub Release and republishes the zypper repository on GitHub Pages, where
existing users pick it up through `zypper dup`.

## 4. Cut it

```sh
sh packaging/release.sh $1 "$2"
```

That bumps all three versions, prepends the `%changelog` entry, commits, tags
`v$1` and pushes both. Its own `python3 -m pytest` step runs on the system
interpreter and will print `note: pytest not installed locally - skipping
tests`; that is expected, and step 1 is what actually covers the suite.

## 5. Watch the build

```sh
gh run watch
gh release view v$1
```

The workflow installs `python3-pytest` inside an openSUSE Tumbleweed container
and runs the suite there, so the tests do get executed against the tag. Report
the outcome and link the release. If the run fails, say so with the failing
step's output — do not retag.
