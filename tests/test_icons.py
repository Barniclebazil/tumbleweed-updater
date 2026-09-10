import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtGui import QColor
from PySide6.QtWidgets import QApplication

from tumbleweed_updater import icons, resources
from tumbleweed_updater.settings import ICON_STYLES
from tumbleweed_updater.tray import TrayIcon, TrayState


@pytest.fixture(scope="module")
def app():
    return QApplication.instance() or QApplication([])


def test_every_style_has_an_svg():
    for style in ICON_STYLES:
        assert resources.style_icon_file(style), f"missing SVG for style {style}"


@pytest.mark.parametrize("style", list(ICON_STYLES))
def test_icons_render_for_each_style(app, style):
    assert not icons.idle_icon(style, QColor("#202020")).isNull()
    assert not icons.updates_icon(style).isNull()


def test_unknown_style_falls_back(app):
    # Should not raise and should still produce a usable icon.
    assert not icons.idle_icon("does-not-exist", QColor("#202020")).isNull()


def test_tray_reload_picks_up_new_style(app, tmp_path, monkeypatch):
    monkeypatch.setenv("HOME", str(tmp_path))

    from tumbleweed_updater.settings import SettingsStore

    store = SettingsStore()
    prefs = store.load()
    prefs.icon_style = "shield"
    store.save(prefs)

    tray = TrayIcon(store)
    tray.set_state(TrayState.IDLE, "ok")
    assert not tray.icon().isNull()

    prefs = store.load()
    prefs.icon_style = "package"
    store.save(prefs)
    tray.reload()
    assert not tray.icon().isNull()
