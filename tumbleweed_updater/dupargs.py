"""The allow-list of ``zypper dup`` options ``helper/run-update`` will accept.

Kept free of any Qt import so the privileged helper can share it with the GUI,
the same arrangement as :mod:`tumbleweed_updater.intervals`.

Why an allow-list at all: polkit's ``exec.path`` annotation matches only the
program path, never its arguments, and the update action is ``auth_admin_keep``
so the authorisation stays cached for a few minutes. Without this check, any
process running as the user could re-run the helper as root during that window
with whatever ``zypper dup`` options it liked. Everything the settings dialog
can produce is here; anything else is refused before zypper is reached.
"""

from __future__ import annotations

# Options that stand alone.
FLAGS = frozenset(
    {
        "-y",
        "--no-confirm",
        "--auto-agree-with-licenses",
        "--allow-vendor-change",
        "--no-allow-vendor-change",
        "--recommends",
        "--no-recommends",
        "--details",
        "--dry-run",
        "--debug-solver",
    }
)

# Options that take a value, mapped to the values they may take. Anything that
# takes a free-form path, URI or repository is deliberately absent.
VALUED = {
    "--download": frozenset({"in-advance", "in-heaps", "as-needed", "only"}),
}


def unknown_args(tokens: list[str]) -> list[str]:
    """Return the tokens that are not acceptable, in the order they appear.

    A value is checked against the option it follows, so ``--download`` with a
    bad value reports the value, and a stray value with no option in front of
    it reports the value too.
    """
    rejected: list[str] = []
    expect: frozenset[str] | None = None
    for token in tokens:
        if expect is not None:
            if token not in expect:
                rejected.append(token)
            expect = None
            continue
        if token in VALUED:
            expect = VALUED[token]
            continue
        if token in FLAGS:
            continue
        # "--download=in-advance" is the same option written the other way.
        option, sep, value = token.partition("=")
        if sep and option in VALUED and value in VALUED[option]:
            continue
        rejected.append(token)
    if expect is not None:
        rejected.append("(missing value)")
    return rejected


def is_allowed(tokens: list[str]) -> bool:
    return not unknown_args(tokens)
