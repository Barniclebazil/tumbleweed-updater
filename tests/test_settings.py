import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtWidgets import QApplication

from tumbleweed_updater.settings import (
    REBOOT_ACTIONS,
    Prefs,
    SettingsStore,
    dup_args_from_prefs,
)


@pytest.fixture(scope="module")
def app():
    return QApplication.instance() or QApplication([])


def test_dup_args_default_empty():
    assert dup_args_from_prefs(Prefs()) == []


def test_dup_args_all_toggles():
    p = Prefs(
        dup_non_interactive=True,
        dup_allow_vendor_change=True,
        dup_download_in_advance=True,
    )
    assert dup_args_from_prefs(p) == [
        "-y",
        "--auto-agree-with-licenses",
        "--allow-vendor-change",
        "--download",
        "in-advance",
    ]


def test_dup_args_dedupes_free_text():
    p = Prefs(dup_non_interactive=True, zypper_dup_args="-y --no-recommends")
    args = dup_args_from_prefs(p)
    assert args.count("-y") == 1
    assert "--no-recommends" in args


def test_settings_roundtrip(app, tmp_path, monkeypatch):
    monkeypatch.setenv("HOME", str(tmp_path))
    store = SettingsStore()
    original = Prefs(
        dup_allow_vendor_change=True,
        dup_non_interactive=True,
        dup_download_in_advance=True,
        cleanup_after_update=False,
        reboot_action="offer",
        icon_style="shield",
    )
    store.save(original)
    loaded = store.load()
    assert loaded.dup_allow_vendor_change is True
    assert loaded.dup_non_interactive is True
    assert loaded.dup_download_in_advance is True
    assert loaded.cleanup_after_update is False
    assert loaded.reboot_action == "offer"
    assert loaded.icon_style == "shield"


def test_reboot_action_falls_back_on_junk(app, tmp_path, monkeypatch):
    monkeypatch.setenv("HOME", str(tmp_path))
    store = SettingsStore()
    p = Prefs()
    p.reboot_action = "not-a-real-action"
    store.save(p)
    assert store.load().reboot_action in REBOOT_ACTIONS


def test_cleanup_default_is_on():
    assert Prefs().cleanup_after_update is True
    assert Prefs().dup_allow_vendor_change is False
    assert Prefs().dup_non_interactive is False
    assert Prefs().dup_download_in_advance is False
