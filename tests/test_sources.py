"""Parser tests. The XML fixtures mirror /usr/share/zypper/xml/xmlout.rnc."""

from tumbleweed_updater.sources import (
    Action,
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


def test_flatpak_parser():
    text = "Application\tVersion\tBranch\tOrigin\n" \
           "org.kde.Kdenlive\t24.12.0\tstable\tflathub\n" \
           "org.gimp.GIMP\t2.10.38\tstable\tflathub\n"
    refs = parse_flatpak_updates(text, "user")
    assert [r.ref_id for r in refs] == ["org.kde.Kdenlive", "org.gimp.GIMP"]
    assert refs[0].version == "24.12.0"
    assert refs[0].installation == "user"
