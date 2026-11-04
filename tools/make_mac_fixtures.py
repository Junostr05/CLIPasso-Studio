"""Make the test data of the Mac app's Swift package from the Python side – never by hand.

    python tools/make_mac_fixtures.py [--out macos/Tests/StudioCoreTests/Fixtures]

Writes, reproducibly (a fixed time, fixed seeds, LF line ends):

- ``schema.json``, ``models.json`` – the exports of ``clipasso_studio.headless`` (the app version as "fixture")
- ``conditions.json`` – settings (a method's defaults with ``changes``) and what Python decides for them: the
  parameters' rules (``enabled``, one "1" / "0" per parameter in ``ruled``) and ``num_strokes``
- ``presets.json`` – settings and the preset the studio shows for them (param_panel._detect_preset: the first one
  whose values all match, else none – "custom")
- ``versions.json`` – version pairs and what gui/updates.is_newer decides for them
- ``edit/`` – ``strokes.json``: what gui/strokes.py (the eraser and the pen) makes of the ``svg/`` sketches and of
  ``odd.svg`` and ``empty.svg``
- ``image_files.json`` – a folder of pictures and the images gui/drop.py takes from it (the folder, with its
  subfolders, and as dropped)
- ``settings.json`` – the app settings as the Python app writes them
- ``pyjson.json`` – values with ``json.dumps(…)`` and ``json.dumps(…, indent=2)`` (``ensure_ascii=False``), and
  ``json.dumps(…, indent=2)`` as written by default (umlauts as ``\u00fc``: job.json, job_state.json, result.json)
- ``jobs/`` – job folders built with engine/jobs.py, their paths as they would be on a Mac
  (``/Users/studio/…``) or on Windows (``C:\\Users\\Jürgen\\…``), and ``jobs_expected.json``: what
  ``jobs.job_summary`` reads from each (paths inside the fixtures as ``{jobs}/…``)
- ``svg/`` – sketches written by engine/svg_io.py and ``svg_expected.json``: what Python reads from them;
  ``paths_expected.json``: path data and what engine/svg_path.py reads from it
- ``export/`` – ``restyle.json``: SVGs as gui/export.restyle_svg changes them (colour, width, background), and
  ``render/*.png``: the ``svg/`` sketches as the studio exports them (gui/export.export_png, 256 px, Qt). Qt's
  pixels can differ by a step between platforms, so the test compares these by pixel, not by byte

``tests/test_mac_fixtures.py`` checks that the committed files are current.
"""

from __future__ import annotations

import argparse
import json
import math
import os
import random
import shutil
import sys
import tempfile
import time
import xml.etree.ElementTree as ET
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

DEFAULT_OUT = ROOT / "macos" / "Tests" / "StudioCoreTests" / "Fixtures"
FIXED_TIME = time.struct_time((2026, 3, 14, 15, 9, 26, 5, 73, 0))
MAC_OUTPUT, MAC_PICTURES = "/Users/studio/Documents/CLIPasso Studio", "/Users/studio/Pictures"
WIN_OUTPUT, WIN_PICTURES = "C:\\Users\\Jürgen\\Documents\\CLIPasso Studio", "C:\\Users\\Jürgen\\Pictures"
CONDITION_CASES = 200  # per method

PYJSON_VALUES = [
    None, True, False, 0, -7, 2 ** 53, -(2 ** 63), 2 ** 63 - 1,
    0.1, -2.5, 100.0, 1e-05, 0.0001, 1e15, 1234567890123456.0, 1e16, 12345678901234567890.0, 5e-324,
    1.7976931348623157e308, 3.141592653589793, 123456789.123, 1.5e-07,
    "", "Bild Ä ö ü ß", "Emoji ✏️🦒", "„Tiere“ and \"quotes\" \\ / \n\t\r\b\f \u0001 \u001f \u007f \u2028",
    [], {}, [1, [2, [3, {}]]], {"b": 1, "a": [True, None], "ü": {"x": ""}},
    {"favourite": True, "title": "Kamel am Abend – Skizze ✏️", "notes": "Zeile 1\nZeile 2", "tags": ["Tier", "Wüste"],
     "albums": ["Tiere"], "ratings": {"Kamel_16strokes_seed0": 1, "Kamel_16strokes_seed1000": -1}},
]


