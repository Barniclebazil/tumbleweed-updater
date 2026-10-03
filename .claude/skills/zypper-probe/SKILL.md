---
name: zypper-probe
description: Measure how zypper, libzypp, PackageKit, snapper or polkit actually behave on this machine before code relies on it, without changing the system, then keep the result as a test fixture and a CLAUDE.md note. Use when a change depends on a tool's output, exit code, lock or timing, or when a bug report needs to be reproduced against the real package system.
argument-hint: "<what to find out>"
---

# Measure the package system, safely

Question to answer: `$ARGUMENTS`

Most of the hard-won rules in CLAUDE.md came from measuring rather than
assuming: the `PAGER` crash, `dup` refusing to refresh, PackageKit's lock, the
solver's question, the title bar's alpha. Follow the same method. Find out what
the tool does on this machine, keep the evidence, and record it.

## 1. Commands you may run yourself

None of these change the system.

```sh
zypper --version; snapper --version; rpm -q zypper libzypp PackageKit snapper polkit
zypper --xmlout repos --details              # no root needed (see repos.py)
zypper --no-refresh --xmlout search -i <name>   # installed packages, cached data only
cat /run/zypp.pid                             # empty, missing or a stale pid all mean "free"
tr '\0' ' ' < /proc/<pid>/cmdline; echo       # who holds it; never trust comm
grep PPid /proc/<pid>/status                  # walk the ancestry, as holder_is_ours() does
cat /run/tumbleweed-updater/status.json
systemctl list-timers tumbleweed-updater-check.timer
systemctl status tumbleweed-updater-check.service
pkaction --verbose --action-id org.opensuse.tumbleweedupdater.<action>
```

1. **Do not call PackageKit's D-Bus methods**, not even read-only ones like
   `GetTransactionList`. A call starts `packagekitd`, which is the thing this
   app goes out of its way not to wake. `busctl --system list | grep -i
   packagekit` only looks and is fine.
2. The installed `check` helper (`pkexec /usr/libexec/tumbleweed-updater/check`)
   needs no password for an active session. It only refreshes and does a dry
   run, then writes the status file the running app reads. You may run it, but
   it holds zypper's lock for about 30 seconds. Say so first if the user might
   be using YaST or Discover.
3. `journalctl` for the system units needs the `systemd-journal` group. If it
   says "No entries", that may be permissions, not an empty log.

## 2. Commands the user runs

Anything else that needs root goes to the user as one exact line to type with
the `!` prefix, so the output lands in the conversation. Pin the locale to
match the helper you are imitating, and always print the exit code, because
the exit code is often the finding.

```sh
! sudo env LC_ALL=C zypper --non-interactive refresh; echo "exit $?"
! sudo zypper --non-interactive --no-refresh --xmlout dup --dry-run --details > <scratchpad>/dup.xml 2>&1; echo "exit $?"
! sudo snapper --jsonout list > <scratchpad>/snapper.json; echo "exit $?"
```

1. Mirror the real argv. `helper/check` refreshes with `LC_ALL=C`, and
   `sources.check_zypper()` runs `--non-interactive --no-refresh --xmlout dup
   --dry-run --details`. `helper/run-update` runs zypper interactively on a
   PTY with `PAGER=/usr/bin/cat`, in the user's locale (it falls back to
   `C.UTF-8` only when `LANG` is unset). A probe that differs from the helper
   in locale, `PAGER` or interactivity measures something else.
2. Write long output to a file in the scratchpad and Read it, rather than
   pasting it into the conversation.
3. **Never propose anything that changes the system as a probe.** That
   includes `dup` without `--dry-run`, `install`, `remove`, `patch`,
   `modifyrepo`, `addrepo`, `removerepo`, `snapper create/delete/rollback`,
   masking or stopping `packagekit`, and killing whatever holds
   `/run/zypp.pid` (it may be mid-transaction). If a question can only be
   answered that way, as with the VLC source in CLAUDE.md, explain what it
   will change and how to undo it, and let the user decide.

## 3. Keep the evidence

1. Note the versions (`rpm -q` above), the locale, the exit code, and both
   output streams.
2. zypper translates its messages. Never make a parser depend on translated
   text: match XML element names, or tokens that are the same in every
   language (the `[alias|url]` that `repos.failed_aliases()` relies on).
3. Turn a capture into an inline fixture in the matching test file:
   `tests/test_sources.py` for dup and check XML, `tests/test_repos.py` for
   source lists and refresh output, `tests/test_snapshots.py` for snapper,
   `tests/test_packagekit.py` for the lock and `/proc`.
4. Trim it to the least that still shows the behaviour, keeping the XML well
   formed. Replace anything personal or private (hostnames, user names, URLs of
   private sources).
5. Put a comment above it in the existing style: "A real capture, trimmed:
   `<command>` <the circumstances>. <what it shows>." If the test reproduces a
   bug, see it fail before fixing the code.

## 4. Record it

Add the finding to CLAUDE.md under the module it affects, in the style already
there: say it was measured, give the version ("Measured on zypper 1.14.101"),
state what was observed, and state what the code does about it. Write only what
was observed. If something was inferred and not measured, say that instead.

## 5. Report

1. What was run, and who ran it (you, or the user via `!`).
2. The result, with the exit code and versions.
3. What it means for the code, and which fixture and CLAUDE.md lines now hold
   it.
