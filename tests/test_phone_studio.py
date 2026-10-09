"""3.8: more of the studio on the phone, against the real studio (``gui/phone_api.py``) – editing the sketch (eraser,
pen, undo / redo / original, "Simplify", the saved steps, continuing with CLIPasso, a matrix cell again)."""

import json

import pytest

from tests.test_strokes import SVG


@pytest.fixture(scope="module")
def window(tmp_path_factory):
    tmp = tmp_path_factory.mktemp("appdata")
    env = pytest.MonkeyPatch()  # undone after the module: later tests use the real model folders
    env.setenv("XDG_DATA_HOME", str(tmp))
    env.setenv("LOCALAPPDATA", str(tmp))
    from PySide6.QtWidgets import QApplication

    app = QApplication.instance() or QApplication([])
    from clipasso_studio.gui import app_settings as settings_module
    from clipasso_studio.gui import theme
    from clipasso_studio.gui.app_settings import app_settings

    settings_module._instance = None
    app_settings().data["output_dir"] = str(tmp / "out")
    theme.apply(app, "dark")
    from clipasso_studio.gui.main_window import MainWindow

    w = MainWindow()
    w.controller.start_next = lambda: None  # (queued, never computed)
    w.show()
    yield w
    w.controller.shutdown()
    w.close()
    settings_module._instance = None
    env.undo()


def _job(tmp_path, method="clipasso", steps=4):
    """A finished job of one sketch with three strokes, its saved steps and its input picture."""
    from PIL import Image

    from clipasso_studio import settings_schema as schema

    job = tmp_path / "job"
    run = job / "run"
    (run / "svg_logs").mkdir(parents=True)
    (run / "best_iter.svg").write_text(SVG)
    (job / "run_best.svg").write_text(SVG)
    for i in range(steps):  # the steps: the strokes one by one
        kept = SVG.split("<path")
        (run / "svg_logs" / f"svg_iter{i * 10}.svg").write_text("<path".join(kept[: 2 + min(i, 2)]) + "</g></svg>")
    (run / "config.json").write_text(json.dumps({"best_iter": (steps - 1) * 10}))
    Image.new("RGB", (224, 224), "white").save(run / "input.png")
    summary = {"target": "x.png", "created": "2026-10-07 10:00:00", "settings": schema.default_settings(method),
               "method": method, "best_svg": str(job / "run_best.svg"), "best_run": "run",
               "runs": [{"seed": 20, "run_name": "run", "run_dir": str(run), "best_loss": 0.2, "best_iter": 0,
                         "iterations_done": 1, "best_svg": str(run / "best_iter.svg"), "status": "done",
                         "method": method, "clip_score": 80.0}]}
    (job / "job.json").write_text(json.dumps(summary))
    return job, run


def test_eraser_pen_undo_on_the_phone(window, tmp_path):
    from clipasso_studio.engine import jobs
    from clipasso_studio.gui import strokes

    job, run = _job(tmp_path)
    studio, call = window.studio, window.phone.api.handle
    studio.show_job_dir(str(job))
    edit = call("get_studio", {})["edit"]
    assert edit["seed"] == 20 and edit["strokes"] == 3 and edit["can_erase"] and not edit["undo"]
    assert edit["can_continue"] and edit["simplify"] == "none" and edit["continue"]["new"] > 0
    # a swipe over the first two strokes (0..1 of the sketch) – one undo step
    swipe = [[80 / 224, 20 / 224], [150 / 224, 60 / 224], [150 / 224, 100 / 224]]
    assert call("do_edit", {"op": "erase", "points": swipe}) == {"ok": True, "erased": 2}
    assert strokes.count(studio.seed_svgs[20]) == 1 and (run / jobs.EDITED_FILE).is_file()
    assert call("do_edit", {"op": "erase", "points": [[0.9, 0.9]]})["ok"] is False  # one line left: not erased
    st = call("get_studio", {})["edit"]
    assert st["undo"] and st["edited"] and not st["can_erase"]
    assert call("do_edit", {"op": "undo"})["ok"] and strokes.count(studio.seed_svgs[20]) == 3
    assert call("do_edit", {"op": "redo"})["ok"] and strokes.count(studio.seed_svgs[20]) == 1
    assert call("do_edit", {"op": "revert"})["ok"] and studio.seed_svgs[20] == SVG
    # the pen: a stroke of its own, kept fixed for CLIPasso
    line = [[0.1, 0.5], [0.3, 0.55], [0.5, 0.6], [0.7, 0.62]]
    assert call("do_edit", {"op": "pen", "points": line}) == {"ok": True, "changed": True}
    assert strokes.count(studio.seed_svgs[20]) == 4 and strokes.fixed_count(studio.seed_svgs[20]) == 1
    assert call("do_edit", {"op": "pen", "points": [[0.5, 0.5]]})["ok"] is False  # (too short)
    assert call("do_edit", {"op": "pen", "points": [[5, 5], ["x", 1]]})["ok"] is False  # (outside, nonsense)
    assert call("do_edit", {"op": "melt"})["ok"] is False
    # continuing with CLIPasso: a new job from the sketch, the drawn stroke fixed
    before = len(window.controller.jobs)
    answer = call("do_continue_clipasso", {"new": 2, "iterations": 50, "keep": True})
    assert answer["ok"] and len(window.controller.jobs) == before + 1
    queued = window.controller.jobs[-1]
    assert queued.settings["method"] == "clipasso" and queued.settings["num_iter"] == 50
    assert queued.settings["num_paths"] == 4 + 2
    window.controller.jobs.remove(queued)
    call("do_edit", {"op": "revert"})