def write_json(path: Path, data, indent: int | None = 1, ensure_ascii: bool = False) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes((json.dumps(data, indent=indent, ensure_ascii=ensure_ascii) + "\n").encode("utf-8"))


# ---------------------------------------------------------------------------------------------- schema, rules, JSON
def _rule_keys(rule: dict) -> set[str]:
    keys = {rule["key"]} if "key" in rule else set()
    for part in rule.get("of", ()):
        keys |= _rule_keys(part)
    return keys


def _random_changes(method: str, rng: random.Random) -> dict:
    """Random values for the keys the rules of ``method`` read (the others keep their defaults)."""
    from clipasso_studio import settings_schema as schema

    keys = set()
    for p in schema.params_for(method):
        if p.enabled_if is not None:
            keys |= _rule_keys(p.enabled_if.to_json())
    keys |= {"num_paths", "num_strokes", "one_line"}  # (num_strokes)
    changes = {}
    for p in schema.params_for(method):
        if p.key not in keys:
            continue
        if p.kind == "bool":
            changes[p.key] = rng.random() < 0.5
        elif p.kind == "choice":
            changes[p.key] = rng.choice(p.choices)
        elif p.kind == "flags":
            changes[p.key] = rng.choice(("none",) + tuple(p.choices))
        elif p.kind in ("int", "float") and p.minimum is not None:
            value = rng.choice((p.minimum, p.default, p.maximum, 0, 1, 2))
            changes[p.key] = int(value) if p.kind == "int" else float(value)
    return changes


def conditions() -> dict:
    """Per method its parameters with a rule (``ruled``), and settings (the method's defaults with ``changes``) with
    what Python decides for them: ``enabled`` ("1" / "0" per ruled parameter, in that order) and ``num_strokes``."""
    from clipasso_studio import settings_schema as schema

    rng = random.Random(0)
    ruled = {m: [p.key for p in schema.params_for(m) if p.enabled_if is not None] for m in schema.METHODS}
    cases = []
    for method in schema.METHODS:
        for i in range(CONDITION_CASES):
            changes = {} if i == 0 else _random_changes(method, rng)
            s = {**schema.default_settings(method), **changes}
            enabled = "".join("1" if schema.param(method, key).enabled_if(s) else "0" for key in ruled[method])
            cases.append({"method": method, "changes": changes, "num_strokes": schema.num_strokes(s),
                          "enabled": enabled})
    return {"ruled": ruled, "cases": cases}


VERSION_PAIRS = (
    ("4.3.0", "4.2.9"), ("v4.3.0", "4.3.0"), ("4.3.0b2", "4.3.0b1"), ("4.3.0", "4.3.0b9"), ("4.3.0-beta.1", "4.2.9"),
    ("4.3.0rc1", "4.3.0b4"), ("4.10.0", "4.9.0"), ("4.3", "4.3.0"), ("5", "4.99.99"), ("v4.3.0a1", "4.3.0"),
    ("nonsense", "4.3.0"), ("4.2.9", "4.3.0"), ("v4.3.1", "v4.3.1"),
)


def version_cases() -> list[dict]:
    """gui/updates.parse_version and is_newer on version pairs (the Mac app announces updates the same way)."""
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from clipasso_studio.gui import updates

    return [{"latest": a, "current": b, "newer": updates.is_newer(a, b), "parsed": list(updates.parse_version(a))}
            for a, b in VERSION_PAIRS]


def detected_preset(settings: dict) -> str | None:
    """gui/widgets/param_panel._detect_preset (without the user's own presets)."""
    from clipasso_studio import settings_schema as schema

    for name, values in schema.METHOD_PRESETS[schema.method_of(settings)].items():
        if all(settings.get(k) == v for k, v in values.items()):
            return name
    return None


