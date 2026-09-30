import json
import os

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

SVG = """<svg version="1.1" xmlns="http://www.w3.org/2000/svg" width="224" height="224" viewBox="0 0 224 224">
<defs/><g>
<path d="M 20 30 C 40 {y} 60 90 80 50" fill="none" stroke="rgb(0, 0, 0)" stroke-opacity="1" stroke-width="1.5"
 stroke-linecap="round" stroke-linejoin="round"/>
</g></svg>"""


@pytest.fixture(scope="module")
def qapp():
    from PySide6.QtWidgets import QApplication

    return QApplication.instance() or QApplication([])


@pytest.fixture
def run_dir(tmp_path):
    logs = tmp_path / "svg_logs"
    logs.mkdir()
    for i in range(0, 30, 10):
        (logs / f"svg_iter{i}.svg").write_text(SVG.format(y=10 + i))
    (tmp_path / "best_iter.svg").write_text(SVG.format(y=30))
    (tmp_path / "config.json").write_text(json.dumps({"best_iter": 20}))
    return tmp_path


def test_restyle_svg():
    from clipasso_studio.gui.export import restyle_svg

    out = restyle_svg(SVG.format(y=10), stroke_color="#ff0000", width_scale=2.0, background="#ffffff")
    assert 'stroke="#ff0000"' in out
    assert 'stroke-width="3"' in out
    assert 'fill="#ffffff"' in out
    # restyling twice keeps a single background
    assert restyle_svg(out, background="#000000").count("data-bg") == 1


def test_export_png_and_svg(qapp, run_dir, tmp_path):
    from PIL import Image

    from clipasso_studio.gui import export

    png = tmp_path / "out.png"
    export.export_png(str(run_dir / "best_iter.svg"), str(png), size=300, background=None)
    im = Image.open(png)
    assert im.size == (300, 300)
    assert im.getpixel((0, 0))[3] == 0  # transparent background
    svg = tmp_path / "out.svg"
    export.export_svg(str(run_dir / "best_iter.svg"), str(svg), stroke_color="#123456")
    assert "#123456" in svg.read_text()


@pytest.mark.parametrize("ext", ["gif", "mp4"])
def test_export_animation(qapp, run_dir, tmp_path, ext):
    from clipasso_studio.gui import export

    dest = tmp_path / f"anim.{ext}"
    n = export.export_animation(str(run_dir), str(dest), size=128, fps=10)
    assert dest.is_file() and dest.stat().st_size > 0
    assert n == 3 + 10  # frames up to the best iteration + 1 s hold


def test_single_layer_svg(tmp_path, qapp):
    import xml.etree.ElementTree as ET

    from clipasso_studio.gui.export import export_single_layer_svg, single_layer_svg, svg_to_qimage

    many = SVG.format(y=10).replace("</g>", '<path d="M 100 100 L 150 120" fill="none" stroke="rgb(0, 0, 0)" '
                                            'stroke-width="2.5"/>\n</g>')
    out = single_layer_svg(many, stroke_color="#ff0000", width_scale=2.0)
    root = ET.fromstring(out)
    ns = "{http://www.w3.org/2000/svg}"
    paths = list(root.iter(f"{ns}path"))
    groups = list(root.iter(f"{ns}g"))
    assert len(paths) == 1 and len(groups) == 1  # one path in one layer
    assert groups[0].get("{http://www.inkscape.org/namespaces/inkscape}groupmode") == "layer"
    d = paths[0].get("d")
    assert d.count("M ") == 2 and "C 40 10 60 90 80 50" in d and "L 150 120" in d
    assert paths[0].get("stroke") == "#ff0000" and paths[0].get("fill") == "none"
    assert paths[0].get("stroke-width") == "5"  # median width 2.5 x 2
    assert root.find(f"{ns}rect") is None and root.get("viewBox") == "0 0 224 224"
    src = tmp_path / "in.svg"
    src.write_text(many)
    dest = tmp_path / "out.svg"
    export_single_layer_svg(str(src), str(dest))
    img = svg_to_qimage(dest.read_text(), 64, None)
    assert not img.isNull()
