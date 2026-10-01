"""SVG export/import for stroke scenes (compatible with ``pydiffvg.save_svg`` output)."""

from __future__ import annotations

import re
import xml.etree.ElementTree as ET

import torch

from .renderer import Path, ShapeGroup
from .svg_path import parse_path_d

_NUM = r"[-+]?(?:\d+\.?\d*|\.\d+)(?:[eE][-+]?\d+)?"


def _fmt(v: float) -> str:
    return f"{float(v):.4f}".rstrip("0").rstrip(".")


def path_to_d(path: Path) -> str:
    pts = path.points.detach().cpu().tolist()
    parts = [f"M {_fmt(pts[0][0])} {_fmt(pts[0][1])}"]
    idx = 0
    ncp = path.num_control_points.tolist()
    for i, c in enumerate(ncp):
        c = int(c)
        seg_pts = []
        for k in range(1, c + 2):
            j = idx + k
            if path.is_closed and i == len(ncp) - 1 and j >= len(pts):
                j = 0
            seg_pts.append(pts[j])
        cmd = {0: "L", 1: "Q", 2: "C"}.get(c)
        if cmd is None:  # higher order: approximate with a polyline through the control points
            cmd = "L"
        parts.append(cmd + " " + " ".join(f"{_fmt(p[0])} {_fmt(p[1])}" for p in seg_pts))
        idx += c + 1
    if path.is_closed:
        parts.append("Z")
    return " ".join(parts)


def scene_to_svg(canvas_width, canvas_height, shapes, shape_groups, background: str | None = None,
                 stroke_color: tuple[int, int, int] | None = None, width_scale: float = 1.0,
                 min_opacity: float = 0.0) -> str:
    """Serialize a scene to SVG text.

    ``stroke_color``/``width_scale`` restyle all strokes (export options); strokes whose
    opacity is below ``min_opacity`` are skipped.
    """
    root = ET.Element("svg", {
        "version": "1.1",
        "xmlns": "http://www.w3.org/2000/svg",
        "width": str(int(canvas_width)),
        "height": str(int(canvas_height)),
        "viewBox": f"0 0 {int(canvas_width)} {int(canvas_height)}",
    })
    ET.SubElement(root, "defs")
    if background:
        ET.SubElement(root, "rect", {"width": "100%", "height": "100%", "fill": background})
    g = ET.SubElement(root, "g")
    for group in shape_groups:
        col = group.stroke_color.detach().cpu().tolist() if group.stroke_color is not None else [0, 0, 0, 1]
        opacity = min(max(col[3], 0.0), 1.0)
        if opacity < min_opacity:
            continue
        if stroke_color is not None:
            rgb = stroke_color
        else:
            rgb = tuple(int(round(min(max(c, 0.0), 1.0) * 255)) for c in col[:3])
        for sid in group.shape_ids.tolist():
            shape = shapes[int(sid)]
            width = float(shape.stroke_width.detach().cpu()) * width_scale
            ET.SubElement(g, "path", {
                "d": path_to_d(shape),
                "fill": "none",
                "stroke": f"rgb({rgb[0]}, {rgb[1]}, {rgb[2]})",
                "stroke-opacity": _fmt(opacity),
                "stroke-width": _fmt(width),
                "stroke-linecap": "round",
                "stroke-linejoin": "round",
            })
    ET.indent(root)
    return ET.tostring(root, encoding="unicode")


def save_svg(filename, canvas_width, canvas_height, shapes, shape_groups, **kwargs) -> None:
    with open(filename, "w", encoding="utf-8") as f:
        f.write(scene_to_svg(canvas_width, canvas_height, shapes, shape_groups, **kwargs))


# ----------------------------------------------------------------------------- loading


def _parse_color(value: str | None, opacity: float) -> list[float] | None:
    if value is None or value == "none":
        return None
    value = value.strip()
    rgb = [0.0, 0.0, 0.0]
    m = re.match(r"rgb\(\s*([^)]*)\)", value)
    if m:
        comps = [c.strip() for c in m.group(1).split(",")]
        rgb = [float(c[:-1]) / 100 if c.endswith("%") else float(c) / 255 for c in comps[:3]]
    elif value.startswith("#"):
        h = value[1:]
        if len(h) == 3:
            h = "".join(ch * 2 for ch in h)
        rgb = [int(h[i:i + 2], 16) / 255 for i in (0, 2, 4)]
    elif value == "white":
        rgb = [1.0, 1.0, 1.0]
    return rgb + [opacity]