def preset_cases() -> list[dict]:
    """Each method's start, every preset on it, and a preset with one of its values changed."""
    from clipasso_studio import settings_schema as schema

    cases = []
    for method in schema.METHODS:
        start = schema.start_settings(method)
        candidates = [start]
        for name, values in schema.METHOD_PRESETS[method].items():
            applied = schema.apply_preset(start, name)
            candidates.append(applied)
            key = next(iter(values))
            changed = dict(applied)
            p = schema.param(method, key)
            if p.kind == "bool":
                changed[key] = not applied[key]
            elif p.kind in ("int", "float"):
                changed[key] = applied[key] + (1 if p.kind == "int" else 0.125)
            elif p.choices:
                changed[key] = next(c for c in p.choices if c != applied[key])
            candidates.append(changed)
        cases += [{"method": method, "settings": c, "preset": detected_preset(c)} for c in candidates]
    return cases


def settings_file() -> str:
    """settings.json as the Python app writes it (gui/app_settings.py: json.dumps(data, indent=2)) – with an umlaut in
    a path, a key the Mac app does not know, the queue, albums and secrets (made-up values; the Mac app must never show
    them)."""
    data = {"settings_version": 3, "language": "de", "theme": "light",
            "output_dir": "/Users/Jürgen/Documents/CLIPasso Studio", "models_dir": "",
            "telegram_token": "123:made-up", "remote_token": "made-up-token", "remote_pin": "000000",
            "albums": ["Tiere", "Wüste"], "user_presets": [{"name": "Mein Stil", "method": "clipasso"}],
            "queue": [{"target": "/Users/Jürgen/Pictures/Kamel.png", "settings": {"method": "clipasso"}}],
            "a_key_of_a_newer_version": {"x": 1.5}}
    return json.dumps(data, indent=2)


def pyjson() -> list[dict]:
    return [{"value": v, "compact": json.dumps(v, ensure_ascii=False),
             "pretty": json.dumps(v, indent=2, ensure_ascii=False),
             "pretty_ascii": json.dumps(v, indent=2)} for v in PYJSON_VALUES]


# ---------------------------------------------------------------------------------------------------- sketches
def _scene(kind: str):
    import torch

    from clipasso_studio.engine.renderer import Path as Stroke
    from clipasso_studio.engine.renderer import ShapeGroup

    def stroke(ncp, pts, width, closed=False, fixed=False):
        return Stroke(ncp, torch.tensor(pts, dtype=torch.float32), width, is_closed=closed, fixed=fixed)

    if kind == "lines":
        shapes = [stroke([0], [[10.0, 20.0], [200.5, 30.25]], 1.5), stroke([1], [[5, 5], [100, 190], [210, 12]], 1.5)]
        colours = [[0, 0, 0, 1], [0, 0, 0, 1]]
    elif kind == "cubic":
        shapes = [stroke([2, 2], [[12, 200], [40, 120], [80, 90], [112, 110], [150, 130], [190, 60], [214, 20]], 2.25),
                  stroke([2], [[30.123456, 40.98765], [60, 10], [90, 70], [120.5, 33.3333]], 3.0, fixed=True)]
        colours = [[0.2, 0.4, 0.6, 0.6], [1, 0, 0, 0.35]]
    else:  # a closed stroke (the last segment comes back to the start) on a background
        shapes = [stroke([2, 2], [[50, 50], [80, 20], [140, 20], [170, 50], [150, 160], [70, 160]], 1.0, closed=True)]
        colours = [[0.1, 0.1, 0.1, 1]]
    groups = [ShapeGroup([i], stroke_color=torch.tensor(c, dtype=torch.float32)) for i, c in enumerate(colours)]
    return shapes, groups


