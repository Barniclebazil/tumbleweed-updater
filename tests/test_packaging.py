"""The polkit policy, paths.py and the installer must name the same files.

An action whose exec.path does not exist simply fails at pkexec time, and a
helper with no action cannot be elevated at all, so keep the three in step.
"""

import re
import xml.etree.ElementTree as ET
from pathlib import Path

from tumbleweed_updater import paths

REPO_ROOT = Path(__file__).resolve().parent.parent
POLICY = REPO_ROOT / "data" / "org.opensuse.tumbleweedupdater.policy"
INSTALL_SH = REPO_ROOT / "packaging" / "install.sh"
_EXEC_PATH = "org.freedesktop.policykit.exec.path"


def _actions() -> dict[str, str]:
    root = ET.parse(POLICY).getroot()
    out = {}
    for action in root.findall("action"):
        annotations = {a.get("key"): a.text for a in action.findall("annotate")}
        out[action.get("id")] = annotations[_EXEC_PATH]
    return out


def _allow_active(action_id: str) -> str:
    root = ET.parse(POLICY).getroot()
    for action in root.findall("action"):
        if action.get("id") == action_id:
            return action.find("defaults").find("allow_active").text
    raise AssertionError(f"no such action: {action_id}")


def test_every_action_points_at_a_helper_in_the_repo():
    for action_id, path in _actions().items():
        assert path.startswith(paths.LIBEXEC_DIR + "/"), action_id
        assert (REPO_ROOT / "helper" / Path(path).name).is_file(), action_id


def test_every_helper_path_constant_has_an_action():
    declared = set(_actions().values())
    for constant in (
        paths.HELPER_CHECK,
        paths.HELPER_SET_INTERVAL,
        paths.HELPER_RUN_UPDATE,
        paths.HELPER_SNAPSHOTS,
        paths.HELPER_SNAPSHOTS_MANAGE,
    ):
        assert constant in declared, constant


def test_action_id_constants_match_the_policy():
    ids = set(_actions())
    for constant in (
        paths.ACTION_CHECK,
        paths.ACTION_SET_INTERVAL,
        paths.ACTION_UPDATE,
        paths.ACTION_SNAPSHOTS,
        paths.ACTION_SNAPSHOTS_MANAGE,
    ):
        assert constant in ids, constant


def test_the_installer_installs_every_helper_an_action_names():
    script = INSTALL_SH.read_text(encoding="utf-8")
    for path in _actions().values():
        name = Path(path).name
        assert re.search(rf"install -m755 helper/{re.escape(name)}\b", script), name


def test_destructive_actions_do_not_cache_their_authorisation():
    """auth_admin_keep stays valid for minutes. Anything that changes the
    system irreversibly has to ask every time."""
    assert _allow_active(paths.ACTION_SNAPSHOTS_MANAGE) == "auth_admin"
    # The read-only ones may keep it: check changes nothing at all, and the
    # snapshots dialog re-lists after every operation.
    assert _allow_active(paths.ACTION_CHECK) == "yes"
    assert _allow_active(paths.ACTION_SNAPSHOTS) == "auth_admin_keep"
