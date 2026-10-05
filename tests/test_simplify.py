"""Saved steps as the result and "Simplify": the importance of each stroke (CLIP, leave one out), its file and the
bar below the studio's canvas."""

import json
import os

import pytest

from clipasso_studio.engine import model_store

HAS_CLIP = model_store.is_available("clip:ViT-B/32")
SVG = ('<svg xmlns="http://www.w3.org/2000/svg" width="224" height="224" viewBox="0 0 224 224">'
       '<path d="M 20 112 C 60 40 160 40 204 112" fill="none" stroke="#000000" stroke-width="6"/>'
       '<path d="M 20 112 C 60 184 160 184 204 112" fill="none" stroke="#000000" stroke-width="6"/>'
       '<path d="M 200 20 L 210 30" fill="none" stroke="#000000" stroke-width="1"/></svg>')


def _run(tmp_path, svg=SVG):
    from PIL import Image, ImageDraw

    run = tmp_path / "run"
    (run / "svg_logs").mkdir(parents=True)
    (run / "best_iter.svg").write_text(svg)
    img = Image.new("RGB", (224, 224), "white")
    ImageDraw.Draw(img).ellipse((20, 50, 204, 174), outline="black", width=6)  # an eye-like shape
    img.save(run / "input.png")
    return str(run)


def test_importance_file_belongs_to_one_sketch(tmp_path):
    from clipasso_studio.engine import importance

    run = _run(tmp_path)
    assert importance.read(run, SVG) is None
    with open(os.path.join(run, importance.FILE), "w") as f:
        json.dump({"sha1": importance.digest(SVG), "base": 80.0, "drops": [3.0, 2.5, -0.1]}, f)
    assert importance.read(run, SVG) == [3.0, 2.5, -0.1]
    assert importance.read(run, SVG.replace("204 112", "200 112")) is None  # the sketch changed: measure again
    assert importance.order([3.0, 2.5, -0.1]) == [2, 1, 0]


@pytest.mark.skipif(not HAS_CLIP, reason="CLIP ViT-B/32 not available")
def test_importance_is_leave_one_out(tmp_path):
    import xml.etree.ElementTree as ET

    from PIL import Image

    from clipasso_studio.__main__ import main
    from clipasso_studio.engine import importance
    from clipasso_studio.engine.scoring import get_scorer

    run = _run(tmp_path)
    assert main(["--importance", run]) == 0
    drops = importance.read(run, SVG)
    assert len(drops) == 3
    scorer = get_scorer("cpu")
    target = Image.open(os.path.join(run, "input.png")).convert("RGB")
    base = scorer.score_svg(os.path.join(run, "best_iter.svg"), target)
    for i in range(3):  # the same as scoring the sketch without stroke i
        root = ET.fromstring(SVG)
        root.remove(list(root)[i])
        path = tmp_path / f"without{i}.svg"
        path.write_text(ET.tostring(root, encoding="unicode"))
        assert drops[i] == pytest.approx(base - scorer.score_svg(str(path), target), abs=0.05)
    assert drops[2] < min(drops[0], drops[1])  # the little tick adds least
    assert main(["--importance", str(tmp_path / "nothing")]) == 1


def test_edit_bar(qapp, tmp_path):
    from clipasso_studio.gui import strokes
    from clipasso_studio.gui.widgets.edit_bar import EditBar

    frames = []
    for it in (0, 10, 20):
        p = tmp_path / f"svg_iter{it}.svg"
        p.write_text(SVG.replace("204 112", f"{150 + it} 112"))
        frames.append(str(p))
    bar = EditBar()
    shown, taken = [], []
    bar.preview.connect(shown.append)
    bar.apply.connect(taken.append)
    assert not bar.open_history(frames[:1], SVG)  # nothing to choose from
    assert bar.open_history(frames, SVG) and bar.slider.value() == 2 and "170 112" in shown[-1]
    bar.slider.setValue(0)
    assert "150 112" in shown[-1] and "10" not in bar.info.text().split("·")[-1]
    bar.apply_btn.click()
    assert "150 112" in taken[-1] and not bar.isVisibleTo(bar.parentWidget() or bar) and bar.mode == ""

    bar.open_simplify(SVG, None)  # still measuring: the slider waits
    assert not bar.slider.isEnabled() and bar.slider.value() == 3 and not bar.apply_btn.isEnabled()
    bar.set_importance([3.0, 2.5, -0.1])
    assert bar.slider.isEnabled()
    bar.slider.setValue(2)
    assert strokes.count(shown[-1]) == 2 and "210 30" not in shown[-1]  # the tick went first
    bar.slider.setValue(1)
    assert strokes.count(shown[-1]) == 1 and "40 160 40 204" in shown[-1]
    closed = []
    bar.closed.connect(lambda: closed.append(1))
    bar.close_bar()
    assert closed and bar.mode == ""
    bar.open_simplify(SVG, None)
    bar.set_importance(None, "boom")
    assert "boom" in bar.note.text() and not bar.slider.isEnabled()