def sketch_svg(kind: str, background: str | None = None) -> str:
    from clipasso_studio.engine import svg_io

    shapes, groups = _scene(kind)
    return svg_io.scene_to_svg(224, 224, shapes, groups, background=background)


def read_svg(text: str) -> dict:
    """What Python reads from a sketch: the canvas, the background and every stroke with its segments."""
    from clipasso_studio.engine.svg_path import parse_path_d

    root = ET.fromstring(text)
    ns = root.tag.split("}")[0] + "}" if root.tag.startswith("{") else ""
    background = next((el.get("fill") for el in root.iter(f"{ns}rect")), None)
    strokes = []
    for el in root.iter(f"{ns}path"):
        rgb = [int(c) for c in el.get("stroke")[4:-1].split(",")]
        for segs, closed in parse_path_d(el.get("d")):
            kinds = {2: "line", 3: "quad", 4: "cubic"}
            strokes.append({"start": list(segs[0][0]), "closed": bool(closed),
                            "segments": [{"kind": kinds[len(seg)], "points": [list(p) for p in seg[1:]]}
                                         for seg in segs],
                            "color": rgb, "opacity": float(el.get("stroke-opacity")),
                            "width": float(el.get("stroke-width")), "fixed": el.get("data-fixed") == "1"})
    return {"width": int(root.get("width")), "height": int(root.get("height")), "background": background,
            "strokes": strokes}


PATH_CASES = (
    "M 10 20 L 30 40", "M10,20l5,5h10v-3H0V1z", "M 0 0 C 1 2 3 4 5 6 S 7 8 9 10", "M 0 0 Q 1 1 2 0 T 4 0 t 2 0",
    "M 0 0 A 5 5 0 0 1 10 0", "M 0 0 A 5 10 30 1 0 10 10", "M 1 1 L 2 2 Z M 5 5 L 6 6", "M 0 0 L 1 0 L 1 1 Z",
    "M 3 3 4 4 5 5", "m 1 1 2 2 c 1 1 2 2 3 3 z", "M.5-.5L1e1 2E-1", "M 0 0 S 1 1 2 0 T 3 3",
)


def path_cases() -> list[dict]:
    """Path data with what engine/svg_path.parse_path_d makes of it (subpaths of segments of points)."""
    from clipasso_studio.engine.svg_path import parse_path_d

    return [{"d": d, "subpaths": [{"segments": [[list(p) for p in seg] for seg in segs], "closed": bool(closed)}
                                  for segs, closed in parse_path_d(d)]} for d in PATH_CASES]


def sketches(out: Path) -> None:
    expected = {}
    for name, kind, background in (("lines.svg", "lines", None), ("cubic.svg", "cubic", None),
                                   ("closed_bg.svg", "closed", "#fff8e7")):
        text = sketch_svg(kind, background)
        (out / "svg").mkdir(parents=True, exist_ok=True)
        (out / "svg" / name).write_bytes(text.encode("utf-8"))
        expected[name] = read_svg(text)
    write_json(out / "svg_expected.json", expected)
    write_json(out / "paths_expected.json", path_cases())


RESTYLE_CASES = (  # (sketch, stroke colour, width factor, background)
    ("lines.svg", None, 1.0, None), ("lines.svg", "#1a2b3c", 1.0, None), ("cubic.svg", None, 2.5, "#ffffff"),
    ("closed_bg.svg", "#ff0000", 0.5, None), ("closed_bg.svg", None, 1.0, "#000000"), ("cubic.svg", None, 0.3333, None),
)
RENDER_SIZE = 256


