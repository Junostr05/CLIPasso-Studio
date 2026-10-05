"""Paper under the sketches: textures, colour, vignette, the SVG background and the exports with paper."""

import json
import re

import numpy as np
import pytest

SVG = """<svg version="1.1" xmlns="http://www.w3.org/2000/svg" width="224" height="224" viewBox="0 0 224 224">
<path d="M 20 30 C 40 10 60 90 80 50" fill="none" stroke="#000000" stroke-width="3"/>
<path d="M 150 150 L 200 190" fill="none" stroke="#000000" stroke-width="3"/></svg>"""


def test_normalize_colour_and_darkness():
    from clipasso_studio.gui import paper

    assert paper.normalize(None) is None and paper.normalize({"kind": "none", "vignette": 0}) is None
    assert paper.normalize({"kind": "none", "vignette": 0.4}) == {"kind": "none", "vignette": 0.4}
    assert paper.normalize({"kind": "bogus", "vignette": 3}) == {"kind": "none", "vignette": 1.0}
    assert paper.normalize({"kind": "kraft"}) == {"kind": "kraft", "vignette": 0.0}
    assert paper.color_of({"kind": "kraft"}) == paper.COLORS["kraft"]
    assert paper.color_of({"kind": "kraft"}, "#123456") == "#123456"
    assert paper.color_of({"kind": "kraft"}, "transparent") == paper.COLORS["kraft"]
    assert paper.is_dark(paper.COLORS["blackboard"]) and not paper.is_dark(paper.COLORS["kraft"])
    assert not paper.is_dark("not a colour")


def test_textures_are_seeded_and_differ_per_kind():
    from clipasso_studio.gui import paper

    seen = []
    for kind in paper.KINDS[1:]:
        t = paper.texture(kind, 200, 150)
        assert t.shape == (150, 200) and t.std() > 0.5
        assert t is paper.texture(kind, 200, 150)  # cached
        assert np.array_equal(t, paper.texture.__wrapped__(kind, 200, 150))  # the same every time
        seen.append(t)
    assert not any(np.array_equal(a, b) for i, a in enumerate(seen) for b in seen[i + 1:])
    assert not paper.texture("none", 10, 10).any()
    # large pictures: the texture is made smaller and scaled up, the features stay the same size relative to it
    assert paper.texture("drawing", paper.MAX_SIDE * 2, 100).shape == (100, paper.MAX_SIDE * 2)


def test_paper_image_colour_and_vignette():
    from clipasso_studio.gui import paper

    img = np.asarray(paper.image({"kind": "kraft", "vignette": 0}, 120, 80), dtype=float)
    assert img.shape == (80, 120, 3)
    want = np.array(paper._rgb(paper.COLORS["kraft"]), dtype=float)
    assert np.abs(img.reshape(-1, 3).mean(axis=0) - want).max() < 12
    plain = np.asarray(paper.image({"kind": "none", "vignette": 0.0}, 50, 50, "#808080"))
    assert (plain == 128).all()
    vig = np.asarray(paper.image({"kind": "none", "vignette": 1.0}, 100, 100, "#ffffff"), dtype=float)
    assert vig[0, 0].mean() < vig[50, 50].mean() - 60  # darker corners


def test_svg_with_paper(qapp):
    from PySide6.QtGui import QColor

    from clipasso_studio.gui import paper
    from clipasso_studio.gui.export import qimage_to_pil, restyle_svg, svg_to_qimage

    assert paper.svg_with_paper(SVG, None) == SVG
    out = paper.svg_with_paper(restyle_svg(SVG, background="#ffffff"), {"kind": "drawing", "vignette": 0.3})
    assert out.count("data-bg") == 1 and "<rect" not in out  # the background rectangle is replaced
    assert re.search(r'<image data-bg="1" x="0" y="0" width="224" height="224"', out)
    assert "data:image/jpeg;base64," in out and 'xmlns:xlink="http://www.w3.org/1999/xlink"' in out
    shown = np.asarray(qimage_to_pil(svg_to_qimage(out, 224, QColor("#00ff00"))).convert("RGB"), dtype=float)
    assert shown[5, 5, 1] < 250 and abs(shown[5, 5, 0] - shown[5, 5, 1]) < 20  # the paper, not the green
    framed = paper.svg_with_paper('<svg xmlns="http://www.w3.org/2000/svg" viewBox="10 20 100 50"></svg>',
                                  {"kind": "linen"})
    assert 'x="10" y="20" width="100" height="50"' in framed


