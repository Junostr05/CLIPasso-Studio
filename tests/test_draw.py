"""Drawing own strokes into a sketch and continuing it with CLIPasso (strokes drawn by hand stay fixed)."""

import os
import xml.etree.ElementTree as ET

import pytest

from clipasso_studio.engine import model_store

SAMPLES = os.path.join(os.path.dirname(__file__), "..", "clipasso_studio", "resources", "samples")
CAMEL = os.path.join(SAMPLES, "camel.png")
CLIPASSO_MODELS = all(model_store.is_available(k) for k in ("clip:RN101", "clip:ViT-B/32", "u2net"))

SVG = ('<svg xmlns="http://www.w3.org/2000/svg" width="224" height="224" viewBox="0 0 224 224"><g>'
       '<path d="M 10 10 C 20 20 30 30 40 40" fill="none" stroke="rgb(0, 0, 0)" stroke-width="2"/>'
       '<path d="M 50 50 C 60 60 70 70 80 80 M 90 90 C 95 95 100 100 110 110" fill="none" stroke="rgb(0, 0, 0)" '
       'stroke-width="3"/>'
       '<path d="M 120 10 C 130 20 140 30 150 40" fill="none" stroke="rgb(0, 0, 0)" stroke-width="5"/></g></svg>')


def test_simplify_and_smooth():
    from clipasso_studio.curves import bezier_d, catmull_rom_bezier, simplify

    line = [(0, 0), (1, 0.01), (2, 0), (3, 0.02), (4, 0)]
    assert simplify(line, 0.1) == [(0.0, 0.0), (4.0, 0.0)]
    corner = [(0, 0), (5, 0), (5, 5), (5, 5)]
    assert simplify(corner, 0.1) == [(0.0, 0.0), (5.0, 0.0), (5.0, 5.0)]
    assert simplify([(1, 1), (1, 1)], 0.5) == [(1.0, 1.0)]
    segs = catmull_rom_bezier([(0, 0), (10, 0), (10, 10)])
    assert len(segs) == 2 and segs[0][0] == (0.0, 0.0) and segs[0][3] == (10.0, 0.0) and segs[1][3] == (10.0, 10.0)
    assert segs[0][2][1] < 0 < segs[1][1][1]  # a smooth turn through (10, 0)
    assert bezier_d(segs).startswith("M 0 0 C ") and bezier_d(segs).count("C") == 2
    assert catmull_rom_bezier([(1, 1)]) == [] and bezier_d([]) == ""


def test_append_stroke():
    from clipasso_studio.gui import strokes

    out = strokes.append_stroke(SVG, [(20, 100), (40, 120), (60, 100), (80, 120)])
    assert strokes.count(out) == 4 and strokes.fixed_count(out) == 1
    assert 'data-fixed="1"' in out and 'stroke-width="3"' in out.split("<path")[-1]  # median width of the sketch
    assert strokes.shape_count(SVG) == 4 and strokes.shape_count(out) == 5  # subpaths count as strokes
    assert strokes.fixed_count(strokes.unfix(out)) == 0
    assert strokes.append_stroke(SVG, [(5, 5), (5, 5)]) == SVG  # a click without movement draws nothing
    ns = "{http://www.w3.org/2000/svg}"
    assert len(ET.fromstring(out).find(f"{ns}g").findall(f"{ns}path")) == 4  # next to the other strokes
    empty = '<svg xmlns="http://www.w3.org/2000/svg" width="512" height="512" viewBox="0 0 512 512"></svg>'
    drawn = strokes.append_stroke(empty, [(10, 10), (100, 100)], fixed=False)
    assert "data-fixed" not in drawn and 'stroke-width="3.429"' in drawn  # 1.5 px at 224 -> 512