def exports(out: Path) -> None:
    """What the studio's export makes of the ``svg/`` sketches (needs PySide6: Qt draws the PNGs)."""
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PIL import Image

    from clipasso_studio.gui import export

    folder = out / "export"
    (folder / "render").mkdir(parents=True)
    cases = []
    for name, colour, scale, background in RESTYLE_CASES:
        svg = (out / "svg" / name).read_text(encoding="utf-8")
        cases.append({"svg": name, "stroke_color": colour, "width_scale": scale, "background": background,
                      "output": export.restyle_svg(svg, colour, scale, background)})
    write_json(folder / "restyle.json", cases)
    with tempfile.TemporaryDirectory() as tmp:
        for name in ("lines.svg", "cubic.svg", "closed_bg.svg"):
            qt = Path(tmp) / "qt.png"
            export.export_png(str(out / "svg" / name), str(qt), size=RENDER_SIZE)  # (white behind it)
            with Image.open(qt) as image:
                image.convert("RGB").save(folder / "render" / name.replace(".svg", ".png"), optimize=False)


# ----------------------------------------------------------------------------------------------- dropped images
IMAGE_TREE = (  # a folder of pictures as a user's might be ("/" at the end: an empty folder)
    "b.PNG", "a.jpg", "Notiz.txt", "c.HEIC", "Z.webp", "ä-Bild.png", ".versteckt.png", "Urlaub/2.jpg", "Urlaub/10.jpg",
    "Urlaub/Strand/1.tif", "urlaub2/x.gif", "_edited/e.png", "_pasted_2/p.png", ".git/g.png",
    "CLIPasso Studio/Kamel_job/job.json", "CLIPasso Studio/Kamel_job/input/Kamel.png",
    "CLIPasso Studio/laufend/job_state.json", "CLIPasso Studio/laufend/x.png", "CLIPasso Studio/Notizen/n.png", "Leer/",
)
IMAGE_DROP = ("a.jpg", "Notiz.txt", "Urlaub", "a.jpg", "Urlaub/2.jpg", "fehlt.png", "Leer")


def image_file_cases() -> dict:
    """gui/drop.image_files (a folder's own images, and with its subfolders) and dropped_images (files and folders
    as they are dropped) on a folder made of IMAGE_TREE – the paths relative to it."""
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PySide6.QtCore import QMimeData, QUrl

    from clipasso_studio.gui import drop

    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp) / "Bilder"
        for entry in IMAGE_TREE:
            path = root / entry
            if entry.endswith("/"):
                path.mkdir(parents=True, exist_ok=True)
            else:
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_bytes(b"")

        def relative(paths: list[str]) -> list[str]:
            return [Path(p).relative_to(root).as_posix() for p in paths]

        mime = QMimeData()
        mime.setUrls([QUrl.fromLocalFile(str(root / p)) for p in IMAGE_DROP])
        return {"tree": list(IMAGE_TREE), "flat": relative(drop.image_files(str(root))),
                "recursive": relative(drop.image_files(str(root), recursive=True)), "drop": list(IMAGE_DROP),
                "dropped": relative(drop.dropped_images(mime))}


# --------------------------------------------------------------------------------------------- editing sketches
EDIT_ODD = (  # a sketch as hand-written SVG may be: shifted viewBox, sizes in px, nested groups, a path in the root
    '<svg xmlns="http://www.w3.org/2000/svg" width="300px" height="200px" viewBox="-10, 5 300 200">\n'
    '  <!-- a comment -->\n'
    '  <rect width="100%" height="100%" fill="#fff8e7" />\n'
    '  <path d="M 0 10 L 100 10 M 120 10 L 200 60" stroke="rgb(0, 0, 0)" />\n'
    '  <g><g transform="none">\n'
    '    <path d="M 20 150 C 60 100 100 200 140 150" stroke-width=" 4 " stroke="rgb(0, 0, 0)"><title>t</title></path>\n'
    '  </g>\n'
    '  <path d="M 250 20 Q 260 150 270 190 Z" stroke-width="2.5" data-fixed="true" stroke="rgb(0, 0, 0)" />\n'
    '  </g>\n'
    '</svg>\n')
