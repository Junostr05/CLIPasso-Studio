"""Export frames: square, like the photo, cropped to the strokes."""

import json
import os
import re

import pytest

from clipasso_studio.engine import framing, model_store

SAMPLES = os.path.join(os.path.dirname(__file__), "..", "clipasso_studio", "resources", "samples")
BUNDLED = all(model_store.is_available(k) for k in ("clip:ViT-B/32", "u2net"))

LINE = ('<svg xmlns="http://www.w3.org/2000/svg" width="224" height="224" viewBox="0 0 224 224">'
        '<path d="M 20 100 C 60 100 120 100 200 110" fill="none" stroke="rgb(0, 0, 0)" stroke-width="2"/></svg>')


def _box(svg):
    return [float(v) for v in re.search(r'viewBox="([^"]+)"', svg).group(1).split()]


def test_where_the_photo_lies_on_the_canvas():
    stretched = framing.photo_frame((300, 200))
    assert stretched == {"aspect": 1.5, "rect": [0.0, 0.0, 1.0, 1.0]}
    side, x, y, w, h = framing.fix_scale_pad(300, 200)
    assert (side, x, y) == (320, 10, 60)
    padded = framing.photo_frame((300, 200), pad=(side, x, y, w, h))
    assert padded["rect"] == pytest.approx([10 / 320, 60 / 320, 310 / 320, 260 / 320])
    zoomed = framing.photo_frame((400, 400), region=(100, 100, 200, 200))  # a small object, zoomed onto
    assert zoomed["rect"] == pytest.approx([-1.0, -1.0, 3.0, 3.0])
    cropped = framing.guess_frame("scenesketch", {"fix_scale": False}, (300, 200))
    assert cropped["rect"] == pytest.approx([-0.25, 0.0, 1.25, 1.0])
    assert framing.guess_frame("clipasso", {"mask_object": True, "frame_object": True}, (300, 200)) is None
    assert framing.guess_frame("controlsketch", {"mask_object": True, "frame_object": True, "fix_scale": True},
                               (300, 200)) == padded
    assert framing.guess_frame("swiftsketch", {"fix_scale": False}, (300, 200)) == stretched


def test_reframing():
    assert framing.make_framing(LINE, "square") is None
    assert framing.make_framing(LINE, "photo", None) is None  # not known
    content = framing.make_framing(LINE, "content", margin=0.1)
    x, y, w, h = content.box
    assert x < 19 and w > 180 and h < 50 and content.aspect > 4
    out = content.apply(LINE)
    assert _box(out) == pytest.approx(list(content.box), abs=1e-3) and 'width="' in out
    assert "M 20 100 C 60 100" in out  # the strokes are not touched, only the frame

    padded = framing.photo_frame((300, 200), pad=framing.fix_scale_pad(300, 200))
    fr = framing.make_framing(LINE, "photo", padded)
    assert fr.y_scale == 1.0 and fr.aspect == pytest.approx(1.5, abs=1e-3)

    stretched = framing.make_framing(LINE, "photo", framing.photo_frame((300, 200)))
    assert stretched.y_scale == pytest.approx(1 / 1.5) and stretched.aspect == pytest.approx(1.5)
    back = stretched.apply(LINE)
    assert _box(back) == pytest.approx([0, 0, 224, 224 / 1.5], abs=1e-3)
    assert "M 20 66.667 C 60 66.667 120 66.667 200 73.333" in back  # squeezed back to the photo's shape
    assert 'stroke-width="2"' in back