def test_simplify_and_saved_steps_on_the_phone(window, tmp_path):
    from clipasso_studio.engine import importance
    from clipasso_studio.gui import strokes

    job, run = _job(tmp_path)
    studio, call = window.studio, window.phone.api.handle
    studio.show_job_dir(str(job))
    assert call("file_simplified", {"keep": 1})["ok"] is False  # not measured yet
    # (measured as the CLIP process would: stroke 2 adds most, stroke 0 least)
    (run / importance.FILE).write_text(json.dumps({"sha1": importance.digest(SVG), "drops": [0.1, 0.5, 0.9]}))
    assert call("get_studio", {})["edit"]["simplify"] == "ready"
    assert call("do_simplify_measure", {}) == {"ok": True, "ready": True}
    one = call("file_simplified", {"keep": 1})
    assert one["_type"] == "image/svg+xml" and strokes.count(one["_bytes"].decode()) == 1
    assert "130 200" in one["_bytes"].decode()  # (the most important one stays)
    assert call("do_simplify_apply", {"keep": 2})["ok"] and strokes.count(studio.seed_svgs[20]) == 2
    assert call("do_edit", {"op": "undo"})["ok"] and studio.seed_svgs[20] == SVG
    # the saved steps: one as the result, all of them for the time lapse
    steps = call("get_steps", {})
    assert steps["ok"] and steps["count"] == 4 and steps["lapse"] == 4
    first = call("file_step", {"i": "0"})
    assert strokes.count(first["_bytes"].decode()) == 1
    assert call("file_step", {"i": "9"})["ok"] is False
    assert call("do_take_step", {"i": 1})["ok"] and strokes.count(studio.seed_svgs[20]) == 2
    call("do_edit", {"op": "revert"})


def test_nothing_to_edit_while_it_is_drawn(window, monkeypatch):
    monkeypatch.setattr(window.studio, "_editable_seed", lambda: None)  # (a sketch being drawn, or none)
    st = window.phone.api.handle("get_studio", {})
    assert st["edit"] is None
    assert window.phone.api.handle("do_edit", {"op": "undo"})["ok"] is False
    assert window.phone.api.handle("do_rerun_cell", {"cell": "x"})["ok"] is False


