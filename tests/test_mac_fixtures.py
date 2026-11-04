"""The test data of the Mac app's Swift package (macos/Tests/StudioCoreTests/Fixtures) is made by the Python side
(tools/make_mac_fixtures.py) – never by hand – and is current: made again, every file is the same."""

from __future__ import annotations

import filecmp
import importlib.util
import json
import os
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
FIXTURES = ROOT / "macos" / "Tests" / "StudioCoreTests" / "Fixtures"


def _generator():
    spec = importlib.util.spec_from_file_location("make_mac_fixtures", ROOT / "tools" / "make_mac_fixtures.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _files(root: Path) -> list[str]:
    return sorted(str(p.relative_to(root)).replace(os.sep, "/") for p in root.rglob("*") if p.is_file())


def _same_pixels(a: Path, b: Path) -> bool:
    """Qt's drawing (export/render/*.png) may differ by a step of a channel between platforms; nothing more."""
    from PIL import Image, ImageChops

    with Image.open(a) as x, Image.open(b) as y:
        if x.size != y.size or x.mode != y.mode:
            return False
        return max(hi for _, hi in ImageChops.difference(x, y).getextrema()) <= 2


def test_fixtures_are_current(tmp_path, user_data):
    out = tmp_path / "Fixtures"
    _generator().build(out)
    assert _files(out) == _files(FIXTURES)
    different = [f for f in _files(out) if not (_same_pixels(out / f, FIXTURES / f) if f.startswith("export/render/")
                                                else filecmp.cmp(out / f, FIXTURES / f, shallow=False))]
    assert different == [], "run: python tools/make_mac_fixtures.py"


def test_fixture_jobs_read_in_python():
    expected = json.loads((FIXTURES / "jobs_expected.json").read_text(encoding="utf-8"))
    assert set(expected) == {"done_clipasso", "interrupted_swiftsketch", "scenesketch_matrix", "windows_paths",
                             "old_2x"}
    assert expected["done_clipasso"]["state"] == "done" and expected["done_clipasso"]["title"]
    assert expected["interrupted_swiftsketch"]["state"] == "interrupted"
    assert expected["interrupted_swiftsketch"]["progress"] == [1, 4]
    assert expected["windows_paths"]["target"].startswith("C:\\Users\\")
    assert expected["windows_paths"]["best_svg"].startswith("{jobs}/windows_paths/")  # found again by rebase
    assert expected["old_2x"]["favourite"] is True


def test_check_swift_meta_tool(tmp_path):
    """tools/check_swift_meta.py (run after ``swift test``, which leaves the meta.json it wrote and what Python
    should read from it) says yes for a folder that reads right and no for one that does not."""
    import subprocess
    import sys

    from clipasso_studio.engine import jobs

    good = tmp_path / "export" / "meta_roundtrip"
    good.mkdir(parents=True)
    want = {"favourite": True, "title": "Kamel am Abend ✏️", "tags": ["Tier", "Wüste"], "ratings": {"a": 1}}
    jobs.write_meta(str(good), **want)
    (good / "expected.json").write_text(json.dumps(want, ensure_ascii=False), encoding="utf-8")
    tool = [sys.executable, str(ROOT / "tools" / "check_swift_meta.py")]
    assert subprocess.run(tool + [str(tmp_path / "export")], capture_output=True).returncode == 0
    (good / "expected.json").write_text(json.dumps({**want, "title": "anders"}), encoding="utf-8")
    bad = subprocess.run(tool + [str(tmp_path / "export")], capture_output=True, text=True)
    assert bad.returncode == 1 and "title" in bad.stdout
    assert subprocess.run(tool + [str(tmp_path / "nothing")], capture_output=True).returncode == 2
    (good / "expected.json").write_text(json.dumps(want, ensure_ascii=False), encoding="utf-8")
    (good / "meta.json").write_text(json.dumps(want), encoding="utf-8")  # the same data, not as Python writes it
    other = subprocess.run(tool + [str(tmp_path / "export")], capture_output=True, text=True)
    assert other.returncode == 1 and "bytes" in other.stdout
