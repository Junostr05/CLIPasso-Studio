"""The two layers of a SceneSketch cell: the background (its strokes outside the object) and the object. They are
told apart by the cell's ``object.svg`` – the object's strokes in scene coordinates, which appear unchanged in the
cell's sketch (also after the eraser: it only removes strokes). For the studio's layer switch, the phone and the
export "SVG · layers" (two Inkscape / Illustrator layers)."""

from __future__ import annotations

import os
import xml.etree.ElementTree as ET

from .strokes import _paths, remove_strokes

PARTS = ("all", "background", "object")
INKSCAPE = "http://www.inkscape.org/namespaces/inkscape"
ET.register_namespace("inkscape", INKSCAPE)


def object_strokes(run_dir: str | None) -> set[str] | None:
    """The ``d`` of every object stroke of the cell (None when the cell has no object layer)."""
    try:
        root = ET.parse(os.path.join(run_dir or "", "object.svg")).getroot()
    except (OSError, ET.ParseError):
        return None
    ds = {(el.get("d") or "").strip() for el in _paths(root)} - {""}
    return ds or None


def available(run_dir: str | None) -> bool:
    return object_strokes(run_dir) is not None


def part(svg: str, run_dir: str | None, which: str) -> str:
    """The sketch with only its background or only its object strokes ("all", or no object layer: unchanged).
    Strokes added with the pen count as background."""
    obj = object_strokes(run_dir) if which in ("background", "object") else None
    if obj is None:
        return svg
    root = ET.fromstring(svg)
    drop = [i for i, el in enumerate(_paths(root)) if ((el.get("d") or "").strip() in obj) == (which == "background")]
    return remove_strokes(svg, drop)


def layered(svg: str, run_dir: str | None, labels: tuple[str, str] = ("Background", "Object")) -> str:
    """The sketch with its strokes in two layers (groups Inkscape and Illustrator open as layers), the background
    below the object. Without an object layer every stroke is in the background layer."""
    obj = object_strokes(run_dir) or set()
    root = ET.fromstring(svg)
    ns = root.tag.split("}")[0] + "}" if root.tag.startswith("{") else ""
    paths = _paths(root)
    parents = {c: p for p in root.iter() for c in p}
    home = parents[paths[0]] if paths else root
    index = list(home).index(paths[0]) if paths else len(home)
    groups = {key: ET.Element(f"{ns}g", {"id": key, f"{{{INKSCAPE}}}groupmode": "layer",
                                         f"{{{INKSCAPE}}}label": label})
              for key, label in zip(("background", "object"), labels)}
    for el in paths:
        parents[el].remove(el)
        groups["object" if (el.get("d") or "").strip() in obj else "background"].append(el)
    home.insert(index, groups["object"])
    home.insert(index, groups["background"])
    return ET.tostring(root, encoding="unicode")
