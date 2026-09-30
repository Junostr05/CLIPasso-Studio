"""The eraser: hit tests on strokes, removing them, and the edited sketch used everywhere."""

import os

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

SVG = """<svg version="1.1" xmlns="http://www.w3.org/2000/svg" width="224" height="224" viewBox="0 0 224 224">
<g>
<path d="M 20 20 C 60 20 100 20 140 20" fill="none" stroke="rgb(0, 0, 0)" stroke-width="2"/>
<path d="M 20 100 L 200 100" fill="none" stroke="rgb(0, 0, 0)" stroke-width="2"/>
<path d="M 100 150 C 110 160 120 170 130 200" fill="none" stroke="rgb(0, 0, 0)" stroke-width="6"/>
</g></svg>"""


def test_hit_test_and_remove():
    from clipasso_studio.gui import strokes

    idx = strokes.StrokeIndex(SVG)
    assert len(idx) == 3
    assert idx.hit(80, 21, 2) == 0 and idx.hit(150, 99, 2) == 1
    assert idx.hit(80, 60, 2) is None  # nothing near
    assert idx.hit(118, 170, 1) == 2  # half the stroke width counts
    out = strokes.remove_strokes(SVG, [1])
    assert strokes.count(out) == 2 and "L 200 100" not in out
    assert strokes.view_box(SVG) == (0.0, 0.0, 224.0, 224.0)
    hl = strokes.highlight(SVG, 0)
    assert hl.count(strokes.HIGHLIGHT) == 1


def test_sketch_file_prefers_the_edited_sketch(tmp_path):
    from clipasso_studio.engine import jobs

    run = tmp_path / "run"
    run.mkdir()
    (run / "best_iter.svg").write_text(SVG)
    assert jobs.sketch_file(str(run)) == str(run / "best_iter.svg")
    (run / jobs.EDITED_FILE).write_text(SVG)
    assert jobs.sketch_file(str(run)) == str(run / jobs.EDITED_FILE)
    summary = {"best_run": "run", "best_svg": str(tmp_path / "run_best.svg"),
               "runs": [{"run_name": "run", "run_dir": str(run)}]}
    assert jobs.best_sketch(summary) == str(run / jobs.EDITED_FILE)


@pytest.fixture(scope="module")
def studio_window(tmp_path_factory):
    tmp = tmp_path_factory.mktemp("appdata")
    os.environ["XDG_DATA_HOME"] = str(tmp)
    os.environ["LOCALAPPDATA"] = str(tmp)
    from PySide6.QtWidgets import QApplication

    app = QApplication.instance() or QApplication([])
    from clipasso_studio.gui import theme
    from clipasso_studio.gui.app_settings import app_settings

    app_settings().data["output_dir"] = str(tmp / "out")
    theme.apply(app, "dark")
    from clipasso_studio.gui.main_window import MainWindow

    w = MainWindow()
    w.resize(1400, 900)
    w.show()
    yield w
    w.controller.shutdown()
    w.close()


def test_eraser_in_the_studio(studio_window, tmp_path):
    import json

    from PySide6.QtCore import QPointF

    from clipasso_studio import settings_schema as schema
    from clipasso_studio.engine import jobs
    from clipasso_studio.gui import strokes

    job = tmp_path / "job"
    run = job / "run"
    (run / "svg_logs").mkdir(parents=True)
    (run / "best_iter.svg").write_text(SVG)
    (job / "run_best.svg").write_text(SVG)
    summary = {"target": "x.png", "created": "2026-10-01 10:00:00", "settings": schema.default_settings("swiftsketch"),
               "method": "swiftsketch", "best_svg": str(job / "run_best.svg"), "best_run": "run",
               "runs": [{"seed": 20, "run_name": "run", "run_dir": str(run), "best_loss": 0.2, "best_iter": 0,
                         "iterations_done": 1, "best_svg": str(run / "best_iter.svg"), "status": "done",
                         "method": "swiftsketch", "clip_score": 80.0}]}
    (job / "job.json").write_text(json.dumps(summary))
    studio = studio_window.studio
    studio.show_job_dir(str(job))
    studio.modes.set_current("sketch")
    studio._mode_changed("sketch")
    assert studio.edit_tools.isVisibleTo(studio) and not studio.undo_btn.isEnabled()
    studio.eraser_btn.setChecked(True)
    canvas = studio.canvas
    rect = canvas._paper_rect()

    def at(x, y):  # SVG coordinates -> widget position
        return QPointF(rect.left() + x / 224 * rect.width(), rect.top() + y / 224 * rect.height())

    assert canvas.stroke_at(at(150, 100)) == 1
    # one gesture: press on stroke 1, drag over stroke 0 -> one undo step, two strokes gone
    canvas.erase_begin.emit()
    canvas.erase.emit(canvas.stroke_at(at(150, 100)))
    canvas.erase.emit(canvas.stroke_at(at(80, 20)))
    canvas.erase_end.emit()
    edited = run / jobs.EDITED_FILE
    assert edited.is_file() and strokes.count(edited.read_text()) == 1
    assert (run / "best_iter.svg").read_text() == SVG  # the original stays
    assert studio._selected_run()[0] == str(edited)  # exports use the edited sketch
    assert studio.undo_btn.isEnabled()
    studio.undo_edit()
    assert not edited.exists() and strokes.count(studio.seed_svgs[20]) == 3
    studio.redo_edit()
    assert strokes.count(edited.read_text()) == 1
    studio.revert_edits()
    assert not edited.exists() and studio.seed_svgs[20] == SVG
    studio.undo_edit()  # revert can be undone
    assert edited.is_file()
    # reopening the job shows the touched-up sketch
    studio.show_job_dir(str(job))
    assert strokes.count(studio.seed_svgs[20]) == 1
    studio.eraser_btn.setChecked(False)
