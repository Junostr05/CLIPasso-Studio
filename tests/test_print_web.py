"""Print layout (pages, contact sheet, PDF, preview, dialog), Lottie and the web page export."""

import json
import re

import pytest

SVG = """<svg version="1.1" xmlns="http://www.w3.org/2000/svg" width="224" height="224" viewBox="0 0 224 224">
<path d="M 20 30 C 40 10 60 90 80 50" fill="none" stroke="#000000" stroke-width="3"/>
<path d="M 150 150 Q 170 120 200 190" fill="none" stroke="#000000" stroke-width="2" stroke-opacity="0.5"/>
<path d="M 100 200 L 120 210" fill="none" stroke="#000000" stroke-width="2"/></svg>"""


@pytest.fixture
def sketches(tmp_path):
    out = []
    for i in range(5):
        p = tmp_path / f"s{i}.svg"
        p.write_text(SVG)
        out.append((str(p), f"sketch {i}"))
    return out


def test_lottie_paths_keep_the_curves():
    from clipasso_studio.gui import export

    (cubic,) = export.lottie_paths("M 0 0 C 10 0 20 10 20 20")
    k = cubic["ks"]["k"]
    assert k["v"] == [[0, 0], [20, 20]] and k["o"][0] == [10, 0] and k["i"][1] == [0, -10] and not k["c"]
    (quad,) = export.lottie_paths("M 0 0 Q 30 0 30 30", scale=2.0)
    q = quad["ks"]["k"]
    assert q["v"][1] == [60, 60] and q["o"][0] == [40, 0] and q["i"][1] == [0, -40]  # 2/3 to the control point
    (line,) = export.lottie_paths("M 10 10 L 20 10", x0=10, y0=10)
    assert line["ks"]["k"]["v"] == [[0, 0], [10, 0]] and line["ks"]["k"]["o"][0] == [0, 0]
    (closed,) = export.lottie_paths("M 0 0 L 10 0 L 10 10 Z")
    assert closed["ks"]["k"]["c"] and len(closed["ks"]["k"]["v"]) == 3


def test_lottie_draws_stroke_by_stroke(qapp):
    from clipasso_studio.gui import export

    data = export.lottie(SVG, length=3.0, hold=1.0, background="#fafafa", size=448)
    assert data["fr"] == export.LOTTIE_FPS and data["op"] == 4 * export.LOTTIE_FPS
    assert (data["w"], data["h"]) == (448, 448)
    strokes = [la for la in data["layers"] if la["ty"] == 4]
    assert len(strokes) == 3 and data["layers"][-1]["ty"] == 1 and data["layers"][-1]["sc"] == "#fafafa"
    spans = []
    for la in strokes:
        items = la["shapes"][0]["it"]
        kinds = [it["ty"] for it in items]
        assert kinds[-3:] == ["st", "tm", "tr"] and "sh" in kinds
        keys = items[-2]["e"]["k"]
        assert keys[0]["s"] == [0] and keys[1]["s"] == [100] and keys[1]["t"] > keys[0]["t"]
        spans.append((keys[0]["t"], keys[1]["t"]))
        assert all(0 <= c <= 448 for sh in items if sh["ty"] == "sh" for v in sh["ks"]["k"]["v"] for c in v)
    spans.sort()
    assert all(b[0] >= a[1] - 1e-6 for a, b in zip(spans, spans[1:]))  # one after another
    assert max(e for _, e in spans) <= 3.0 * export.LOTTIE_FPS + 1e-6
    widths = sorted(la["shapes"][0]["it"][-3]["w"]["k"] for la in strokes)
    assert widths[-1] == pytest.approx(3 * 2.0)  # stroke width scaled with the picture (224 -> 448)
    assert any(la["shapes"][0]["it"][-3]["o"]["k"] == 50 for la in strokes)
    on_paper = export.lottie(SVG, paper={"kind": "kraft"})
    assert on_paper["assets"][0]["p"].startswith("data:image/jpeg;base64,") and on_paper["layers"][-1]["ty"] == 2
    assert all(la["ty"] == 4 for la in export.lottie(SVG)["layers"])  # transparent: no background layer


def test_lottie_follows_the_drawing_direction(qapp):
    from clipasso_studio.gui import export

    # the route starts with the longest stroke and then goes to the nearest end: the short stroke is drawn
    # from its right end, so its Lottie path has to start there
    svg = ('<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 100 100">'
           '<path d="M 0 50 L 60 50" stroke="#000" stroke-width="1"/>'
           '<path d="M 95 50 L 70 50" stroke="#000" stroke-width="1"/></svg>')
    drawing = export.Drawing(svg)
    data = export.lottie(svg, size=100)
    firsts = sorted((la["shapes"][0]["it"][-2]["e"]["k"][0]["t"], la["shapes"][0]["it"][0]["ks"]["k"]["v"][0])
                    for la in data["layers"])
    assert [round(c) for c in firsts[1][1]] == [round(c) for c in drawing.strokes[1]["subs"][0][0]]


