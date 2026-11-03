"""Make the test data of the Mac app's Swift package from the Python side – never by hand.

    python tools/make_mac_fixtures.py [--out macos/Tests/StudioCoreTests/Fixtures]

Writes, reproducibly (a fixed time, fixed seeds, LF line ends):

- ``schema.json``, ``models.json`` – the exports of ``clipasso_studio.headless`` (the app version as "fixture")
- ``conditions.json`` – settings (a method's defaults with ``changes``) and what Python decides for them: the
  parameters' rules (``enabled``, one "1" / "0" per parameter in ``ruled``) and ``num_strokes``
- ``pyjson.json`` – values with ``json.dumps(…)`` and ``json.dumps(…, indent=2)`` (``ensure_ascii=False``), and
  ``json.dumps(…, indent=2)`` as written by default (umlauts as ``\u00fc``: job.json, job_state.json, result.json)
- ``jobs/`` – job folders built with engine/jobs.py, their paths as they would be on a Mac
  (``/Users/studio/…``) or on Windows (``C:\\Users\\Jürgen\\…``), and ``jobs_expected.json``: what
  ``jobs.job_summary`` reads from each (paths inside the fixtures as ``{jobs}/…``)
- ``svg/`` – sketches written by engine/svg_io.py and ``svg_expected.json``: what Python reads from them;
  ``paths_expected.json``: path data and what engine/svg_path.py reads from it

``tests/test_mac_fixtures.py`` checks that the committed files are current.
"""

from __future__ import annotations

import argparse
import json
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


# --------------------------------------------------------------------------------------------------------- jobs
def _png(path: Path, colour) -> Path:
    from PIL import Image

    path.parent.mkdir(parents=True, exist_ok=True)
    Image.new("RGB", (8, 8), colour).save(path, format="PNG")
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
                rest = value[len(old):]
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
    sketches(out)
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
