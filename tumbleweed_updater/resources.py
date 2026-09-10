"""Locating bundled data files whether installed or run from a checkout."""

from __future__ import annotations

import os

_REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# (installed location, in-repo location) for each logical resource.
_SEARCH = [
    "/usr/share/tumbleweed-updater",
    os.path.join(_REPO_ROOT, "data"),
]


def find(relative: str) -> str | None:
    for base in _SEARCH:
        candidate = os.path.join(base, relative)
        if os.path.exists(candidate):
            return candidate
    return None


def icon_file(name: str) -> str | None:
    # Prefer an installed themed icon, then our bundled copy.
    themed = f"/usr/share/icons/hicolor/scalable/apps/{name}.svg"
    if os.path.exists(themed):
        return themed
    return find(os.path.join("icons", f"{name}.svg"))


def style_icon_file(style: str) -> str | None:
    """Path to the SVG for a tray icon style (data/icons/styles/<style>.svg)."""
    return find(os.path.join("icons", "styles", f"{style}.svg"))
