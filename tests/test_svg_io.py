import torch

from clipasso_studio.engine.renderer import Path, ShapeGroup, render
from clipasso_studio.engine.svg_io import load_svg, save_svg, scene_to_svg

# Output format of pydiffvg.save_svg as used by the original CLIPasso.
DIFFVG_SVG = """<?xml version="1.0" ?>
<svg height="224" version="1.1" width="224" xmlns="http://www.w3.org/2000/svg">
  <defs/>
  <g>
    <path d="M 20.0 30.0 C 40.0 10.0 60.0 90.0 80.0 50.0" fill="none" stroke="rgb(0, 0, 0)" stroke-opacity="1.0"
          stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round"/>
    <path d="M 100.0 100.0 C 120.0 110.0 130.0 150.0 150.0 160.0" fill="none" stroke="rgb(0, 0, 0)"
          stroke-opacity="0.5" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round"/>
  </g>
</svg>
"""


def test_load_diffvg_format(tmp_path):
    f = tmp_path / "sketch.svg"
    f.write_text(DIFFVG_SVG)
    w, h, shapes, groups = load_svg(str(f))
    assert (w, h) == (224, 224)
    assert len(shapes) == 2 and len(groups) == 2
    assert shapes[0].num_control_points.tolist() == [2]
    assert shapes[0].points.shape == (4, 2)
    assert torch.allclose(shapes[0].points[3], torch.tensor([80.0, 50.0]))
    assert abs(groups[1].stroke_color[3].item() - 0.5) < 1e-6
    assert abs(shapes[0].stroke_width.item() - 1.5) < 1e-6


def test_roundtrip(tmp_path):
    pts = torch.tensor([[10.0, 10.0], [30.0, 5.0], [50.0, 40.0], [60.0, 60.0], [70.0, 50.0], [80.0, 90.0],
                        [90.0, 100.0]])
    shapes = [Path(torch.tensor([2, 2], dtype=torch.int32), pts, torch.tensor(2.0))]
    groups = [ShapeGroup(torch.tensor([0]), None, torch.tensor([0.0, 0.0, 0.0, 1.0]))]
    f = tmp_path / "rt.svg"
    save_svg(str(f), 128, 128, shapes, groups)
    w, h, shapes2, groups2 = load_svg(str(f))
    assert (w, h) == (128, 128)
    assert torch.allclose(shapes2[0].points, pts, atol=1e-3)
    assert shapes2[0].num_control_points.tolist() == [2, 2]
    a = render(128, 128, shapes, groups)
    b = render(128, 128, shapes2, groups2)
    assert torch.allclose(a, b, atol=1e-3)


def test_export_options():
    pts = torch.tensor([[10.0, 10.0], [20.0, 20.0]])
    shapes = [Path(torch.tensor([0], dtype=torch.int32), pts, torch.tensor(1.5)),
              Path(torch.tensor([0], dtype=torch.int32), pts + 5, torch.tensor(1.5))]
    groups = [ShapeGroup(torch.tensor([0]), None, torch.tensor([0.0, 0.0, 0.0, 1.0])),
              ShapeGroup(torch.tensor([1]), None, torch.tensor([0.0, 0.0, 0.0, 0.1]))]
    svg = scene_to_svg(32, 32, shapes, groups, background="white", stroke_color=(255, 0, 0), width_scale=2,
                       min_opacity=0.5)
    assert 'fill="white"' in svg
    assert svg.count("<path") == 1
    assert "rgb(255, 0, 0)" in svg
    assert 'stroke-width="3"' in svg


def test_load_line_polyline_and_viewbox(tmp_path):
    f = tmp_path / "shapes.svg"
    f.write_text("""<svg xmlns="http://www.w3.org/2000/svg" width="200" height="200" viewBox="0 0 100 100">
    <line x1="0" y1="0" x2="50" y2="50" style="stroke:#ff0000;stroke-width:2"/>
    <polyline points="10,10 20,20 30,10" stroke="black"/>
    </svg>""")
    w, h, shapes, groups = load_svg(str(f))
    assert (w, h) == (200, 200)
    assert len(shapes) == 2
    assert torch.allclose(shapes[0].points[1], torch.tensor([100.0, 100.0]))
    assert abs(shapes[0].stroke_width.item() - 4.0) < 1e-6
    assert torch.allclose(groups[0].stroke_color[:3], torch.tensor([1.0, 0.0, 0.0]))
    assert shapes[1].num_control_points.tolist() == [0, 0]


def test_path_parser_commands():
    from clipasso_studio.engine.svg_path import parse_path_d

    subs = parse_path_d("M10 10 h 10 v 10 L 5 5 Q 0 0 5 -5 T 10 0 C 1 2 3 4 5 6 S 7 8 9 10 z m 1 1 l 2 2")
    assert len(subs) == 2
    segs, closed = subs[0]
    assert closed
    assert segs[0] == [(10.0, 10.0), (20.0, 10.0)]
    assert segs[1] == [(20.0, 10.0), (20.0, 20.0)]
    assert len(segs[3]) == 3 and len(segs[4]) == 3  # Q and T
    assert segs[4][1] == (10.0, -10.0)  # reflected control point
    assert len(segs[5]) == 4 and segs[6][1] == (7.0, 8.0)  # S reflects C's 2nd control point (3,4)->(7,8)
    assert subs[1][0][0] == [(11.0, 11.0), (13.0, 13.0)]


def test_arc_is_converted_to_cubics():
    import math

    from clipasso_studio.engine.svg_path import parse_path_d

    segs, _ = parse_path_d("M 0 0 A 10 10 0 0 1 20 0")[0]
    assert all(len(s) == 4 for s in segs)
    assert segs[-1][-1] == (20.0, 0.0)
    # the midpoint of a half circle of radius 10 lies 10 units away from the chord
    s = segs[0]
    mid = [(1 - 0.5) ** 3 * s[0][k] + 3 * 0.25 * 0.5 * s[1][k] + 3 * 0.5 * 0.25 * s[2][k] + 0.125 * s[3][k]
           for k in range(2)]
    assert math.isclose(math.dist(mid, (10.0, 0.0)), 10.0, rel_tol=0.01)