def test_views_best_history_hints_and_paper(window, tmp_path, monkeypatch):
    """The views of a job (photo / sketch, attention), another sketch as the result, the earlier jobs of the photo,
    the hints about the photo and the paper's colour and vignette – from the phone."""
    import io

    from PIL import Image

    from clipasso_studio.engine import jobs
    from clipasso_studio.gui import image_hints
    from clipasso_studio.gui.app_settings import app_settings

    out = tmp_path / "out"
    out.mkdir()
    monkeypatch.setitem(app_settings().data, "output_dir", str(out))
    photo = tmp_path / "camel.png"
    Image.new("RGB", (64, 64), "white").save(photo)
    job, run = _job(out)
    Image.new("L", (224, 224), 128).save(run / "attention_map.png")
    run2 = job / "run2"
    run2.mkdir()
    (run2 / "best_iter.svg").write_text(SVG)
    summary = json.loads((job / "job.json").read_text())
    summary["target"] = str(photo)
    summary["runs"].append({**summary["runs"][0], "seed": 21, "run_name": "run2", "run_dir": str(run2),
                            "best_svg": str(run2 / "best_iter.svg")})
    (job / "job.json").write_text(json.dumps(summary))
    studio, call = window.studio, window.phone.api.handle
    studio.set_image(str(photo))
    studio.show_job_dir(str(job))
    st = call("get_studio", {})
    assert {"compare", "attention"} <= set(st["views"]) and len(st["seeds"]) == 2
    png = call("file_view", {"kind": "attention"})
    assert png["_type"] == "image/png" and Image.open(io.BytesIO(png["_bytes"])).size == (224, 224)
    assert call("file_view", {"kind": "nothing"})["ok"] is False
    # another sketch as the job's result
    assert call("do_choose_best", {"seed": 21})["ok"]
    assert jobs.job_summary(str(job))["best_run"] == "run2"
    assert next(x for x in call("get_studio", {})["seeds"] if x["seed"] == 21)["best"]
    assert call("do_choose_best", {"seed": "x"})["ok"] is False
    # the earlier jobs of the photo
    studio._history_cache = None
    history = call("get_history", {})
    assert history["ok"] and [j["dir"] for j in history["jobs"]] == ["job"] and history["jobs"][0]["shown"]
    # a hint about the photo, and "don't show again"
    monkeypatch.setattr(studio, "_photo_hints", [image_hints.Hint("dark")])
    hints = call("get_studio", {})["hints"]
    assert [h["key"] for h in hints] == ["dark"] and hints[0]["text"]
    assert call("do_dismiss_hint", {"key": "dark"})["ok"] and "dark" in app_settings().get("hints_off")
    assert call("get_studio", {})["hints"] == [] and call("do_dismiss_hint", {"key": "x"})["ok"] is False
    app_settings().set("hints_off", [])
    # the paper's colour and vignette (as the studio's look menu)
    assert call("do_paper", {"color": "#112233", "vignette": True})["ok"]
    st = call("get_studio", {})
    assert st["paper_color"] == "#112233" and st["vignette"]
    assert call("do_paper", {"color": "red; x"})["ok"] is False
    assert call("do_paper", {"color": "", "vignette": False})["ok"] and not call("get_studio", {})["vignette"]


def test_touching_up_the_mask_on_the_phone(window, tmp_path, monkeypatch):
    import numpy as np
    from PIL import Image

    from clipasso_studio.engine import masking
    from clipasso_studio.gui import mask_view

    photo = tmp_path / "dog.png"
    Image.new("RGB", (40, 80), "white").save(photo)
    studio, call = window.studio, window.phone.api.handle
    studio.set_image(str(photo))
    prob = np.zeros((80, 40), np.float32)
    prob[20:60, 10:30] = 1.0
    monkeypatch.setattr(studio, "_mask_settings", lambda: (True, "u2net", {}))
    monkeypatch.setattr(studio, "_mask", {"key": (str(photo), "u2net"), "prob": prob, "edited": False})
    monkeypatch.setattr(mask_view, "load_mask", lambda path, model: (Image.open(photo).convert("RGB"), prob, None))
    saved, previews = [], []
    monkeypatch.setattr(masking, "save_edited_mask", lambda im, mask: saved.append(mask.copy()))
    monkeypatch.setattr(studio, "_update_mask_preview", lambda: previews.append(True))
    begin = call("do_mask_begin", {})
    assert begin["ok"] and begin["share"] == 0.25 and not begin["undo"]
    jpg = call("file_mask_edit", {})
    assert jpg["_type"] == "image/jpeg"
    gone = call("do_mask_edit", {"op": "part", "x": 0.5, "y": 0.5})  # the object tapped: it goes
    assert gone["share"] == 0 and gone["undo"]
    assert call("do_mask_save", {})["ok"] is False  # (an empty mask is not kept)
    assert call("do_mask_edit", {"op": "undo"})["share"] == 0.25
    more = call("do_mask_edit", {"op": "add", "points": [[0.1, 0.05], [0.9, 0.05]], "size": 0.2})
    assert more["share"] > 0.25
    wand = call("do_mask_edit", {"op": "part", "x": 0.05, "y": 0.95})  # where the model saw nothing: magic wand
    assert wand["share"] > more["share"]  # (the white photo: all of it)
    assert call("do_mask_edit", {"op": "undo"})["share"] == more["share"]
    assert call("do_mask_edit", {"op": "melt"})["ok"] is False
    assert call("do_mask_save", {})["ok"] and saved and saved[0].mean() > 0.25 and previews
    assert call("do_mask_edit", {"op": "undo"})["ok"] is False  # (saved: the session is over)


