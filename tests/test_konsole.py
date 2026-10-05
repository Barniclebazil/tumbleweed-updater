"""Reading Konsole's default profile: its colour scheme and its font.

The scheme in tests/fixtures/konsole is the real "Ubuntu Breeze" scheme from
the machine this was written on (Konsole 26.08), copied as it was. The
konsolerc below starts with a key before any section, as that machine's
does, which Python's configparser refuses.
"""

import shutil
from pathlib import Path

import pytest

from tumbleweed_updater.konsole import read_konsole, watched_paths
from tumbleweed_updater.termthemes import THEMES

FIXTURES = Path(__file__).parent / "fixtures" / "konsole"


@pytest.fixture
def dirs(tmp_path, monkeypatch):
    config = tmp_path / "config"
    home_data = tmp_path / "data"
    system_data = tmp_path / "system"
    for d in (config, home_data / "konsole", system_data / "konsole"):
        d.mkdir(parents=True)
    monkeypatch.setenv("XDG_CONFIG_HOME", str(config))
    monkeypatch.setenv("XDG_DATA_HOME", str(home_data))
    monkeypatch.setenv("XDG_DATA_DIRS", str(system_data))
    return config, home_data / "konsole", system_data / "konsole"


def _konsolerc(config, profile):
    (config / "konsolerc").write_text(
        f"MenuBar=Disabled\n\n[Desktop Entry]\nDefaultProfile={profile}\n\n"
        "[UiSettings]\nColorScheme=\n"
    )


def _profile(where, name, scheme=None, font=None, parent="FALLBACK/"):
    lines = ["[Appearance]"]
    if scheme:
        lines.append(f"ColorScheme={scheme}")
    if font:
        lines.append(f"Font={font}")
    lines += ["", "[General]", f"Name={name}", f"Parent={parent}", ""]
    (where / f"{name}.profile").write_text("\n".join(lines))


def test_the_whole_chain_gives_konsoles_scheme_and_font(dirs):
    config, home, _system = dirs
    shutil.copy(FIXTURES / "Ubuntu Breeze.colorscheme", home)
    _konsolerc(config, "Mine.profile")
    _profile(home, "Mine", "Ubuntu Breeze", "Ubuntu Mono,13,-1,5,400,0,0,0,0,0,0,0,0,0,0,1,,0,0")

    k = read_konsole()

    assert k.scheme == "Ubuntu Breeze"
    assert (k.font_family, k.font_size) == ("Ubuntu Mono", 13)
    assert k.note is None
    assert (k.theme.bg, k.theme.fg) == ("#300a24", "#eeeeee")
    assert k.theme.colours == (
        "#383a42", "#e4564a", "#50a050", "#c4a000",
        "#5283c2", "#7550a4", "#0a96b4", "#fafafa",
        "#1c1a24", "#f83636", "#50c850", "#de6602",
        "#005ce8", "#ba0eb8", "#00aac8", "#ffffff",
    )


def test_what_a_profile_leaves_out_comes_from_its_parent(dirs):
    config, home, system = dirs
    shutil.copy(FIXTURES / "Ubuntu Breeze.colorscheme", system)
    _profile(system, "Base", "Ubuntu Breeze", "Hack,10.5,-1")
    _profile(home, "Mine", font=None, parent="Base.profile")
    _konsolerc(config, "Mine.profile")

    k = read_konsole()

    assert k.scheme == "Ubuntu Breeze"
    assert (k.font_family, k.font_size) == ("Hack", 11)


def test_no_konsole_settings_at_all_is_konsoles_own_default(dirs):
    k = read_konsole()
    assert k.scheme == "Breeze"
    assert k.theme == THEMES["breeze"]
    assert (k.font_family, k.font_size) == ("", None)
    assert k.note is None


def test_a_built_in_scheme_with_a_theme_here_uses_it(dirs):
    config, home, _system = dirs
    _konsolerc(config, "Mine.profile")
    _profile(home, "Mine", "SolarizedLight")
    k = read_konsole()
    assert k.theme == THEMES["solarized-light"]
    assert k.note is None


def test_a_built_in_scheme_that_cannot_be_read_says_so(dirs):
    config, home, _system = dirs
    _konsolerc(config, "Mine.profile")
    _profile(home, "Mine", "DarkPastels")
    k = read_konsole()
    assert k.scheme == "DarkPastels"
    assert k.theme == THEMES["breeze"]
    assert "DarkPastels" in k.note and "Breeze" in k.note


def test_a_broken_scheme_falls_back_without_failing(dirs):
    config, home, _system = dirs
    (home / "Bad.colorscheme").write_text("[Background]\nColor=nonsense\n")
    (home / "Binary.colorscheme").write_bytes(b"\xff\xfe\x00junk")
    _konsolerc(config, "Mine.profile")
    for scheme in ("Bad", "Binary"):
        _profile(home, "Mine", scheme)
        k = read_konsole()
        assert k.theme == THEMES["breeze"], scheme
        assert scheme in k.note


def test_hex_colours_and_missing_bright_ones_are_read(dirs):
    config, home, _system = dirs
    body = ["[Background]\nColor=#102030\n", "[Foreground]\nColor=200,201,202\n"]
    body += [f"[Color{n}]\nColor={n},{n},{n}\n" for n in range(8)]
    (home / "Plain.colorscheme").write_text("\n".join(body))
    _konsolerc(config, "Mine.profile")
    _profile(home, "Mine", "Plain")

    k = read_konsole()

    assert (k.theme.bg, k.theme.fg) == ("#102030", "#c8c9ca")
    assert k.theme.colours[:8] == k.theme.colours[8:]


def test_a_font_given_in_pixels_keeps_the_family_only(dirs):
    config, home, _system = dirs
    _konsolerc(config, "Mine.profile")
    _profile(home, "Mine", font="Hack,-1,14,5,400")
    k = read_konsole()
    assert (k.font_family, k.font_size) == ("Hack", None)


def test_the_watched_folders_are_the_ones_that_exist(dirs):
    config, home, system = dirs
    assert watched_paths() == [str(config), str(home), str(system)]
    shutil.rmtree(system)
    assert str(system) not in watched_paths()
