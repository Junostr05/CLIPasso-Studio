"""One-line mode of CLIPasso: the whole sketch as one continuous cubic path."""

import math
import os
import random

import pytest

from clipasso_studio import settings_schema as schema
from clipasso_studio.engine import model_store

SAMPLES = os.path.join(os.path.dirname(__file__), "..", "clipasso_studio", "resources", "samples")
CAMEL = os.path.join(SAMPLES, "camel.png")
CLIPASSO_MODELS = all(model_store.is_available(k) for k in ("clip:RN101", "clip:ViT-B/32", "u2net"))


def _length(points, route):
    return sum(math.dist(points[a], points[b]) for a, b in zip(route, route[1:]))


def test_route_through_the_points():
    from clipasso_studio.curves import order_points

    rng = random.Random(3)
    pts = [(rng.random(), rng.random()) for _ in range(60)]
    route = order_points(pts)
    assert sorted(route) == list(range(60)) and route == order_points(pts)  # all points, deterministic
    assert _length(pts, route) < 0.3 * _length(pts, list(range(60)))
    line = [(float(x), 0.0) for x in (5, 1, 4, 2, 3, 0)]
    assert [line[i][0] for i in order_points(line)] == [0, 1, 2, 3, 4, 5]
    assert order_points([(0, 0), (1, 1)]) == [0, 1] and order_points([]) == []


def test_one_line_settings():
    import torch

    from clipasso_studio.engine import jobs, pipeline

    s = {**schema.default_settings("clipasso"), "one_line": True, "one_line_segments": 32, "num_paths": 24,
         "num_stages": 3, "force_sparse": True, "control_points_per_seg": 2}
    args = pipeline.build_args(s, "x.png", 0, "/tmp/x", torch.device("cpu"))
    assert (args.num_paths, args.num_segments, args.num_stages, args.control_points_per_seg, args.force_sparse) == \
        (1, 32, 1, 4, 0)
    assert schema.num_strokes(s) == 1 and jobs.run_name_for("camel.png", s, 0) == "camel_1strokes_seed0"
    for key in ("num_paths", "num_segments", "control_points_per_seg", "num_stages", "force_sparse"):
        assert not schema.is_enabled(schema.param("clipasso", key), s), key
        assert schema.is_enabled(schema.param("clipasso", key), {**s, "one_line": False}), key
    assert schema.is_enabled(schema.param("clipasso", "one_line_segments"), s)
    off = pipeline.build_args({**s, "one_line": False}, "x.png", 0, "/tmp/x", torch.device("cpu"))
    assert (off.num_paths, off.num_segments, off.num_stages) == (24, 1, 3)


def test_drawing_of_one_line_takes_by_its_length(tmp_path):
    from clipasso_studio.gui import export

    assert export.default_drawing_length(1, 10.0) == 6.0 and export.default_drawing_length(1, 50.0) == 12.0
    assert export.default_drawing_length(1) == 2.0 and export.default_drawing_length(16) == 4.0
    d = " ".join(f"C {x + 30} 10 {x + 60} 210 {x + 90} 10" for x in range(0, 900, 90))
    svg = ('<svg xmlns="http://www.w3.org/2000/svg" width="224" height="224" viewBox="0 0 224 224">'
           f'<path d="M 0 10 {d}" fill="none" stroke="#000" stroke-width="1.5"/></svg>')
    drawing = export.Drawing(svg)
    assert drawing.line > 5
    path = tmp_path / "line.svg"
    path.write_text(svg)
    assert export.drawing_length(str(path)) == export.default_drawing_length(1, drawing.line) > 2.0
    assert export.Drawing(svg.replace("</svg>", '<path d="M 0 0 L 5 5"/></svg>')).line == 0.0


@pytest.mark.skipif(not CLIPASSO_MODELS, reason="models not downloaded (run tools/fetch_models.py)")
def test_one_line_run(tmp_path):
    from clipasso_studio.engine import pipeline, svg_io

    summary = pipeline.run_job({"num_iter": 3, "num_sketches": 1, "device": "cpu", "one_line": True,
                                "one_line_segments": 16, "eval_interval": 1, "save_interval": 1},
                               CAMEL, str(tmp_path))
    _, _, shapes, _ = svg_io.load_svg(summary["best_svg"])
    assert len(shapes) == 1 and shapes[0].num_control_points.tolist() == [2] * 16
    assert open(summary["best_svg"]).read().count("C ") == 16
