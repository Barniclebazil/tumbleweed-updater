"""What Konsole's default profile looks like: its colours and its font.

Qt-free on purpose (see the conventions in CLAUDE.md). Read from Konsole's own
files, the way Konsole finds them, measured on Konsole 26.08:

1. ``$XDG_CONFIG_HOME/konsolerc`` names the default profile under
   ``[Desktop Entry] DefaultProfile=Barrie.profile``.
2. Profiles and colour schemes are files in ``konsole/`` under
   ``$XDG_DATA_HOME`` first, then each of ``$XDG_DATA_DIRS``.
3. A profile has ``[Appearance] ColorScheme=Ubuntu Breeze`` and
   ``Font=Ubuntu Mono,13,-1,5,400,…`` (a QFont string), and anything it does
   not set comes from ``[General] Parent=``; ``FALLBACK/`` is Konsole's
   built-in profile, which uses Breeze and the system fixed-width font.
4. A scheme ``Ubuntu Breeze.colorscheme`` has ``[Background]``,
   ``[Foreground]``, ``[Color0]`` to ``[Color7]`` and ``[Color0Intense]`` to
   ``[Color7Intense]``, each with ``Color=48,10,36``.

The schemes Konsole ships (Breeze, Solarized and the rest) are compiled into
Konsole itself, not installed as files, so they cannot be read. Breeze and
Solarized Light have a theme of their own here; any other is shown as Breeze,
and says so.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from .termthemes import THEMES, Theme

_FALLBACK_PARENT = "FALLBACK/"
_MAX_PARENTS = 5
# Konsole's own schemes, by the name a profile uses for them.
_BUILT_IN = {"Breeze": "breeze", "SolarizedLight": "solarized-light"}


@dataclass(frozen=True)
class KonsoleLook:
    scheme: str  # the colour scheme's name, as Konsole shows it
    theme: Theme
    font_family: str  # "" for the system fixed-width font
    font_size: int | None  # None for the system fixed-width font's own size
    note: str | None = None  # a plain sentence when Breeze stands in


def _config_home() -> Path:
    return Path(os.environ.get("XDG_CONFIG_HOME") or Path.home() / ".config")


def data_dirs() -> list[Path]:
    """Where Konsole looks for profiles and schemes, in its order."""
    home = os.environ.get("XDG_DATA_HOME") or str(Path.home() / ".local/share")
    others = os.environ.get("XDG_DATA_DIRS") or "/usr/local/share:/usr/share"
    return [Path(d) / "konsole" for d in [home, *others.split(":")] if d]


def watched_paths() -> list[str]:
    """Directories whose changes can change what Konsole looks like.

    Directories rather than files: Konsole saves by writing a new file and
    renaming it over the old one, which a watch on the old file misses.
    """
    return [str(p) for p in [_config_home(), *data_dirs()] if p.is_dir()]


_Ini = dict[str, dict[str, str]]


def _read_ini(path: Path) -> _Ini | None:
    """A KDE config file as {section: {key: value}}.

    Not configparser: KDE's files can start with keys before any section
    (konsolerc here begins with ``MenuBar=Disabled``), which it refuses. Keys
    are case-sensitive, a repeated key keeps the last value, and a key with a
    KDE flag such as ``Color[$e]`` is read under its plain name.
    """
    try:
        text = path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return None
    sections: _Ini = {}
    current = sections.setdefault("", {})
    for raw in text.splitlines():
        line = raw.strip()
        if not line or line.startswith(("#", ";")):
            continue
        if line.startswith("[") and line.endswith("]"):
            current = sections.setdefault(line[1:-1], {})
            continue
        key, sep, value = line.partition("=")
        if sep:
            current[key.split("[", 1)[0].strip()] = value.strip()
    return sections


def _get(ini: _Ini | None, section: str, key: str) -> str:
    return (ini or {}).get(section, {}).get(key, "")


def _find(name: str, suffix: str) -> Path | None:
    if os.path.isabs(name):
        path = Path(name)
        return path if path.is_file() else None
    if not name.endswith(suffix):
        name += suffix
    for directory in data_dirs():
        path = directory / name
        if path.is_file():
            return path
    return None


def _profile_values() -> tuple[str | None, str | None]:
    """The default profile's colour scheme name and font, following Parent."""
    rc = _read_ini(_config_home() / "konsolerc")
    name = _get(rc, "Desktop Entry", "DefaultProfile")
    scheme = font = None
    for _ in range(_MAX_PARENTS):
        if not name or name == _FALLBACK_PARENT:
            break
        path = _find(name, ".profile")
        profile = _read_ini(path) if path else None
        if profile is None:
            break
        scheme = scheme or _get(profile, "Appearance", "ColorScheme") or None
        font = font or _get(profile, "Appearance", "Font") or None
        if scheme and font:
            break
        name = _get(profile, "General", "Parent")
    return scheme, font


def _colour(scheme: _Ini, section: str) -> str | None:
    value = _get(scheme, section, "Color")
    if value.startswith("#") and len(value) == 7:
        try:
            int(value[1:], 16)
        except ValueError:
            return None
        return value.lower()
    parts = value.split(",")
    if len(parts) < 3:
        return None
    try:
        r, g, b = (int(p) for p in parts[:3])
    except ValueError:
        return None
    if not all(0 <= c <= 255 for c in (r, g, b)):
        return None
    return f"#{r:02x}{g:02x}{b:02x}"


def _read_scheme(path: Path, name: str) -> Theme | None:
    ini = _read_ini(path)
    if ini is None:
        return None
    bg = _colour(ini, "Background")
    fg = _colour(ini, "Foreground")
    normal = [_colour(ini, f"Color{n}") for n in range(8)]
    bright = [_colour(ini, f"Color{n}Intense") for n in range(8)]
    if bg is None or fg is None or None in normal:
        return None
    bright = [b or n for b, n in zip(bright, normal)]
    return Theme(name, bg, fg, tuple(normal + bright))


def _font(value: str | None) -> tuple[str, int | None]:
    if not value:
        return "", None
    parts = value.split(",")
    family = parts[0].strip()
    try:
        size = float(parts[1])
    except (IndexError, ValueError):
        return family, None
    if size <= 0:  # -1: the font was given in pixels, not points
        return family, None
    return family, min(32, max(6, int(size + 0.5)))


def read_konsole() -> KonsoleLook:
    """What Konsole's default profile looks like now. Never raises."""
    scheme, font_value = _profile_values()
    family, size = _font(font_value)
    breeze = THEMES["breeze"]
    if not scheme:
        # Nothing chosen: Konsole uses its own default, which is Breeze.
        return KonsoleLook("Breeze", breeze, family, size)

    path = _find(scheme, ".colorscheme")
    if path is not None:
        theme = _read_scheme(path, scheme)
        if theme is not None:
            return KonsoleLook(scheme, theme, family, size)
        note = (
            f"Konsole's “{scheme}” colours could not be read, "
            "so Breeze's are shown."
        )
        return KonsoleLook(scheme, breeze, family, size, note)

    if scheme in _BUILT_IN:
        return KonsoleLook(scheme, THEMES[_BUILT_IN[scheme]], family, size)
    note = (
        f"Konsole's “{scheme}” colours are built into Konsole and cannot be "
        "read, so Breeze's are shown."
    )
    return KonsoleLook(scheme, breeze, family, size, note)
