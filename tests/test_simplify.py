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
    """The file belongs to one sketch – and, 4.1, to the order of its version: a file of 4.0 (CLIP's drops only) is
    measured again."""
    from clipasso_studio.engine import importance

    run = _run(tmp_path)
    assert importance.read(run, SVG) is None
    with open(os.path.join(run, importance.FILE), "w") as f:
        json.dump({"sha1": importance.digest(SVG), "base": 80.0, "drops": [3.0, 2.5, -0.1]}, f)
    assert importance.read(run, SVG) is None  # (4.0's file: measured again)
    with open(os.path.join(run, importance.FILE), "w") as f:
        json.dump({"version": importance.VERSION, "sha1": importance.digest(SVG), "base": 80.0,
                   "drops": [3.0, 2.5, -0.1], "rank": [2, 1, 0]}, f)
    assert importance.read(run, SVG) == [2.0, 1.0, 0.0]
    assert importance.read(run, SVG.replace("204 112", "200 112")) is None  # the sketch changed: measure again
    assert importance.order([2.0, 1.0, 0.0]) == [2, 1, 0]


def _disc_sketch(size=112):
    """A black disc on white, 8 strokes on its outline, 8 strokes crowded in one place inside and 4 spread out."""
    import numpy as np

    yy, xx = np.mgrid[0:size, 0:size]
    c, r = size / 2, size * 0.34
    gray = np.where((xx - c) ** 2 + (yy - c) ** 2 <= r ** 2, 0.05, 0.97).astype(np.float32)
    strokes = []
    for k in range(8):  # the outline: arcs of 45° each
        a = np.linspace(k * np.pi / 4, (k + 1) * np.pi / 4, 16)
        strokes.append(np.stack([c + r * np.cos(a), c + r * np.sin(a)], 1))
    rng = np.random.default_rng(1)
    for _ in range(8):  # crowded: short lines through about the same spot
        p = np.array([c - 8, c - 6]) + rng.uniform(-3, 3, 2)
        d = rng.uniform(-1, 1, 2)
        d /= np.linalg.norm(d)
        strokes.append(np.linspace(p - 9 * d, p + 9 * d, 16))
    for q in ((c + 14, c + 2), (c - 2, c + 16), (c + 6, c - 18), (c - 18, c + 10)):  # spread out
        strokes.append(np.linspace(np.array(q) - (7, 3), np.array(q) + (7, 3), 16))
    coverage = np.zeros((len(strokes), size, size))
    for i, pts in enumerate(strokes):
        dense = np.concatenate([np.linspace(pts[j], pts[j + 1], 6) for j in range(len(pts) - 1)])
        for x, y in dense:
            coverage[i, max(int(y) - 1, 0): int(y) + 2, max(int(x) - 1, 0): int(x) + 2] = 1.0
    samples = [(pts, np.gradient(pts, axis=0)) for pts in strokes]
    return gray, strokes, coverage, samples


def test_simplify_keeps_the_outline_and_thins_areas_evenly():
    """4.1: "Simplify" lets the strokes that fill a dark area go first – where they crowd first – and keeps the
    outline longest, even when CLIP alone would rather keep the filling (here: every outline stroke adds least)."""
    from clipasso_studio.engine import importance

    gray, strokes, coverage, samples = _disc_sketch()
    outline, crowded, spread = range(0, 8), range(8, 16), range(16, 20)
    # CLIP alone: the outline matters least, the crowded strokes most – it would empty the outline first
    drops = [0.1] * 8 + [2.0 + 0.01 * i for i in range(8)] + [1.0 + 0.01 * i for i in range(4)]
    rank = importance.ranking(drops, coverage, samples, gray)
    assert sorted(rank) == list(range(20))
    assert min(rank[i] for i in outline) > max(rank[i] for i in (*crowded, *spread))  # the outline goes last
    first = sorted(range(20), key=lambda i: rank[i])[:4]
    assert sum(i in crowded for i in first) >= 3, first  # the crowded place is thinned first (CLIP: the others) …
    assert max(rank[i] for i in crowded) > min(rank[i] for i in spread)  # … not emptied before the others go
    assert importance.order([float(v) for v in rank])[:4] == first


def test_simplify_without_edges_follows_clip():
    """4.1: a picture without edges or dark areas (a blank one): the order is CLIP's."""
    import numpy as np

    from clipasso_studio.engine import importance

    _, strokes, coverage, samples = _disc_sketch()
    drops = list(np.linspace(0.0, 1.0, len(strokes)))[::-1]
    rank = importance.ranking(drops, coverage, samples, np.full((112, 112), 0.97, dtype=np.float32))
    assert rank == list(range(len(strokes)))[::-1]


@pytest.mark.skipif(not HAS_CLIP, reason="CLIP ViT-B/32 not available")
def test_importance_is_leave_one_out(tmp_path):
    import xml.etree.ElementTree as ET

    from PIL import Image

    from clipasso_studio.__main__ import main
    from clipasso_studio.engine import importance
    from clipasso_studio.engine.scoring import get_scorer

    run = _run(tmp_path)
    assert main(["--importance", run]) == 0
    with open(os.path.join(run, importance.FILE), encoding="utf-8") as f:
        data = json.load(f)
    drops = data["drops"]
    assert len(drops) == 3 and data["version"] == importance.VERSION and sorted(data["rank"]) == [0, 1, 2]
    assert importance.read(run, SVG) == [float(v) for v in data["rank"]]
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