EDIT_EMPTY = '<svg xmlns="http://www.w3.org/2000/svg" width="224" height="224" viewBox="0 0 224 224"><defs /></svg>'
EDIT_STROKES = (  # (points, width, fixed)
    ([(20 + 9 * i, 100 + 15 * (i % 2)) for i in range(20)], None, True),
    ([(10 + 4 * i, 50 + 0.3 * math.sin(i)) for i in range(40)], None, True),
    ([(10, 10), (10, 10), (40.5, 40.25), (40.5, 40.25), (70.125, 10)], None, True),
    ([(5, 5), (5, 5)], None, True),
    ([(15.3333, 80.6667), (150.75, 120.125)], 2.5, False),
)


def edit_cases(out: Path) -> list[dict]:
    """gui/strokes.py on the ``svg/`` sketches and two odd ones (``edit/``): their count, fixed strokes and viewBox,
    the stroke hit at points of a grid and at each stroke's start, strokes removed, strokes drawn with the pen, and
    every stroke freed again."""
    from clipasso_studio.gui import brush, strokes

    (out / "edit").mkdir(parents=True, exist_ok=True)
    (out / "edit" / "odd.svg").write_text(EDIT_ODD, encoding="utf-8")
    (out / "edit" / "empty.svg").write_text(EDIT_EMPTY, encoding="utf-8")
    cases = []
    for name in ("svg/lines.svg", "svg/cubic.svg", "svg/closed_bg.svg", "edit/odd.svg", "edit/empty.svg"):
        svg = (out / name).read_text(encoding="utf-8")
        x0, y0, w, h = strokes.view_box(svg)
        index = strokes.StrokeIndex(svg)
        points = [(x0 + w * i / 8, y0 + h * j / 8, tol) for i in range(9) for j in range(9) for tol in (2.0, 9.0)]
        for line in index.lines:
            if line and line[0]:
                points.append((line[0][0][0] + 0.25, line[0][0][1] - 0.5, 1.0))
        n = len(index)
        cases.append({
            "svg": name, "count": strokes.count(svg), "fixed": strokes.fixed_count(svg), "view_box": [x0, y0, w, h],
            "samples": [brush.sample(el, per_segment=12) for el in _path_ds(svg)],
            "hits": [{"x": x, "y": y, "tolerance": t, "index": index.hit(x, y, t)} for x, y, t in points],
            "removes": [{"indices": list(drop), "output": strokes.remove_strokes(svg, drop)}
                        for drop in ([0], [n - 1], list(range(n)), [n + 5]) if n],
            "appends": [{"points": [list(p) for p in pts], "width": width, "fixed": fixed,
                         "output": strokes.append_stroke(svg, pts, width, fixed)}
                        for pts, width, fixed in EDIT_STROKES],
            "unfixed": strokes.unfix(svg),
        })
    return cases


def _path_ds(svg: str) -> list[str]:
    import xml.etree.ElementTree as ET

    root = ET.fromstring(svg)
    ns = root.tag.split("}")[0] + "}" if root.tag.startswith("{") else ""
    return [el.get("d") or "" for el in root.iter(f"{ns}path")]


# --------------------------------------------------------------------------------------------------------- jobs
def _png(path: Path, colour) -> Path:
    """An 8×8 PNG of one colour – written byte by byte with stored (uncompressed) deflate blocks, so the file is the
    same on every platform whatever zlib it has."""
    import struct
    import zlib

    def chunk(kind: bytes, data: bytes) -> bytes:
        return struct.pack(">I", len(data)) + kind + data + struct.pack(">I", zlib.crc32(kind + data) & 0xFFFFFFFF)

    raw = b"".join(b"\0" + bytes(colour) * 8 for _ in range(8))
    png = (b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", 8, 8, 8, 2, 0, 0, 0))
           + chunk(b"IDAT", zlib.compress(raw, 0)) + chunk(b"IEND", b""))
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(png)
    return path


