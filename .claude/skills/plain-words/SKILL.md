---
name: plain-words
description: Check the text Tumbleweed Updater shows its users (banners, dialogs, tray tooltips and notifications, Settings labels, README, a release's changelog note) against the project's plain-language rule and the user's 20-rule writing style guide. Use after changing any user-facing string, before a release, or when asked to review wording.
argument-hint: "[commit | range | all | \"changelog note\"]"
---

# Check user-facing wording

Many of this project's releases were about how a failure is explained. This
skill checks the text against the written rules and reports what breaks them.
**It reports and does not edit**, unless the user then asks for the fixes.

## 1. Work out what to check

Arguments: `$ARGUMENTS`

1. Nothing: the uncommitted changes (`git diff HEAD`) plus any untracked files
   in the scope below.
2. A commit or a range (`git rev-parse --verify --quiet "<arg>^{commit}"`
   succeeds, or the argument contains `..`): that diff.
3. `all`: every file in the scope below, in full.
4. Anything else: treat it as a proposed changelog note and check that text
   alone. The note becomes the RPM `%changelog` entry and the release commit's
   subject, so it must also be one line, plain prose and free of markdown.

In a diff, check added and changed lines. Read the surrounding function to
decide whether a string reaches the user. For an f-string, follow each
interpolated value back to where it comes from. `f"Update check failed:
{message}"` is only as plain as `message`, and a value that started in zypper,
pkexec or an exception can carry their wording into a banner.

## 2. Scope

User-facing text lives in these places. Use the names to find it, since line
numbers move. When checking an older commit, some of these names may not exist
yet, which is not a finding.

1. `tumbleweed_updater/mainwindow.py`: `_missing_sources_text()`,
   `_stuck_sources_text()`, `_locked_text()`, `_render_banner()`,
   `_check_failure`, `_run_failure`, the headline and `_subline`, every
   `QMessageBox`, `statusBar().showMessage()`, button labels and tooltips.
2. `tumbleweed_updater/sources.py`: `NEEDS_A_DECISION`.
3. `tumbleweed_updater/app.py`: `tray.showMessage()` notifications, and the
   question about Plasma's update notifier.
4. `tumbleweed_updater/tray.py`: menu labels and tooltips.
5. `tumbleweed_updater/settingsdialog.py`, `snapshotsdialog.py`, `terminal.py`:
   labels, tooltips and `QMessageBox` text.
6. `tumbleweed_updater/repos.py`: messages that replace zypper's, such as
   `set_enabled()`'s for a held lock.
7. `data/org.opensuse.tumbleweedupdater.policy`: each `<message>` is the
   sentence in the polkit password dialog, so it is dialog text.
8. `data/*.desktop`: `Name`, `GenericName` and `Comment` appear in the
   launcher.
9. `helper/check` and `tumbleweed_updater/sources.py`: the strings put into
   `ZypperResult.error` ("zypper exited N" and the like). They reach the banner
   through `z.error`, so check them under section 3.
10. `helper/run-update` (`_heading()`, `_stopped_by()`) and
    `tumbleweed_updater/runner.py` (`append_notice` lines): this app's own
    sentences in the terminal.
11. `README.md`.

Out of scope: comments, docstrings, log output, and zypper's or flatpak's own
words in the terminal. CLAUDE.md keeps those untouched on purpose, because the
terminal is the record of what actually happened. This app's own notices in
the terminal (`append_notice`, and the helper messages in item 10) get the style
check in section 4 but not the vocabulary rule in section 3, since they sit
beside the exact command line. Check that each one is accurate about what
happened in every case that can reach it.

## 3. The project rule (CLAUDE.md, Conventions)

This applies to anything that tells the user about a failure or a problem:
banners, warning and error dialogs, the polkit messages, failure
notifications, the tray tooltip in an error state, the changelog note, and the
README's sections about what happens when something goes wrong. The README's
install and packaging sections may name the zypper repository, since that is
what the reader types.

1. Write it for someone who has never heard of a repository.
2. No "repository" or "repo". Say "software source". Exception: the real name
   of something the user has to find, quoted exactly, such as YaST's "Software
   Repositories" page. Do not report that.
3. No "metadata" or "refresh". Other jargon ("zypp", "solver", "vendor",
   "dependency", "lock" for zypper's lock) is not banned by name. Flag it as a
   judgement call when a plainer word would do.
4. No exit codes, pids, aliases, file paths or command names. Name a source by
   its display name and never by its alias. Name a lock holder in words, as
   `_locked_text()` does, and not by pid.
5. Do not paste raw text from a tool. zypper's sentence "System management is
   locked by the application with pid N (zypper). Close this application before
   trying again" breaks rules 3 and 4, and the pid is usually this app's own.
6. Say what happened, what it means for the user's programs, and whether there
   is anything for them to do. If there is nothing to do, say so.

Settings labels and tooltips for options that are themselves technical (the
`zypper dup` options, the free-text options field) may name the option. Their
explanation should still be plain.

## 4. The style guide

These are the user's rules for anything they will read or publish. The ones
that apply to interface text are marked UI. In the README, check every rule
except 5, 10 and 13.

1. Numbered lists only. Never bullets, dashes or asterisks as list markers.
   (README; also UI text that builds a list.)
2. Copyable content (code, commands) goes in a code block. (README)
3. UI: concise. The answer plus the reasoning needed to check it.
4. Headings only where more than one topic is covered. (README)
5. Comments explain what and why. (Not checked here.)
6. UI: British English spelling, punctuation and terminology ("colour",
   "licence" as a noun, "authorise", "behaviour").
7. UI: metric units.
8. UI: dates DD/MM/YYYY, times on the 24-hour clock.
9. UI: neutral, factual register. No enthusiasm markers or exclamation marks.
10. No opening praise. (Replies only.)
11. UI: no first-person emotional language ("Sorry", "Oops", "Unfortunately").
    State what happened in functional terms.
12. Do not shape the message toward what the user wants to hear. If the update
    did not happen, say that first.
13. No closing validation or encouragement. (Replies only.)
14. UI: no rhetorical build-ups.
15. UI: no tricolon padding. List the number of things that actually apply.
16. UI: no "not just X, but Y" or "it isn't X, it's Y".
17. UI: no em-dash asides in a sentence and no one-line paragraphs for
    emphasis. A dash that separates a label from the command it runs
    ("System upgrade — zypper dup") is not an aside.
18. UI: no metaphor or analogy unless the idea cannot be stated directly.
19. UI: no hype words (powerful, seamless, robust, unlock, leverage,
    supercharge, game-changing, revolutionary, deep dive).
20. UI: no filler qualifiers ("it's worth noting", "essentially",
    "fundamentally", "at the end of the day", "simply", "just" used as
    softening).

## 5. Report

Group findings by file. For each one, give:

1. `path:line`.
2. The text as it stands, quoted.
3. The rule it breaks, as "project 4" or "style 17".
4. A suggested rewording that keeps the meaning and fits where the string is
   shown (a banner line, a tooltip, a button).

When checking a commit or range, look at whether each finding is still in
the current code and say so. One that has since been fixed goes in a short
"Already fixed" list at the end, not among the findings.

End with the number of findings, or "No problems found" and what was checked.
Do not report a rule as broken unless you can quote the words that break it.
When a finding is a judgement call, such as tone, say so.
