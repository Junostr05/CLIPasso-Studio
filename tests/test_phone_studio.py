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
