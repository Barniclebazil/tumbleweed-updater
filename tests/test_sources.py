"""Parser tests. The XML fixtures mirror /usr/share/zypper/xml/xmlout.rnc."""

import subprocess

from tumbleweed_updater import sources
from tumbleweed_updater.sources import (
    Action,
    ZYPPER_EXIT_ZYPP_LOCKED,
    check_zypper,
    human_bytes,
    parse_flatpak_updates,
    parse_zypper_dup_xml,
)

DUP_XML = """<?xml version='1.0'?>
<stream>
<message type="info">Loading repository data...</message>
<message type="info">Reading installed packages...</message>
<message type="info">Computing distribution upgrade...</message>
<install-summary download-size="123456789" space-usage-diff="-2048" space-usage-installed="0"
 space-usage-removed="2048" packages-to-change="3" need-restart="false" need-reboot="true">
  <to-upgrade>
    <solvable status="other-version" kind="package" name="bash" edition="5.2.37-1.1"
     edition-old="5.2.32-1.1" arch="x86_64" summary="The GNU Bourne-Again Shell"/>
    <solvable status="other-version" kind="package" name="glibc" edition="2.41-1.1"
     edition-old="2.40-3.1" arch="x86_64"/>
    <solvable status="other-version" kind="patch" name="ignore-me" edition="1" arch="noarch"/>
  </to-upgrade>
  <to-install>
    <solvable status="not-installed" kind="package" name="libnewdep1" edition="1.0-1.1" arch="x86_64"/>
  </to-install>
  <to-remove>
    <solvable status="installed" kind="package" name="oldpkg" edition="0.9-1.1" arch="x86_64"/>
  </to-remove>
</install-summary>
</stream>
"""

NOTHING_XML = """<?xml version='1.0'?>
<stream>
<message type="info">Computing distribution upgrade...</message>
<message type="info">Nothing to do.</message>
</stream>
"""

ERROR_XML = """<?xml version='1.0'?>
<stream>
<message type="error">Repository 'foo' is invalid.</message>
</stream>
"""

LOCK_XML = """<?xml version='1.0'?>
<stream>
<message type="error">System management is locked by the application with pid 5899 (/usr/libexec/packagekitd).
Close this application before trying again.</message>
</stream>
"""


def test_parses_all_groups():
    res = parse_zypper_dup_xml(DUP_XML)
    assert res.error is None
    names = {p.name: p for p in res.packages}
    # patch solvable is filtered out; 4 package solvables remain
    assert set(names) == {"bash", "glibc", "libnewdep1", "oldpkg"}
    assert names["bash"].action is Action.UPGRADE
    assert names["bash"].old_version == "5.2.32-1.1"
    assert names["bash"].new_version == "5.2.37-1.1"
    assert names["bash"].summary_line == "5.2.32-1.1 → 5.2.37-1.1"
    assert names["libnewdep1"].action is Action.INSTALL
    assert names["oldpkg"].action is Action.REMOVE
    assert res.download_size == 123456789
    assert res.space_diff == -2048
    assert res.need_reboot is True
    assert res.need_restart is False


def test_nothing_to_do():
    res = parse_zypper_dup_xml(NOTHING_XML)
    assert res.error is None
    assert res.count == 0


def test_error_message_surfaced():
    res = parse_zypper_dup_xml(ERROR_XML)
    assert res.count == 0
    assert res.error and "invalid" in res.error


def test_unterminated_stream_recovers():
    truncated = DUP_XML.split("</install-summary>")[0]
    res = parse_zypper_dup_xml(truncated)
    # Should not raise; may or may not recover packages, but never crashes.
    assert isinstance(res.count, int)


def test_empty_input():
    res = parse_zypper_dup_xml("")
    assert res.error is not None


def test_human_bytes():
    assert human_bytes(0) == "0 B"
    assert human_bytes(2048) == "2.0 KiB"
    assert human_bytes(-2048) == "-2.0 KiB"
    assert human_bytes(123456789).endswith("MiB")


def test_check_zypper_sets_locked_on_exit_code_7(monkeypatch):
    def fake_run(*args, **kwargs):
        return subprocess.CompletedProcess(
            args, returncode=ZYPPER_EXIT_ZYPP_LOCKED, stdout=LOCK_XML, stderr=""
        )

    monkeypatch.setattr(sources.subprocess, "run", fake_run)
    res = check_zypper()
    assert res.locked is True
    assert res.error and "locked" in res.error.lower()