def test_gallery_info_albums_and_continue(window, tmp_path, monkeypatch):
    """Titles, tags and notes, sorting and the tag filter, albums (new, add, remove, rename, delete) and continuing an
    interrupted result – from the phone's gallery."""
    from clipasso_studio.engine import jobs
    from clipasso_studio.gui.app_settings import app_settings
    from tests.helpers import fake_job

    out = tmp_path / "out"
    out.mkdir()
    monkeypatch.setitem(app_settings().data, "output_dir", str(out))
    api, call = window.phone.api, window.phone.api.handle
    api._cache = None
    fake_job(str(out), "camel", str(tmp_path / "camel.png"), 31.0, created="2026-10-01 10:00:00")
    fake_job(str(out), "zebra", str(tmp_path / "zebra.png"), 25.0, created="2026-10-02 10:00:00")
    res = call("get_results", {})
    assert [r["dir"] for r in res["results"]] == ["zebra", "camel"] and {s["key"] for s in res["sorts"]} >= {"name"}
    assert [r["dir"] for r in call("get_results", {"sort": "score"})["results"]] == ["camel", "zebra"]
    assert [r["dir"] for r in call("get_results", {"sort": "name"})["results"]] == ["camel", "zebra"]
    # title, tags, notes
    assert call("do_info", {"dir": "camel", "title": "Kamel", "tags": "tier, wüste", "notes": "erstes"})["ok"]
    meta = jobs.read_meta(str(out / "camel"))
    assert meta["title"] == "Kamel" and meta["tags"] == ["tier", "wüste"] and meta["notes"] == "erstes"
    res = call("get_results", {"tag": "tier"})
    assert [r["dir"] for r in res["results"]] == ["camel"] and res["results"][0]["title"] == "Kamel"
    assert "tier" in res["tags"]
    assert call("do_info", {"dir": "nope"})["ok"] is False
    # albums
    assert call("do_album", {"op": "new", "name": "Tiere", "dirs": ["camel", "zebra"]})["ok"]
    assert len(call("get_results", {"album": "Tiere"})["results"]) == 2
    assert call("do_album", {"op": "remove", "name": "Tiere", "dirs": ["zebra"]})["ok"]
    assert [r["dir"] for r in call("get_results", {"album": "Tiere"})["results"]] == ["camel"]
    assert call("do_album", {"op": "rename", "name": "Tiere", "new": "Zoo"})["name"] == "Zoo"
    assert "Zoo" in call("get_results", {})["albums"]
    assert call("do_album", {"op": "delete", "name": "Zoo"})["ok"]
    assert call("get_results", {"album": "Zoo"})["results"] == []
    assert call("do_album", {"op": "new", "name": "  "})["ok"] is False
    assert call("do_album", {"op": "burn", "name": "x"})["ok"] is False
    # an interrupted result goes on
    monkeypatch.setattr(window.controller, "continue_job", lambda d: object() if d.endswith("camel") else None)
    assert call("do_continue_result", {"dir": "camel"})["ok"]
    assert call("do_continue_result", {"dir": "zebra"})["ok"] is False


def test_queue_details_options_and_load(window, tmp_path, monkeypatch):
    from PIL import Image

    from clipasso_studio import settings_schema as schema

    photo = tmp_path / "owl.png"
    Image.new("RGB", (64, 64), "white").save(photo)
    c, call = window.controller, window.phone.api.handle
    c.jobs.clear()
    first = c.enqueue(str(photo), schema.default_settings("clipasso"), start=False)
    second = c.enqueue(str(photo), {**schema.default_settings("swiftsketch"), "num_sketches": 3}, start=False)
    try:
        q = call("get_queue", {})
        assert [j["id"] for j in q["jobs"]] == [first.id, second.id] and q["jobs"][0]["can_load"]
        changes = q["jobs"][1]["changes"]
        assert any(ch["value"] == "3" for ch in changes) and q["remaining"]
        assert call("do_run_next", {"id": second.id})["ok"] and c.jobs[0] is second
        assert call("do_queue_options", {"auto_start": False})["ok"] and not c.auto_start
        assert not window.queue.auto.isChecked() and call("get_queue", {})["auto_start"] is False
        call("do_queue_options", {"auto_start": True})
        assert call("do_load_job", {"id": second.id})["ok"]
        assert window.studio.params.method() == "swiftsketch" and window.studio.params.settings()["num_sketches"] == 3
        assert window.studio.image_path == str(photo)
    finally:
        c.jobs.clear()
