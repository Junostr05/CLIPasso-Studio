"""Brush styles of the export: ink, pencil, marker."""

import os
import xml.etree.ElementTree as ET

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

NS = "{http://www.w3.org/2000/svg}"
SVG = """<svg version="1.1" xmlns="http://www.w3.org/2000/svg" width="224" height="224" viewBox="0 0 224 224">
<g>
<path d="M 20 30 C 40 10 60 90 80 50 C 90 40 100 60 120 80" fill="none" stroke="rgb(0, 0, 0)" stroke-opacity="0.8"
 stroke-width="2"/>
<path d="M 150 150 L 200 190" fill="none" stroke="#ff0000" stroke-width="3"/>
</g></svg>"""


@pytest.fixture(scope="module")
def qapp():
    from PySide6.QtWidgets import QApplication

    return QApplication.instance() or QApplication([])


def _paths(svg):
    return list(ET.fromstring(svg).iter(f"{NS}path"))


def test_plain_leaves_the_svg_unchanged():
    from clipasso_studio.gui.brush import stylize_svg

    assert stylize_svg(SVG, "plain") == SVG
    assert stylize_svg(SVG, "unknown") == SVG


def test_ink_turns_strokes_into_tapered_outlines():
    from clipasso_studio.gui import brush

    out = brush.stylize_svg(SVG, "ink")
    paths = _paths(out)
    assert len(paths) == 2
    assert all(p.get("stroke") == "none" and p.get("d").endswith("Z") for p in paths)
    assert paths[0].get("fill") == "rgb(0, 0, 0)" and paths[0].get("fill-opacity") == "0.8"
    assert paths[1].get("fill") == "#ff0000"
    # thinner at the ends than in the middle
    pts = brush.sample("M 0 0 L 100 0")[0]
    outline = brush.ink_outline(pts, 4.0)
    ys = [float(v.split()[1]) for v in outline[2:-2].split(" L ")]
    assert max(abs(y) for y in ys[:1]) < max(abs(y) for y in ys) and max(abs(y) for y in ys) <= 4.0 * 0.7 + 1e-6


def test_pencil_draws_several_graphite_lines_the_same_every_time():
    from clipasso_studio.gui import brush

    out = brush.stylize_svg(SVG, "pencil", seed=3)
    paths = _paths(out)
    assert len(paths) == 6  # three lines per stroke
    assert {p.get("stroke") for p in paths[:3]} == {brush.GRAPHITE}  # black strokes become graphite grey
    assert {p.get("stroke") for p in paths[3:]} == {"#ff0000"}  # coloured strokes keep their colour
    assert float(paths[0].get("stroke-width")) < 2
    assert out == brush.stylize_svg(SVG, "pencil", seed=3)  # deterministic
    assert out != brush.stylize_svg(SVG, "pencil", seed=4)


def test_marker_is_wide_flat_and_see_through():
    from clipasso_studio.gui.brush import stylize_svg

    paths = _paths(stylize_svg(SVG, "marker"))
    assert len(paths) == 2 and paths[0].get("stroke-linecap") == "butt"
    assert float(paths[0].get("stroke-width")) > 2 * 2 and float(paths[0].get("stroke-opacity")) < 0.8


def test_background_is_kept():
    from clipasso_studio.gui.brush import stylize_svg
    from clipasso_studio.gui.export import restyle_svg

    out = stylize_svg(restyle_svg(SVG, background="#fafafa"), "ink")
    assert 'fill="#fafafa"' in out and out.count("data-bg") == 1


@pytest.mark.parametrize("style", ["ink", "pencil", "marker"])
def test_styles_in_every_export(qapp, tmp_path, style):
    import json

    from PIL import Image

    from clipasso_studio.gui import export

    run = tmp_path / "run"
    (run / "svg_logs").mkdir(parents=True)
    for i in range(3):
        (run / "svg_logs" / f"svg_iter{i}.svg").write_text(SVG)
    (run / "best_iter.svg").write_text(SVG)
    export.export_svg(str(run / "best_iter.svg"), str(tmp_path / "a.svg"), style=style)
    assert _paths((tmp_path / "a.svg").read_text()) != _paths(SVG)
    export.export_png(str(run / "best_iter.svg"), str(tmp_path / "a.png"), size=128, style=style)
    assert Image.open(tmp_path / "a.png").getextrema()[0][0] < 200  # something was drawn (pencil: light grey)
    export.export_animation(str(run), str(tmp_path / "a.gif"), size=96, length=1.0, style=style)
    assert (tmp_path / "a.gif").stat().st_size > 0
    (tmp_path / "job").mkdir()
    runs = [{"seed": 800, "best_svg": str(run / "best_iter.svg")}]
    (tmp_path / "job" / "job.json").write_text(json.dumps({"runs": runs}))
    export.export_matrix_zip(str(tmp_path / "job"), str(tmp_path / "m.zip"), size=64, style=style)
    assert (tmp_path / "m.zip").stat().st_size > 0
