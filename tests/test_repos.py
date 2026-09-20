"""Reading and switching software sources.

The XML fixture is a trimmed copy of real `zypper --xmlout repos --details`
output from a Tumbleweed install, including the disabled entries every system
accumulates (debug, source, the installation medium).
"""

import subprocess

from tumbleweed_updater import repos

REPOS_XML = """<?xml version='1.0'?>
<stream>
<repo-list>
<repo alias="download.opensuse.org-oss" name="Main Repository (OSS)" type="rpm-md" priority="99" enabled="1" autorefresh="1">
<url>http://download.opensuse.org/tumbleweed/repo/oss/</url>
</repo>
<repo alias="repo-debug" name="openSUSE-Tumbleweed-Debug" priority="99" enabled="0" autorefresh="1">
<url>http://download.opensuse.org/debug/tumbleweed/repo/oss/</url>
</repo>
<repo alias="vlc" name="VLC" type="rpm-md" priority="90" enabled="1" autorefresh="1">
<url>http://download.videolan.org/pub/vlc/SuSE/Tumbleweed/</url>
</repo>
<repo alias="bare" priority="99" enabled="1" autorefresh="0">
<url>https://example.invalid/bare/</url>
</repo>
</repo-list>
</stream>
"""

# The exact text zypper printed in the failure this was written for, with
# LC_ALL=C. The alias appears only inside the "[alias|url]" token; the
# "Skipping repository 'VLC'" line carries the display name instead.
REFRESH_FAILURE = """Retrieving repository 'VLC' metadata ...............................[error]
Repository 'VLC' is invalid.
[vlc|http://download.videolan.org/pub/vlc/SuSE/Tumbleweed/] Failed to retrieve new repository metadata.
History:
 - [] Error trying to read from 'http://download.videolan.org/pub/vlc/SuSE/Tumbleweed/'
 - Download (curl) error for 'http://download.videolan.org/pub/vlc/SuSE/Tumbleweed/content':
   Error code: Connection failed Curl error (7)
   Error message: Failed to connect to download.videolan.org:80 after 4448 ms: Could not connect to server

Please check if the URIs defined for this repository are pointing to a valid repository.
Skipping repository 'VLC' because of the above error.
Some of the repositories have not been refreshed because of an error.
"""


def test_parses_aliases_names_and_enabled_state():
    result = repos.parse_zypper_repos_xml(REPOS_XML)
    assert result.error is None
    assert [r.alias for r in result.repos] == [
        "download.opensuse.org-oss",
        "repo-debug",
        "vlc",
        "bare",
    ]
    assert result.by_alias("vlc").name == "VLC"
    assert result.by_alias("vlc").enabled is True
    assert result.by_alias("vlc").url.endswith("/SuSE/Tumbleweed/")
    assert result.by_alias("repo-debug").enabled is False


def test_a_source_with_no_name_falls_back_to_its_alias():
    # `zypper ar <url> <alias>` leaves name empty, and the window must still
    # have something to call it.
    result = repos.parse_zypper_repos_xml(REPOS_XML)
    assert result.by_alias("bare").label == "bare"
    assert result.by_alias("vlc").label == "VLC"


def test_by_alias_returns_none_for_an_unknown_source():
    assert repos.parse_zypper_repos_xml(REPOS_XML).by_alias("nope") is None


def test_malformed_xml_is_an_error_not_an_exception():
    result = repos.parse_zypper_repos_xml("<stream><repo-list>")
    assert result.error is not None
    assert result.repos == []


def test_failed_aliases_finds_the_unreachable_source():
    known = ["download.opensuse.org-oss", "repo-debug", "vlc", "bare"]
    assert repos.failed_aliases(REFRESH_FAILURE, known) == ["vlc"]


def test_failed_aliases_ignores_an_alias_that_does_not_exist():
    """The list is what the window later hands back to helper/repos, so a name
    scraped out of the output is only trusted if zypper really has it."""
    assert repos.failed_aliases(REFRESH_FAILURE, ["download.opensuse.org-oss"]) == []


def test_failed_aliases_reports_each_source_once():
    doubled = REFRESH_FAILURE + REFRESH_FAILURE
    assert repos.failed_aliases(doubled, ["vlc"]) == ["vlc"]


def test_failed_aliases_on_a_clean_refresh_finds_nothing():
    clean = (
        "Repository 'Main Repository (OSS)' is up to date.\n"
        "Repository 'VLC' is up to date.\n"
        "All repositories have been refreshed.\n"
    )
    assert repos.failed_aliases(clean, ["vlc"]) == []


def test_list_repos_reports_a_missing_zypper(monkeypatch):
    def boom(*args, **kwargs):
        raise FileNotFoundError

    monkeypatch.setattr(repos.subprocess, "run", boom)
    assert "not installed" in repos.list_repos().error