@pytest.fixture
def run(tmp_path):
    run = tmp_path / "run"
    (run / "svg_logs").mkdir(parents=True)
    for i in range(3):
        (run / "svg_logs" / f"svg_iter{i}.svg").write_text(SVG)
    (run / "best_iter.svg").write_text(SVG)
    return run


def test_exports_on_paper(qapp, tmp_path, run):
    from PIL import Image

    from clipasso_studio.gui import export

    kraft = {"kind": "kraft", "vignette": 0.5}
    # the colour of the paper is the background colour; without one (transparent) the paper's own
    export.export_png(str(run / "best_iter.svg"), str(tmp_path / "a.png"), size=200, background=None, paper=kraft)
    img = np.asarray(Image.open(tmp_path / "a.png").convert("RGB"), dtype=float)
    assert img[100, 100].mean() > 120 and img[:, :, 2].mean() < img[:, :, 0].mean() - 30  # brown paper
    assert img[0, 0].mean() < img[100, 60].mean()  # vignette
    export.export_svg(str(run / "best_iter.svg"), str(tmp_path / "a.svg"), background="#ffffff", paper=kraft)
    assert "data:image/jpeg" in (tmp_path / "a.svg").read_text()
    export.export_pdf(str(run / "best_iter.svg"), str(tmp_path / "a.pdf"), 5.0, paper=kraft)
    assert (tmp_path / "a.pdf").stat().st_size > 10_000  # with the paper picture
    for fmt in ("gif", "webp", "mp4"):
        n = export.export_animation(str(run), str(tmp_path / f"a.{fmt}"), size=96, length=0.5, style="neon",
                                    paper={"kind": "blackboard"}, stroke_color="#f2f2ec", background=None)
        assert n > 0 and (tmp_path / f"a.{fmt}").stat().st_size > 0
    first = np.asarray(Image.open(tmp_path / "a.gif").convert("RGB"), dtype=float)
    assert first.mean() < 110  # on the dark board
    export.export_drawing(str(run / "best_iter.svg"), str(tmp_path / "d.webp"), size=96, length=0.5,
                          paper={"kind": "watercolor"})
    out = export.animated_svg(SVG, 1.0, paper={"kind": "drawing"})
    assert out.count("data-bg") == 1 and "@keyframes" in out
    (tmp_path / "job").mkdir()
    (tmp_path / "job" / "job.json").write_text(json.dumps({"runs": [{"seed": 800,
                                                                       "best_svg": str(run / "best_iter.svg")}]}))
    export.export_matrix_zip(str(tmp_path / "job"), str(tmp_path / "m.zip"), size=64, paper=kraft)
    import zipfile

    with zipfile.ZipFile(tmp_path / "m.zip") as z:
        assert "data:image/jpeg" in z.read("L8_level0.svg").decode() and "data:image/jpeg" in z.read(
            "matrix.svg").decode()


def test_paper_in_the_canvas_and_the_export_dialog(qapp, run):
    from clipasso_studio.gui import dialogs, paper
    from clipasso_studio.gui.widgets.canvas import SketchCanvas

    canvas = SketchCanvas()
    canvas.resize(200, 200)
    canvas.set_svg(SVG)
    plain = canvas.grab().toImage()
    canvas.set_paper({"kind": "watercolor", "vignette": 0.0})
    on_paper = canvas.grab().toImage()
    assert on_paper != plain and canvas.svg() == SVG
    canvas.set_paper({"kind": "blackboard"})
    assert "#F2F2EC" in (canvas._shown(SVG) or "").upper()  # light strokes on the board
    canvas.set_paper(None)
    assert canvas.grab().toImage() == plain

    dlg = dialogs.ExportDialog("png", str(run / "best_iter.svg"), str(run), "x")
    dlg.paper.combo.setCurrentIndex(paper.KINDS.index("blackboard"))
    assert dlg.background.color() == paper.COLORS["blackboard"] and dlg.stroke.color() == paper.LIGHT_STROKE
    dlg.paper.combo.setCurrentIndex(paper.KINDS.index("kraft"))
    assert dlg.background.color() == paper.COLORS["kraft"] and dlg.stroke.color() == "#000000"
    dlg.paper.vignette.setValue(40)
    assert dlg.paper.paper() == {"kind": "kraft", "vignette": 0.4}
    dlg.paper.combo.setCurrentIndex(0)
    dlg.paper.vignette.setValue(0)
    assert dlg.paper.paper() is None
