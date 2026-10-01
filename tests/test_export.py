import json

import pytest


SVG = """<svg version="1.1" xmlns="http://www.w3.org/2000/svg" width="224" height="224" viewBox="0 0 224 224">
<defs/><g>
<path d="M 20 30 C 40 {y} 60 90 80 50" fill="none" stroke="rgb(0, 0, 0)" stroke-opacity="1" stroke-width="1.5"
 stroke-linecap="round" stroke-linejoin="round"/>
</g></svg>"""


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


@pytest.mark.parametrize("ext", ["gif", "mp4", "webp"])
def test_export_animation(qapp, run_dir, tmp_path, ext):
    from clipasso_studio.gui import export

    dest = tmp_path / f"anim.{ext}"
    n = export.export_animation(str(run_dir), str(dest), size=128, fps=10)
    assert dest.is_file() and dest.stat().st_size > 0
    # 3 drawn frames (up to the best iteration) at 10 fps = 0.3 s, then the sketch for 1 s
    assert n == (round(0.3 * 30) + 30 if ext == "mp4" else 3)


def _gif_durations(path):
    from PIL import Image

    im = Image.open(path)
    out = []
    for i in range(im.n_frames):
        im.seek(i)
        out.append(im.info["duration"])
    return out


def test_animation_length_sets_the_frame_rate(qapp, run_dir, tmp_path):
    from clipasso_studio.gui import export

    dest = tmp_path / "anim.gif"
    export.export_animation(str(run_dir), str(dest), size=96, length=3.0, hold=2.0)
    durations = _gif_durations(dest)
    assert len(durations) == 3 and durations[:2] == [1000, 1000] and durations[2] == 1000 + 2000
    # the frames share one small palette (8 ink steps from white to black)
    from PIL import Image

    im = Image.open(dest)
    assert im.mode == "P" and len({c for _, c in im.convert("RGB").getcolors(256)}) <= export.INK_LEVELS


def test_animation_plan():
    from clipasso_studio.gui.export import MIN_FRAME_MS, animation_plan

    idx, ms = animation_plan(100, length=4.0, hold=1.0, fmt="gif")
    assert idx == list(range(100)) and sum(ms) == 5000 and all(d >= MIN_FRAME_MS for d in ms)
    idx, ms = animation_plan(1000, length=2.0, hold=0.0, fmt="gif")  # 2 ms per frame: thinned out
    assert len(idx) == 2000 // MIN_FRAME_MS and idx[0] == 0 and idx[-1] == 999 and sum(ms) == 2000
    idx, ms = animation_plan(3, length=1.0, hold=0.5, fmt="webp")
    assert idx == [0, 1, 2] and abs(sum(ms) - 1500) <= 1
    idx, ms = animation_plan(10, length=2.0, hold=1.0, fmt="mp4")  # 30 fps: drawn frames repeated
    assert len(idx) == 60 + 30 and idx[0] == 0 and idx[59] == 9 and idx == sorted(idx)
    idx, _ = animation_plan(1000, length=1.0, hold=0.0, fmt="mp4")  # and skipped
    assert len(idx) == 30 and idx[-1] == 999
    assert animation_plan(20, fps=10, fmt="gif")[1][:-1] == [100.0] * 19  # the old frame-rate setting


def test_webp_keeps_a_transparent_background(qapp, run_dir, tmp_path):
    from PIL import Image

    from clipasso_studio.gui import export

    dest = tmp_path / "anim.webp"
    export.export_animation(str(run_dir), str(dest), size=96, length=1.0, background=None, stroke_color="#ff0000",
                            width_scale=4.0)
    im = Image.open(dest)
    assert im.is_animated and im.n_frames == 3
    im.seek(2)
    rgba = im.convert("RGBA")
    assert rgba.getpixel((0, 0))[3] == 0  # transparent
    assert any(p[3] > 200 and p[0] > 200 and p[1] < 60 for p in rgba.getdata())  # red strokes


def test_coloured_strokes_are_kept(qapp, tmp_path):
    from PIL import Image

    from clipasso_studio.gui import export

    logs = tmp_path / "svg_logs"
    logs.mkdir()
    for i in range(2):
        (logs / f"svg_iter{i}.svg").write_text(SVG.format(y=10 + 20 * i).replace("rgb(0, 0, 0)", "rgb(0, 0, 255)"))
    dest = tmp_path / "anim.gif"
    export.export_animation(str(tmp_path), str(dest), size=96, length=1.0, width_scale=4.0)
    im = Image.open(dest)
    im.seek(1)
    assert any(b > 150 and r < 80 for r, g, b in im.convert("RGB").getdata())  # still blue


def test_animation_export_can_be_cancelled(qapp, run_dir, tmp_path):
    from clipasso_studio.gui import export

    dest = tmp_path / "anim.gif"
    with pytest.raises(InterruptedError):
        export.export_animation(str(run_dir), str(dest), size=96, cancel=lambda: True)
    assert not dest.exists()


def test_matrix_zip(qapp, tmp_path):
    import zipfile

    from PIL import Image

    from clipasso_studio.gui import export

    job = tmp_path / "ballerina_scenesketch_x"
    runs = []
    for cell in (200, 201, 800, 801):
        run = job / f"cell{cell}"
        run.mkdir(parents=True)
        (run / "best_iter.svg").write_text(SVG.format(y=10 + cell % 100 * 30))
        runs.append({"seed": cell, "run_dir": str(run), "best_svg": str(run / "best_iter.svg")})
    (job / "job.json").write_text(json.dumps({"method": "scenesketch", "runs": runs}))
    dest = tmp_path / "m.zip"
    assert export.export_matrix_zip(str(job), str(dest), size=128, stroke_color="#ff0000", background=None) == 4
    with zipfile.ZipFile(dest) as z:
        names = set(z.namelist())
        assert {"L2_level0.svg", "L2_level1.png", "L8_level1.svg", "matrix.svg", "matrix.png"} <= names
        assert "#ff0000" in z.read("L8_level0.svg").decode()
        sheet = z.read("matrix.svg").decode()
        assert sheet.count("<svg") == 1 + 4 and ">L2<" in sheet and ">L8<" in sheet
        z.extract("matrix.png", tmp_path)
        z.extract("L2_level0.png", tmp_path)
    assert Image.open(tmp_path / "L2_level0.png").size == (128, 128)
    w, h = Image.open(tmp_path / "matrix.png").size
    assert w > 2 * 128 * 0.9 and h > 2 * 128 * 0.9  # 2 x 2 cells of about the PNG size


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
