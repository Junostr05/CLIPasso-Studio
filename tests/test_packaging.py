"""The version number is kept in one place (clipasso_studio/__init__.py); the packaging reads it."""

import re
from pathlib import Path

import clipasso_studio

ROOT = Path(__file__).resolve().parent.parent


def test_version_is_kept_in_one_place():
    assert re.fullmatch(r"\d+\.\d+\.\d+((a|b|rc)\d+)?", clipasso_studio.__version__)  # (PEP 440: 3.1.0b1)
    pyproject = (ROOT / "pyproject.toml").read_text(encoding="utf-8")
    assert 'dynamic = ["version"]' in pyproject
    assert not re.search(r'^version\s*=\s*"', pyproject, re.M)
    iss = (ROOT / "packaging" / "installer.iss").read_text(encoding="utf-8")
    assert not re.search(r'#define AppVersion "', iss)
    assert not (ROOT / "packaging" / "version_info.txt").exists()


def test_version_info_template_is_filled_like_the_spec():
    info = (ROOT / "packaging" / "version_info.in").read_text(encoding="utf-8")
    assert "{version}" in info and "{vtuple}" in info
    filled = info.replace("{version}", "3.1.4").replace("{vtuple}", str((3, 1, 4, 0)))
    assert "filevers=(3, 1, 4, 0)" in filled and "'ProductVersion', '3.1.4'" in filled
    spec = (ROOT / "packaging" / "clipasso_studio.spec").read_text(encoding="utf-8")
    assert "version_info.in" in spec


def _pins(path: Path) -> dict[str, str]:
    out = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        m = re.match(r"([A-Za-z0-9_.\-]+)==([^\s\;]+)", line.strip())
        if m:
            out[m.group(1).lower().replace("_", "-")] = m.group(2)
    return out


def test_lock_files_match_the_requirements():
    """Every exact pin of the requirements is in the release lock files (run tools/lock_requirements.py)."""
    req = ROOT / "requirements"
    for ed in ("cpu", "gpu"):
        lock = _pins(req / f"lock-{ed}.txt")
        assert lock, ed
        for name in ("app.txt", "build.txt", f"torch-{ed}.txt"):
            for pkg, ver in _pins(req / name).items():
                assert pkg in lock, (ed, pkg)
                assert lock[pkg].split("+")[0] == ver, (ed, pkg, lock[pkg], ver)


def test_installer_matches_the_app():
    """The uninstaller finds the app data and the files the app writes for it; both editions can be
    installed side by side (own shortcut names); an update removes the libraries of the old version."""
    from clipasso_studio.gui import storage, updates

    raw = (ROOT / "packaging" / "installer.iss").read_bytes()
    iss = raw.decode("utf-8")
    if any(ord(c) > 127 for c in iss):
        assert raw.startswith(b"\xef\xbb\xbf")  # ISCC reads UTF-8 only with a BOM (German texts)
    assert re.search(r'#define AppDataName "([^"]+)"', iss).group(1) == clipasso_studio.APP_ID
    assert f"AppGuid = '{updates.APP_GUID}'" in iss and "AppId={" + updates.APP_GUID + "_{#Edition}" in iss
    assert storage.MODELS_LOCATION in iss and storage.OUTPUT_LOCATION in iss
    assert 'Type: filesandordirs; Name: "{app}\\_internal"' in iss
    assert '#define ShortcutName "CLIPasso Studio GPU"' in iss and 'Name: "{autodesktop}\\{#ShortcutName}"' in iss