def test_list_repos_accepts_the_no_repositories_exit_code(monkeypatch):
    # Exit 6 is "no repositories defined", a legitimate empty answer.
    monkeypatch.setattr(
        repos.subprocess,
        "run",
        lambda *a, **k: subprocess.CompletedProcess(
            a, returncode=6, stdout="<stream><repo-list/></stream>", stderr=""
        ),
    )
    result = repos.list_repos()
    assert result.error is None
    assert result.repos == []


def test_set_enabled_builds_the_right_command(monkeypatch):
    seen = {}

    def fake_run(argv, **kwargs):
        seen["argv"] = argv
        return subprocess.CompletedProcess(argv, returncode=0, stdout="", stderr="")

    monkeypatch.setattr(repos.subprocess, "run", fake_run)

    assert repos.set_enabled("vlc", enabled=False) is None
    assert seen["argv"] == [
        "zypper",
        "--non-interactive",
        "modifyrepo",
        "--disable",
        "vlc",
    ]

    assert repos.set_enabled("vlc", enabled=True) is None
    assert seen["argv"][-2:] == ["--enable", "vlc"]


def test_set_enabled_translates_a_held_package_lock(monkeypatch):
    """zypper's own words for exit 7 are "System management is locked by the
    application with pid N ... Close this application before trying again."
    Passed through, the user reads that in a dialog they did not type anything
    into, above a window that is not going to close itself."""
    monkeypatch.setattr(
        repos.subprocess,
        "run",
        lambda *a, **k: subprocess.CompletedProcess(
            a,
            returncode=7,
            stdout="",
            stderr=(
                "System management is locked by the application with pid 3383 "
                "(zypper).\nClose this application before trying again."
            ),
        ),
    )
    message = repos.set_enabled("vlc", enabled=False)
    assert "Close this application" not in message
    assert "try again" in message
    for jargon in ("repository", "zypper", "pid", "exit"):
        assert jargon not in message.lower(), jargon


def test_set_enabled_returns_zyppers_complaint(monkeypatch):
    monkeypatch.setattr(
        repos.subprocess,
        "run",
        lambda *a, **k: subprocess.CompletedProcess(
            a, returncode=6, stdout="", stderr="Repository 'nope' not found."
        ),
    )
    assert "not found" in repos.set_enabled("nope", enabled=False)


# --------------------------------------------------------------------------- #
# The note that puts a source back after an interrupted upgrade.
# --------------------------------------------------------------------------- #


def _listing(monkeypatch, *pairs):
    """Stand in for the real source list: (alias, enabled) per source."""
    monkeypatch.setattr(
        repos,
        "list_repos",
        lambda *a, **k: repos.ReposResult(
            repos=[repos.Repo(alias=a, enabled=e) for a, e in pairs]
        ),
    )


def test_a_remembered_source_is_switched_back_on(monkeypatch, tmp_path):
    note = str(tmp_path / "restore.json")
    switched = []
    _listing(monkeypatch, ("vlc", False))
    monkeypatch.setattr(
        repos, "set_enabled", lambda alias, enabled, **k: switched.append(
            (alias, enabled)
        )
    )

    repos.remember_to_restore(["vlc"], note)
    assert repos.restore_remembered(note) == ["vlc"]
    assert switched == [("vlc", True)]
    # The note goes once it has been acted on, so the next check does nothing.
    assert repos.restore_remembered(note) == []


def test_restoring_without_a_note_does_nothing(tmp_path):
    assert repos.restore_remembered(str(tmp_path / "nothing.json")) == []


def test_a_source_that_has_since_gone_is_skipped(monkeypatch, tmp_path):
    """The note names an alias; by the time it is read the user may have
    deleted that source. Nothing invented reaches a zypper command line."""
    note = str(tmp_path / "restore.json")
    switched = []
    _listing(monkeypatch, ("other", True))
    monkeypatch.setattr(
        repos, "set_enabled", lambda alias, enabled, **k: switched.append(alias)
    )

    repos.remember_to_restore(["vlc"], note)
    assert repos.restore_remembered(note) == []
    assert switched == []


def test_a_source_the_user_switched_on_again_is_left_alone(monkeypatch, tmp_path):
    note = str(tmp_path / "restore.json")
    switched = []
    _listing(monkeypatch, ("vlc", True))
    monkeypatch.setattr(
        repos, "set_enabled", lambda alias, enabled, **k: switched.append(alias)
    )

    repos.remember_to_restore(["vlc"], note)
    assert repos.restore_remembered(note) == []
    assert switched == []


def test_a_damaged_note_is_discarded_rather_than_acted_on(tmp_path):
    """It can only ever switch a source *on*, so the worst a bad file can do is
    nothing. Confirm it also does not raise, since helper/check calls this
    before it does anything else."""
    note = tmp_path / "restore.json"
    note.write_text("not json at all")
    assert repos.restore_remembered(str(note)) == []
    assert not note.exists()