def _run(job_dir: Path, target: Path, settings: dict, seed: int, loss: float, score: float | None,
         kind: str = "lines"):
    from clipasso_studio import settings_schema as schema
    from clipasso_studio.engine import jobs

    name = jobs.run_name_for(str(target), settings, seed)
    run_dir = job_dir / name
    run_dir.mkdir(parents=True)
    (run_dir / "best_iter.svg").write_bytes(sketch_svg(kind).encode("utf-8"))
    _png(run_dir / "best_iter.png", (255, 255, 255))
    result = jobs.SeedResult(seed=seed, run_name=name, run_dir=str(run_dir), best_loss=loss, best_iter=400,
                             iterations_done=501, best_svg=str(run_dir / "best_iter.svg"), status="done",
                             method=schema.method_of(settings), clip_score=score, seconds=12.5)
    jobs.save_result(result)
    return result


def _job(output: Path, folder: str, target: Path, settings: dict) -> Path:
    from clipasso_studio.engine import jobs

    job_dir = output / folder
    job_dir.mkdir(parents=True)
    jobs.save_input(str(job_dir), str(target))
    jobs.write_state(str(job_dir), str(target), settings, "running")
    return job_dir


def build_jobs(output: Path, pictures: Path) -> None:
    from clipasso_studio import settings_schema as schema
    from clipasso_studio.engine import jobs

    camel, giraffe = _png(pictures / "Kamel.png", (200, 160, 90)), _png(pictures / "Giraffe.png", (220, 180, 60))

    s = schema.normalize({"method": "clipasso", "num_sketches": 3, "num_iter": 501})
    d = _job(output, "done_clipasso", camel, s)
    runs = [_run(d, camel, s, seed, loss, None, kind) for seed, loss, kind in
            ((0, 0.31, "lines"), (1000, 0.27, "cubic"), (2000, 0.35, "lines"))]
    jobs.finish_job(str(d), str(camel), s, runs)
    (d / runs[1].run_name / jobs.EDITED_FILE).write_bytes(sketch_svg("lines").encode("utf-8"))  # touched up
    jobs.write_meta(str(d), favourite=True, title="Kamel am Abend – Skizze ✏️", notes="Für das Album „Tiere“",
                    tags=["Tier", "Wüste"], albums=["Tiere"], ratings={runs[1].run_name: 1, runs[0].run_name: -1})

    s = schema.normalize({"method": "swiftsketch", "num_sketches": 4, "seed": 20})
    d = _job(output, "interrupted_swiftsketch", giraffe, s)
    _run(d, giraffe, s, 20, 0.0, 28.75, "cubic")
    jobs.set_status(str(d), "interrupted")

    s = schema.normalize({"method": "scenesketch", "layers": "8", "simplicity_levels": 4, "num_sketches": 1})
    d = _job(output, "scenesketch_matrix", camel, s)
    _run(d, camel, s, schema.scene_cell_id(8, 0), 0.5, 30.5, "cubic")
    _run(d, camel, s, schema.scene_cell_id(8, 4), 0.6, 27.25, "lines")
    jobs.set_status(str(d), "interrupted")

    s = schema.normalize({"method": "clipasso", "num_sketches": 2})
    d = _job(output, "windows_paths", giraffe, s)
    runs = [_run(d, giraffe, s, seed, loss, None) for seed, loss in ((0, 0.4), (1000, 0.3))]
    jobs.finish_job(str(d), str(giraffe), s, runs)
    jobs.write_meta(str(d), title="Giraffe – von Jürgens PC", tags=["Windows"])

    s = schema.normalize({"method": "clipasso", "num_sketches": 1})  # a job of CLIPasso Studio 2.x
    d = _job(output, "old_2x", camel, s)
    jobs.finish_job(str(d), str(camel), s, [_run(d, camel, s, 0, 0.29, None)])
    shutil.move(str(d / jobs.INPUT_DIR / "Kamel.png"), str(d / "source.png"))
    shutil.rmtree(d / jobs.INPUT_DIR)
    (d / jobs.STATE_FILE).unlink()
    summary = json.loads((d / "job.json").read_text(encoding="utf-8"))
    summary["favourite"] = True  # (2.x kept the favourite in job.json)
    (d / "job.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")