def test_fixed_strokes_survive_the_svg_round_trip(tmp_path):
    import torch

    from clipasso_studio.engine import renderer, svg_io

    shapes = [renderer.Path([2], torch.tensor([[1.0, 1], [2, 2], [3, 3], [4, 4]]), 1.5, fixed=True),
              renderer.Path([2], torch.tensor([[5.0, 5], [6, 6], [7, 7], [8, 8]]), 1.5)]
    groups = [renderer.ShapeGroup([i], stroke_color=torch.tensor([0.0, 0, 0, 1])) for i in range(2)]
    path = tmp_path / "s.svg"
    svg_io.save_svg(str(path), 224, 224, shapes, groups)
    assert path.read_text().count('data-fixed="1"') == 1
    _, _, loaded, _ = svg_io.load_svg(str(path))
    assert [s.fixed for s in loaded] == [True, False]


def test_init_svg_is_kept_with_the_job(tmp_path):
    from clipasso_studio.engine import jobs

    job = tmp_path / "job"
    (job / "input").mkdir(parents=True)
    (job / "input" / "zebra.png").write_bytes(b"x")
    src = tmp_path / "start.svg"
    src.write_text(SVG)
    copy = jobs.save_init_svg(str(job), str(src))
    assert copy == str(job / "input" / jobs.INIT_SVG) and open(copy).read() == SVG
    src.write_text("<svg/>")
    assert jobs.save_init_svg(str(job), str(src)) == copy and open(copy).read() == SVG  # never replaced
    assert jobs.saved_input(str(job), "other.png").endswith("zebra.png")  # the start sketch is not the input
    assert jobs.save_init_svg(str(tmp_path / "nojob"), str(tmp_path / "missing.svg")).endswith("missing.svg")


@pytest.mark.skipif(not CLIPASSO_MODELS, reason="models not downloaded (run tools/fetch_models.py)")
def test_continuing_keeps_the_fixed_strokes(tmp_path):
    from clipasso_studio.engine import checkpoint, jobs, pipeline, svg_io
    from clipasso_studio.gui import strokes

    big = SVG.replace('width="224" height="224" viewBox="0 0 224 224"', 'width="448" height="448" '
                      'viewBox="0 0 448 448"')
    start = tmp_path / "start.svg"
    start.write_text(strokes.append_stroke(big, [(200, 300), (260, 340), (320, 300)]))
    logs = []

    class Rec(pipeline.Reporter):
        def event(self, kind, **data):
            if kind == "log":
                logs.append(data.get("code"))

    settings = {"num_iter": 6, "num_sketches": 1, "num_paths": 7, "device": "cpu", "path_svg": str(start),
                "eval_interval": 2, "save_interval": 2, "augemntations": "affine_noise", "noise_thresh": 0.0}
    summary = pipeline.run_job(settings, CAMEL, str(tmp_path / "out"), Rec())
    run = summary["runs"][0]["run_dir"]
    job_dir = os.path.dirname(summary["best_svg"])
    assert jobs.read_state(job_dir)["settings"]["path_svg"] == os.path.join(job_dir, "input", jobs.INIT_SVG)
    _, _, final, _ = svg_io.load_svg(os.path.join(run, "final_svg.svg"))
    _, _, first, _ = svg_io.load_svg(str(start))
    assert len(final) == 7 and [s.fixed for s in final] == [False] * 4 + [True] + [False] * 2
    for a, b in zip(first, final):
        a_pts = a.points * 0.5  # 448 -> 224 canvas
        assert abs(float(b.stroke_width) - float(a.stroke_width) * 0.5) < 1e-4  # widths scaled with the canvas
        if a.fixed:
            assert (b.points - a_pts).abs().max() < 1e-3  # not moved (no gradient step, no noise)
        else:
            assert (b.points - a_pts).abs().max() > 1e-3

    # a checkpoint written for other strokes is not used (the seed starts again)
    checkpoint.save(run, {"epoch": 2, "counter": 3, "stage": 0, "points": [], "colors": []})
    pipeline.run_single({**settings, "path_svg": os.path.join(job_dir, "input", jobs.INIT_SVG)}, CAMEL, run, 0,
                        Rec())
    assert "checkpoint_mismatch" in logs