def test_export_lottie_and_web_page(qapp, tmp_path, sketches):
    from clipasso_studio.gui import export

    src = sketches[0][0]
    export.export_lottie(src, str(tmp_path / "a.json"), length=2.0, background="#ffffff")
    data = json.loads((tmp_path / "a.json").read_text())
    assert data["v"] and data["nm"] == "a" and len(data["layers"]) == 4
    export.export_web_page(src, str(tmp_path / "<b>.html"), length=2.0, style="ink", paper={"kind": "blackboard"},
                           stroke_color="#f2f2ec")
    page = (tmp_path / "<b>.html").read_text()
    assert page.startswith("<!doctype html>") and "<title>&lt;b&gt;</title>" in page
    assert "@keyframes" in page and "<button" in page and "data:image/jpeg" in page
    assert re.search(r"background: #2c3a33", page) and "color: #e8e8e8" in page  # light text on the board


def test_page_grid_and_sizes():
    from clipasso_studio.gui import print_layout as pl

    lay = pl.Layout(page="a4")
    assert pl.page_mm(lay) == pytest.approx((210, 297), abs=0.5)
    assert pl.page_mm(pl.Layout(page="a4", landscape=True)) == pytest.approx((297, 210), abs=0.5)
    assert pl.page_mm(pl.Layout(page="poster")) == pytest.approx((500, 700))
    assert pl.grid(6) == (2, 3) and pl.grid(6, landscape=True) == (3, 2) and pl.grid(1) == (1, 1)
    assert pl.page_count(5, pl.Layout(per_page=2)) == 3 and pl.page_count(0, lay) == 0


def test_pdf_pages_and_preview(qapp, tmp_path, sketches):
    from clipasso_studio.gui import print_layout as pl

    lay = pl.Layout(page="a5", per_page=2, title="My <sketches>", signature="J. 2026", captions=True,
                    style="charcoal", paper={"kind": "drawing", "vignette": 0.2})
    pages = []
    n = pl.export_pdf_pages(sketches, str(tmp_path / "a.pdf"), lay, progress=lambda a, b: pages.append((a, b)))
    assert n == 3 and pages[-1] == (3, 3)
    pdf = (tmp_path / "a.pdf").read_bytes()
    assert len(re.findall(rb"/Type\s*/Page\b", pdf)) == 3
    img = pl.preview(sketches, lay, width=200)
    assert img.width() == 200 and abs(img.height() / img.width() - 210 / 148) < 0.02
    def dark(im):
        return sum(1 for y in range(0, im.height(), 2) for x in range(0, im.width(), 2)
                   if im.pixelColor(x, y).lightness() < 150)

    assert dark(img) > dark(pl.preview([], lay, width=200)) + 12  # strokes and captions are on the page
    with pytest.raises(InterruptedError):
        pl.export_pdf_pages(sketches, str(tmp_path / "b.pdf"), lay, cancel=lambda: True)
    assert not (tmp_path / "b.pdf").exists()


def test_print_dialog(qapp, sketches):
    from clipasso_studio.gui import print_layout as pl
    from clipasso_studio.gui.app_settings import app_settings
    from clipasso_studio.gui.i18n import tr
    from clipasso_studio.gui.print_dialog import PrintDialog

    dlg = PrintDialog(sketches)
    assert dlg.per_page.currentData() == app_settings().get("print_per_page", 6)
    dlg.per_page.setCurrentIndex(pl.PER_PAGE.index(4))
    dlg.title.setText("Camels")
    dlg.paper.combo.setCurrentIndex(5)  # blackboard: light strokes
    dlg._update_preview()
    assert dlg.pages_label.text() == tr("ui.print.pages", n=2)
    lay = dlg.layout_choice()
    assert lay.per_page == 4 and lay.title == "Camels" and lay.paper == {"kind": "blackboard", "vignette": 0.0}
    assert lay.stroke_color is not None and lay.background == "#2C3A33"
    assert not dlg.preview.pixmap().isNull()
    dlg._remember(lay)
    assert app_settings().get("print_per_page") == 4
    single = PrintDialog(sketches[:1])
    assert single.per_page.currentData() == 1