def _swap(value, swaps):
    if isinstance(value, dict):
        return {k: _swap(v, swaps) for k, v in value.items()}
    if isinstance(value, list):
        return [_swap(v, swaps) for v in value]
    if isinstance(value, str):
        for old, new, windows in swaps:
            if value.startswith(old):
                rest = value[len(old):].replace("\\", "/")  # (made on Windows: its separators)
                return new + (rest.replace("/", "\\") if windows else rest)
    return value


def copy_jobs(output: Path, pictures: Path, dest: Path) -> None:
    """The job folders into the fixtures, their absolute paths as on a Mac (or on Windows for windows_paths); JSON
    files written again the way Python writes them, with LF line ends."""
    for job_dir in sorted(output.iterdir()):
        windows = job_dir.name == "windows_paths"
        out_root, pic_root = (WIN_OUTPUT, WIN_PICTURES) if windows else (MAC_OUTPUT, MAC_PICTURES)
        swaps = [(str(output), out_root, windows), (str(pictures), pic_root, windows)]
        for src in sorted(p for p in job_dir.rglob("*") if p.is_file()):
            target = dest / src.relative_to(output)
            target.parent.mkdir(parents=True, exist_ok=True)
            if src.suffix == ".json":
                data = _swap(json.loads(src.read_text(encoding="utf-8")), swaps)
                meta = src.name == "meta.json"  # (write_meta keeps umlauts; the others escape them)
                target.write_bytes(json.dumps(data, indent=2, ensure_ascii=not meta).encode("utf-8"))
            else:
                target.write_bytes(src.read_bytes())


def _placeholder(value, root: str):
    if isinstance(value, dict):
        return {k: _placeholder(v, root) for k, v in value.items()}
    if isinstance(value, list):
        return [_placeholder(v, root) for v in value]
    if isinstance(value, str) and value.startswith(root):
        return "{jobs}" + value[len(root):].replace("\\", "/")
    return value


def expected_jobs(jobs_dir: Path) -> dict:
    from clipasso_studio.engine import jobs

    return {d.name: _placeholder(jobs.job_summary(str(d)), str(jobs_dir)) for d in sorted(jobs_dir.iterdir())}


# ----------------------------------------------------------------------------------------------------------- all
def build(out: Path) -> None:
    from clipasso_studio.headless import export

    if out.exists():
        shutil.rmtree(out)
    out.mkdir(parents=True)
    schema_data = export.export_schema()
    schema_data["app_version"] = "fixture"  # (not made again for every version)
    write_json(out / "schema.json", schema_data)
    write_json(out / "models.json", export.export_models())
    write_json(out / "conditions.json", conditions(), indent=None)
    write_json(out / "pyjson.json", pyjson())
    write_json(out / "presets.json", preset_cases(), indent=None)
    write_json(out / "versions.json", version_cases())
    write_json(out / "image_files.json", image_file_cases())
    (out / "settings.json").write_bytes(settings_file().encode("utf-8"))
    sketches(out)
    exports(out)
    write_json(out / "edit" / "strokes.json", edit_cases(out))
    real_strftime = time.strftime
    with tempfile.TemporaryDirectory() as tmp, \
            mock.patch.dict(os.environ, {"XDG_DATA_HOME": os.path.join(tmp, "data"),
                                         "LOCALAPPDATA": os.path.join(tmp, "data")}), \
            mock.patch("time.strftime", lambda fmt, t=None: real_strftime(fmt, FIXED_TIME)):
        output, pictures = Path(tmp) / "CLIPasso Studio", Path(tmp) / "Bilder"
        build_jobs(output, pictures)
        copy_jobs(output, pictures, out / "jobs")
    write_json(out / "jobs_expected.json", expected_jobs(out / "jobs"))


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--out", default=str(DEFAULT_OUT))
    args = parser.parse_args(argv)
    build(Path(args.out))
    print(f"fixtures written to {args.out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
