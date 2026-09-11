"""Parser tests. The JSON fixture mirrors `snapper --jsonout list`'s shape:
client/snapper/cmd-list.cc nests snapshots under the config name and uses
hyphenated keys (e.g. "pre-number"), not the CLI's underscored ones."""

from tumbleweed_updater.snapshots import parse_snapper_list_json, parse_snapper_status

LIST_JSON = """
{
  "root": [
    {
      "subvolume": "/", "number": 1, "default": true, "active": false,
      "type": "single", "pre-number": null, "date": "2026-09-01 08:00:00",
      "user": "root", "used-space": 0, "cleanup": "number",
      "description": "first root filesystem", "userdata": null
    },
    {
      "subvolume": "/", "number": 30, "default": false, "active": false,
      "type": "pre", "pre-number": null, "date": "2026-09-11 17:39:00",
      "user": "root", "used-space": 12345, "cleanup": "number",
      "description": "zypp(zypper)", "userdata": {"important": "yes"}
    },
    {
      "subvolume": "/", "number": 31, "default": true, "active": true,
      "type": "post", "pre-number": 30, "date": "2026-09-11 17:41:00",
      "user": "root", "used-space": 67890, "cleanup": "number",
      "description": "zypp(zypper)", "userdata": null
    }
  ]
}
"""

STATUS_TEXT = """\
c..... /etc/foo.conf
+..... /usr/bin/newthing
-..... /usr/bin/oldthing
"""


def test_parses_all_snapshots_across_configs():
    res = parse_snapper_list_json(LIST_JSON)
    assert res.error is None
    numbers = {s.number: s for s in res.snapshots}
    assert set(numbers) == {1, 30, 31}
    assert numbers[1].type == "single"
    assert numbers[1].pre_number is None
    assert numbers[30].type == "pre"
    assert numbers[31].type == "post"
    assert numbers[31].pre_number == 30
    assert numbers[31].description == "zypp(zypper)"
    # sorted ascending by number
    assert [s.number for s in res.snapshots] == [1, 30, 31]


def test_empty_output():
    res = parse_snapper_list_json("")
    assert res.error is None
    assert res.snapshots == []


def test_invalid_json_reports_error():
    res = parse_snapper_list_json("not json")
    assert res.error is not None
    assert res.snapshots == []


def test_unexpected_shape_reports_error():
    res = parse_snapper_list_json("[1, 2, 3]")
    assert res.error is not None


def test_parses_status_lines():
    changes = parse_snapper_status(STATUS_TEXT)
    assert [(c.status, c.path) for c in changes] == [
        ("c.....", "/etc/foo.conf"),
        ("+.....", "/usr/bin/newthing"),
        ("-.....", "/usr/bin/oldthing"),
    ]


def test_status_ignores_blank_lines():
    changes = parse_snapper_status("\n\nc..... /a\n\n")
    assert len(changes) == 1
    assert changes[0].path == "/a"
