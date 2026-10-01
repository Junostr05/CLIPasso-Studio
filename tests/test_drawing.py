"""Stroke-by-stroke animation (GIF / WebP / MP4) and the self-drawing SVG."""

import json
import time
import xml.etree.ElementTree as ET

import pytest


# three strokes: a long one (drawn first), a short one far away, one starting near the long one's end
SVG = ('<svg xmlns="http://www.w3.org/2000/svg" width="224" height="224" viewBox="0 0 224 224"><g>'
       '<path d="M 200 200 L 180 180" stroke="black" stroke-width="2" fill="none"/>'
       '<path d="M 10 10 C 40 10 80 10 110 10" stroke="black" stroke-width="3" fill="none"/>'
       '<path d="M 120 15 L 150 40" stroke="black" stroke-width="2" fill="none"/>'
       '</g></svg>')


def test_route_and_frames():
    from clipasso_studio.gui.export import Drawing

    d = Drawing(SVG)
    firsts = [st["subs"][0][0] for st in d.strokes]
    assert firsts[0] == (10.0, 10.0)  # the longest stroke first
    assert abs(firsts[1][0] - 120) < 1e-6  # then the nearest end
    assert firsts[2] == (180.0, 180.0)  # the last one is drawn from its nearer end (reversed)
    assert d.frame(0.0).count("<path") == 0
    assert d.frame(1.0).count("<path") == 3
    counts = [d.frame(t / 20).count("<path") for t in range(21)]
    assert counts == sorted(counts)  # strokes only appear
    half = Drawing(SVG).frame(0.3)
    ET.fromstring(half)
    assert half.count("<path") == 1 and "L" in half  # the first stroke, cut short
    kept = Drawing(SVG, keep_order=True)
    assert kept.strokes[0]["subs"][0][0] == (200.0, 200.0)  # SVG order (ControlSketch)


def test_export_drawing_formats(qapp, tmp_path):
    from PIL import Image

    from clipasso_studio.gui import export

    src = tmp_path / "best_iter.svg"
    src.write_text(SVG)
    n = export.export_drawing(str(src), str(tmp_path / "a.gif"), size=96, length=2.0, hold=0.5)
    assert n > 10 and Image.open(tmp_path / "a.gif").n_frames > 5
    export.export_drawing(str(src), str(tmp_path / "a.webp"), size=96, length=1.0, style="ink",
                          stroke_color="#224488", background=None)
    assert (tmp_path / "a.webp").stat().st_size > 0
    export.export_drawing(str(src), str(tmp_path / "a.mp4"), size=96, length=1.0)
    assert (tmp_path / "a.mp4").stat().st_size > 0
    with pytest.raises(InterruptedError):
        export.export_drawing(str(src), str(tmp_path / "c.gif"), size=96, cancel=lambda: True)
    assert not (tmp_path / "c.gif").exists()


def test_controlsketch_keeps_its_stroke_order(tmp_path):
    from clipasso_studio.gui import export

    run = tmp_path / "run"
    run.mkdir()
    (run / "config.json").write_text(json.dumps({"method": "controlsketch"}))
    assert export.run_method(str(run)) == "controlsketch"
    assert export.run_method(str(tmp_path)) == "clipasso"


@pytest.mark.parametrize("style", ["plain", "ink", "pencil", "marker"])
def test_animated_svg(style):
    from clipasso_studio.gui.export import animated_svg

    out = animated_svg(SVG, length=3.0, hold=1.0, style=style, background="#fffaf0", stroke_color="#333333")
    root = ET.fromstring(out)
    assert root.tag == "{http://www.w3.org/2000/svg}svg" and root.get("viewBox") == "0 0 224 224"
    assert out.count("<mask ") == 3 and out.count('mask="url(#m') == 3
    assert out.count("@keyframes") == 3 and "infinite" in out and 'pathLength="1"' in out
    assert 'fill="#fffaf0"' in out and "#333333" in out
    # stroke 0 starts at 0 %, the last one ends at length / (length + hold) = 75 %
    assert "0%,0.000%" in out and "75.000%,100%" in out


@pytest.fixture
def own_settings(tmp_path, monkeypatch):
    """App settings of their own (the dialog remembers the animation mode)."""
    from clipasso_studio.gui import app_settings as settings_module

    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path / "data"))
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path / "data"))
    settings_module._instance = None
    yield
    settings_module._instance = None


def test_export_dialog_stroke_by_stroke(qapp, tmp_path, monkeypatch, own_settings):
    from PySide6.QtWidgets import QDialog, QFileDialog

    from clipasso_studio.gui import dialogs
    from clipasso_studio.gui.app_settings import app_settings

    run = tmp_path / "run"
    (run / "svg_logs").mkdir(parents=True)
    (run / "svg_logs" / "svg_iter0.svg").write_text(SVG)
    (run / "best_iter.svg").write_text(SVG)
    dest = tmp_path / "out.gif"
    monkeypatch.setattr(QFileDialog, "getSaveFileName", lambda *a, **k: (str(dest), ""))
    dlg = dialogs.ExportDialog("gif", str(run / "best_iter.svg"), str(run), "out")
    dlg.mode.setCurrentIndex(dlg.mode.findData("strokes"))
    assert dlg.length.value() == 2.0  # 3 strokes: the shortest default
    dlg._save()
    end = time.time() + 30
    while dlg.result() != QDialog.Accepted and time.time() < end:
        qapp.processEvents()
        time.sleep(0.01)
    assert dest.stat().st_size > 0
    assert app_settings().get("export_anim_mode") == "strokes"  # remembered for the next export
    svg_dest = tmp_path / "anim.svg"
    monkeypatch.setattr(QFileDialog, "getSaveFileName", lambda *a, **k: (str(svg_dest), ""))
    dlg = dialogs.ExportDialog("svganim", str(run / "best_iter.svg"), str(run), "out")
    assert not dlg.mode.isVisibleTo(dlg) and "3" in dlg.timing.text()
    dlg._save()
    assert dlg.result() == QDialog.Accepted and svg_dest.read_text().count("<mask ") == 3