def test_export_in_other_shapes(tmp_path, qapp):
    from PIL import Image

    from clipasso_studio.gui import export

    run = tmp_path / "job" / "run"
    run.mkdir(parents=True)
    (run / "best_iter.svg").write_text(LINE)
    (run / "config.json").write_text(json.dumps({"photo_frame": framing.photo_frame((300, 200))}))
    src = str(run / "best_iter.svg")

    export.export_png(src, str(tmp_path / "content.png"), 600, frame="content", margin=0.05)
    w, h = Image.open(tmp_path / "content.png").size
    assert w == 600 and h < 150
    export.export_png(src, str(tmp_path / "photo.png"), 600, frame="photo")
    assert Image.open(tmp_path / "photo.png").size == (600, 400)
    export.export_png(src, str(tmp_path / "square.png"), 600)
    assert Image.open(tmp_path / "square.png").size == (600, 600)
    export.export_svg(src, str(tmp_path / "photo.svg"), frame="photo")
    assert _box((tmp_path / "photo.svg").read_text()) == pytest.approx([0, 0, 224, 149.333], abs=1e-3)
    export.export_single_layer_svg(src, str(tmp_path / "one.svg"), frame="content")
    assert _box((tmp_path / "one.svg").read_text())[3] < 40

    # the copy of the best sketch in the job folder finds its run (and so the photo frame)
    best = tmp_path / "job" / "run_best.svg"
    best.write_text(LINE)
    (tmp_path / "job" / "job.json").write_text(json.dumps({"best_run": "run", "runs": [
        {"run_name": "run", "run_dir": str(run), "seed": 0, "best_svg": src}]}))
    assert export.run_dir_of(str(best)) == str(run)
    assert export.framing_for(str(best), "photo").aspect == pytest.approx(1.5)

    export.export_drawing(src, str(tmp_path / "draw.gif"), size=256, length=0.5, hold=0, frame="photo")
    assert Image.open(tmp_path / "draw.gif").size == (256, 171)
    export.export_drawing(src, str(tmp_path / "draw.mp4"), size=256, length=0.5, hold=0, frame="photo")
    import imageio.v2 as imageio

    reader = imageio.get_reader(str(tmp_path / "draw.mp4"))
    frame = reader.get_data(0)
    reader.close()
    assert frame.shape[:2] == (176, 256)  # padded to multiples of 16


def test_old_runs_take_the_frame_from_their_settings(tmp_path):
    from PIL import Image

    from clipasso_studio.engine import jobs

    photo = tmp_path / "wide.png"
    Image.new("RGB", (300, 200), "white").save(photo)
    job = tmp_path / "job"
    run = job / "run"
    run.mkdir(parents=True)
    jobs.write_state(str(job), str(photo), {"method": "controlsketch", "fix_scale": True}, "done")
    (run / "config.json").write_text("{}")
    assert framing.run_frame(str(run)) == framing.photo_frame((300, 200), pad=framing.fix_scale_pad(300, 200))
    jobs.save_input(str(job), str(photo))
    photo.unlink()  # the copy in the job folder is used then
    assert framing.run_frame(str(run))["aspect"] == 1.5
    jobs.write_state(str(job), str(photo), {"method": "clipasso", "mask_object": True}, "done")
    assert framing.run_frame(str(run)) is None  # may have been zoomed onto the object: unknown
    (run / "config.json").write_text(json.dumps({"photo_frame": framing.photo_frame((300, 200))}))
    assert framing.run_frame(str(run))["rect"] == [0.0, 0.0, 1.0, 1.0]  # saved by the run


@pytest.mark.skipif(not BUNDLED, reason="bundled models missing (run tools/fetch_models.py)")
def test_clipasso_records_the_frame(tmp_path):
    import torch
    from PIL import Image

    from clipasso_studio import settings_schema as schema
    from clipasso_studio.engine import pipeline

    wide = tmp_path / "wide.png"
    Image.open(os.path.join(SAMPLES, "camel.png")).convert("RGB").resize((300, 200)).save(wide)
    for fix_scale in (False, True):
        s = {**schema.default_settings("clipasso"), "fix_scale": fix_scale, "device": "cpu", "mask_model": "u2net"}
        args = pipeline.build_args(s, str(wide), 0, str(tmp_path), torch.device("cpu"))
        pipeline.get_target(args)
        pad = framing.fix_scale_pad(300, 200) if fix_scale else None
        assert args.photo_frame == framing.photo_frame((300, 200), pad=pad)