def _style_dict(el: ET.Element) -> dict[str, str]:
    attrs = dict(el.attrib)
    style = attrs.pop("style", "")
    for item in style.split(";"):
        if ":" in item:
            k, v = item.split(":", 1)
            attrs[k.strip()] = v.strip()
    return attrs


def _float(v: str | None, default: float) -> float:
    if v is None:
        return default
    m = re.match(_NUM, v.strip())
    return float(m.group(0)) if m else default


def _segments_from_d(d: str):
    """Yield subpaths as (list of segments, closed); each segment is a list of complex points."""
    for segs, closed in parse_path_d(d):
        yield [[complex(x, y) for x, y in seg] for seg in segs], closed


def load_svg(filename: str, device=None):
    """Load strokes from an SVG file -> (canvas_width, canvas_height, shapes, shape_groups).

    Supports <path>, <line>, <polyline> and <polygon>; fills are ignored (CLIPasso only
    optimises strokes). Group transforms are not applied.
    """
    tree = ET.parse(filename)
    root = tree.getroot()
    ns = ""
    if root.tag.startswith("{"):
        ns = root.tag.split("}")[0] + "}"
    vb = root.attrib.get("viewBox")
    if vb:
        vx, vy, vw, vh = [float(v) for v in re.findall(_NUM, vb)[:4]]
    else:
        vx = vy = 0.0
        vw = _float(root.attrib.get("width"), 224)
        vh = _float(root.attrib.get("height"), 224)
    canvas_w = int(round(_float(root.attrib.get("width"), vw)))
    canvas_h = int(round(_float(root.attrib.get("height"), vh)))
    sx, sy = canvas_w / vw, canvas_h / vh

    shapes, groups = [], []
    for el in root.iter():
        tag = el.tag.replace(ns, "")
        attrs = _style_dict(el)
        if tag == "path":
            d = attrs.get("d", "")
        elif tag == "line":
            d = f"M {attrs.get('x1', 0)} {attrs.get('y1', 0)} L {attrs.get('x2', 0)} {attrs.get('y2', 0)}"
        elif tag in ("polyline", "polygon"):
            nums = re.findall(_NUM, attrs.get("points", ""))
            if len(nums) < 4:
                continue
            pairs = [f"{nums[i]} {nums[i + 1]}" for i in range(0, len(nums) - 1, 2)]
            d = "M " + " L ".join(pairs) + (" Z" if tag == "polygon" else "")
        else:
            continue
        if not d.strip():
            continue
        opacity = _float(attrs.get("stroke-opacity"), 1.0) * _float(attrs.get("opacity"), 1.0)
        color = _parse_color(attrs.get("stroke", "rgb(0,0,0)"), opacity)
        if color is None:
            color = [0.0, 0.0, 0.0, opacity]
        width = _float(attrs.get("stroke-width"), 1.0) * (sx + sy) / 2
        for segs, closed in _segments_from_d(d):
            pts = [segs[0][0]]
            ncp = []
            for seg in segs:
                ncp.append(len(seg) - 2)
                pts.extend(seg[1:])
            if closed and len(pts) > 1 and abs(pts[-1] - pts[0]) < 1e-6:
                pts = pts[:-1]
            else:
                closed = False
            points = torch.tensor([[(p.real - vx) * sx, (p.imag - vy) * sy] for p in pts], dtype=torch.float32,
                                  device=device)
            shapes.append(Path(torch.tensor(ncp, dtype=torch.int32), points, torch.tensor(width, device=device),
                               is_closed=closed))
            groups.append(ShapeGroup(torch.tensor([len(shapes) - 1]), fill_color=None,
                                     stroke_color=torch.tensor(color, dtype=torch.float32, device=device)))
    return canvas_w, canvas_h, shapes, groups