def test_check_zypper_other_error_not_flagged_locked(monkeypatch):
    def fake_run(*args, **kwargs):
        return subprocess.CompletedProcess(
            args, returncode=6, stdout=ERROR_XML, stderr="Repository 'foo' is invalid."
        )

    monkeypatch.setattr(sources.subprocess, "run", fake_run)
    res = check_zypper()
    assert res.locked is False
    assert res.error and "invalid" in res.error


def test_flatpak_parser():
    text = "Application\tVersion\tBranch\tOrigin\n" \
           "org.kde.Kdenlive\t24.12.0\tstable\tflathub\n" \
           "org.gimp.GIMP\t2.10.38\tstable\tflathub\n"
    refs = parse_flatpak_updates(text, "user")
    assert [r.ref_id for r in refs] == ["org.kde.Kdenlive", "org.gimp.GIMP"]
    assert refs[0].version == "24.12.0"
    assert refs[0].installation == "user"


# A real capture, trimmed: `zypper --xmlout dup --dry-run` after a software
# source that installed packages came from was switched off. Every one of them
# is orphaned, the solver raises a question per orphan, and non-interactive
# zypper takes its default (cancel) and exits 4 with an empty stderr - so the
# window used to show the bare words "zypper exited 4".
SOLVER_QUESTION = """<?xml version='1.0'?>
<stream>
<message type="info">Computing distribution upgrade...</message>
<message type="info">14 Problems:</message>
<message type="info">Problem: 1: problem with the installed vlc-3.0.23-425.6.x86_64</message>
<prompt id="1">
<description>Problem: 1: Detailed information:
- the installed vlc-3.0.23-425.6.x86_64 does not belong to a distupgrade repository and must be replaced
 Solution 1: install vlc-3.0.23-425.5.x86_64 from vendor openSUSE
 Solution 2: keep obsolete vlc-3.0.23-425.6.x86_64
</description>
<text>Choose from above solutions by number or skip, retry or cancel</text>
<option value="1" desc="Choose solution 1"/>
<option default="1" value="c" desc="Choose no solution and cancel."/>
</prompt>
</stream>
"""


def test_a_solver_question_is_a_decision_not_an_error():
    """The check worked: its answer is that the user has to choose, and the
    upgrade (interactive, in the terminal) is where they can."""
    result = sources.parse_zypper_dup_xml(SOLVER_QUESTION)

    assert result.packages == []
    assert result.needs_decision
    assert result.error is None


def test_the_decision_notice_is_written_for_anyone():
    # Written for someone who has never heard of a repository, like everything
    # else that reaches the window.
    for jargon in ("repository", "distupgrade", "solver", "zypper", "exit"):
        assert jargon not in sources.NEEDS_A_DECISION.lower(), jargon
    # It names the way on, which is the button and the terminal.
    assert "Update now" in sources.NEEDS_A_DECISION


def test_check_zypper_does_not_turn_a_question_into_an_exit_code(monkeypatch):
    """The dry run exits 4 over a question. That used to reach the window as
    the bare words "zypper exited 4"."""
    monkeypatch.setattr(
        sources.subprocess,
        "run",
        lambda *a, **k: subprocess.CompletedProcess(
            a, returncode=4, stdout=SOLVER_QUESTION, stderr=""
        ),
    )
    result = sources.check_zypper()

    assert result.needs_decision
    assert result.error is None


def test_an_ordinary_prompt_alongside_a_summary_is_not_an_error():
    """zypper also prompts for GPG keys and media changes. Only a stream that
    computed nothing at all is a failure."""
    with_summary = SOLVER_QUESTION.replace(
        "</stream>",
        '<install-summary download-size="1" space-usage-diff="0" '
        'packages-to-change="1" need-restart="false" need-reboot="false">'
        '<to-upgrade><solvable status="installed" kind="package" name="bash" '
        'edition="5.3" edition-old="5.2" arch="x86_64"/></to-upgrade>'
        "</install-summary></stream>",
    )
    result = sources.parse_zypper_dup_xml(with_summary)

    assert result.error is None
    assert [p.name for p in result.packages] == ["bash"]
