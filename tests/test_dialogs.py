"""Background work of the dialogs: callbacks in the GUI thread, export / download to the end, cancel."""

import os
import threading
import time

import pytest

from tests.helpers import wait_until

SVG = ('<svg xmlns="http://www.w3.org/2000/svg" width="224" height="224" viewBox="0 0 224 224">'
       '<path d="M 10 10 C 60 {y} 120 {y} 200 200" stroke="black" stroke-width="2" fill="none"/></svg>')


@pytest.fixture(scope="module")
def qapp(tmp_path_factory):
    tmp = tmp_path_factory.mktemp("appdata")
    env = pytest.MonkeyPatch()  # undone after the module: later tests use the real model folders
    env.setenv("XDG_DATA_HOME", str(tmp))
    env.setenv("LOCALAPPDATA", str(tmp))
    from PySide6.QtWidgets import QApplication

    app = QApplication.instance() or QApplication([])
    yield app
    from clipasso_studio.gui import dialogs

    dialogs.wait_for_threads()
    env.undo()


def _wait(app, condition, timeout=30.0):
    wait_until(app, condition, timeout)


def test_run_in_thread_calls_back_in_the_gui_thread(qapp):
    from PySide6.QtWidgets import QWidget

    from clipasso_studio.gui import dialogs

    owner = QWidget()
    seen = {}

    def work(progress):
        progress(1, 2)
        progress(2, 2)
        return "ok"

    def fail(progress):
        raise ValueError("boom")

    def record(name):
        return lambda *a: seen.setdefault(name, (threading.current_thread() is threading.main_thread(), a))

    dialogs.run_in_thread(owner, work, on_progress=record("progress"), on_done=record("done"))
    dialogs.run_in_thread(owner, fail, on_error=record("error"))
    _wait(qapp, lambda: {"progress", "done", "error"} <= set(seen))
    assert seen["progress"] == (True, (1, 2))
    assert seen["done"] == (True, ("ok",))
    assert seen["error"] == (True, ("boom",))


def test_progress_of_downloads_over_2_gib(qapp):
    """Byte counts above the 32-bit range (SDXL ~6.9 GB, the GPU update ~3.3 GB) arrive unchanged."""
    from PySide6.QtWidgets import QProgressBar, QWidget

    from clipasso_studio.gui import dialogs

    owner = QWidget()
    seen = []

    def work(progress):
        progress(5_000_000_000, 6_938_011_392)
        return "ok"

    done = []
    dialogs.run_in_thread(owner, work, on_progress=lambda a, b: seen.append((a, b)), on_done=done.append)
    _wait(qapp, lambda: done)
    assert seen == [(5_000_000_000, 6_938_011_392)]
    bar = QProgressBar()
    dialogs.set_progress(bar, *seen[0])
    assert (bar.minimum(), bar.maximum(), bar.value()) == (0, 1000, 720)
    dialogs.set_progress(bar, 0, -1)
    assert bar.maximum() == 0  # busy
    busy = dialogs.BusyDialog("moving")
    busy.progress(3_000_000_000, 4_000_000_000)
    assert busy.bar.value() == 750


def test_consecutive_background_jobs(qapp):
    """The GUI thread releasing a finished job while the next one runs Python code crashed PySide
    (deferred delete of the thread) – the second export in a row."""
    from PySide6.QtWidgets import QWidget

    from clipasso_studio.gui import dialogs

    owner = QWidget()

    def work(n, progress):
        total = 0
        for i in range(20000):  # keep the worker busy in Python while the GUI processes events
            total += i * n
        progress(1, 1)
        return total

    results = []
    for n in range(8):
        dialogs.run_in_thread(owner, work, n, on_done=results.append)
        _wait(qapp, lambda: len(results) == n + 1)
    assert len(results) == 8


def test_callbacks_are_skipped_when_the_owner_is_gone(qapp):
    import shiboken6
    from PySide6.QtWidgets import QWidget

    from clipasso_studio.gui import dialogs

    owner = QWidget()
    called, gate = [], threading.Event()

    def work(progress):
        gate.wait(5)
        return "late"

    thread = dialogs.run_in_thread(owner, work, on_done=called.append)
    shiboken6.delete(owner)
    gate.set()
    _wait(qapp, lambda: thread.isFinished())
    for _ in range(20):
        qapp.processEvents()
        time.sleep(0.01)
    assert called == []


def _run_dir(tmp_path, frames=3):
    run = tmp_path / "run"
    os.makedirs(run / "svg_logs")
    for i in range(frames):
        (run / "svg_logs" / f"svg_iter{i}.svg").write_text(SVG.format(y=20 + 40 * i))
    (run / "best_iter.svg").write_text(SVG.format(y=100))
    return run


@pytest.mark.parametrize("fmt", ["gif", "mp4", "webp"])
def test_animation_export_runs_to_the_end(qapp, tmp_path, monkeypatch, fmt):
    from PySide6.QtWidgets import QDialog, QFileDialog

    from clipasso_studio.gui import dialogs

    run = _run_dir(tmp_path)
    dest = tmp_path / f"out.{fmt}"
    monkeypatch.setattr(QFileDialog, "getSaveFileName", lambda *a, **k: (str(dest), ""))
    dlg = dialogs.ExportDialog(fmt, str(run / "best_iter.svg"), str(run), "out")
    dlg._save()
    _wait(qapp, lambda: dlg.result() == QDialog.Accepted)
    assert dest.is_file() and dest.stat().st_size > 0
    assert dlg.saved_path == str(dest)


def test_animation_export_can_be_cancelled(qapp, tmp_path, monkeypatch):
    from PySide6.QtWidgets import QDialog, QFileDialog

    from clipasso_studio.gui import dialogs, export

    run = _run_dir(tmp_path, frames=40)
    dest = tmp_path / "out.gif"
    monkeypatch.setattr(QFileDialog, "getSaveFileName", lambda *a, **k: (str(dest), ""))
    original = export.svg_to_qimage

    def slow(*a, **k):
        time.sleep(0.05)
        return original(*a, **k)

    monkeypatch.setattr(export, "svg_to_qimage", slow)
    dlg = dialogs.ExportDialog("gif", str(run / "best_iter.svg"), str(run), "out")
    dlg._save()
    _wait(qapp, lambda: dlg.progress.value() >= 2)
    dlg.reject()
    assert dlg.isVisible() or dlg.result() != QDialog.Accepted
    _wait(qapp, lambda: dlg.busy is False)
    assert dlg.result() == QDialog.Rejected
    assert not dest.exists()


def _fake_install(calls, block=None):
    def install(key, cancel=None, progress=None):
        calls.append(key)
        for i in range(1, 6):
            if block is not None:
                while not (cancel and cancel()):
                    time.sleep(0.01)
            if cancel and cancel():
                raise InterruptedError("download cancelled")
            progress(i, 5)
            time.sleep(0.01)
        progress(0, 0)  # verifying / converting
        time.sleep(0.05)
        return key

    return install


def test_model_download_dialog_installs_all_and_closes(qapp, monkeypatch):
    from PySide6.QtWidgets import QDialog

    from clipasso_studio.engine import model_store
    from clipasso_studio.gui import dialogs

    calls = []
    monkeypatch.setattr(model_store, "install", _fake_install(calls))
    dlg = dialogs.ModelDownloadDialog(["u2net", "lama"])
    dlg._start()
    _wait(qapp, lambda: dlg.result() == QDialog.Accepted)
    assert calls == ["u2net", "lama"]


def test_model_download_dialog_cancel_stops_before_the_next_model(qapp, monkeypatch):
    from PySide6.QtWidgets import QDialog

    from clipasso_studio.engine import model_store
    from clipasso_studio.gui import dialogs

    calls = []
    monkeypatch.setattr(model_store, "install", _fake_install(calls, block=True))
    dlg = dialogs.ModelDownloadDialog(["u2net", "lama"])
    dlg._start()
    _wait(qapp, lambda: calls == ["u2net"])
    dlg.reject()
    _wait(qapp, lambda: dlg.busy is False)
    assert dlg.result() == QDialog.Rejected
    time.sleep(0.2)
    qapp.processEvents()
    assert calls == ["u2net"]


def test_export_dialog_length_sets_the_frame_rate(qapp, tmp_path):
    from clipasso_studio.gui import dialogs

    run = _run_dir(tmp_path, frames=40)
    dlg = dialogs.ExportDialog("gif", str(run / "best_iter.svg"), str(run), "out")
    assert dlg.length.value() == 2.0  # 40 frames: like 20 fps, at least 2 s
    dlg.length.setValue(4.0)
    dlg.hold.setValue(0.0)
    assert dlg.timing.text().startswith("≈ 10 fps") and "40" in dlg.timing.text()
    mp4 = dialogs.ExportDialog("mp4", str(run / "best_iter.svg"), str(run), "out")
    mp4.length.setValue(3.0)
    mp4.hold.setValue(1.0)
    assert mp4.timing.text().startswith("≈ 30 fps") and "120" in mp4.timing.text()


def test_matrix_export_dialog(qapp, tmp_path, monkeypatch):
    import json
    import zipfile

    from PySide6.QtWidgets import QDialog, QFileDialog

    from clipasso_studio.gui import dialogs

    job = tmp_path / "scene_job"
    runs = []
    for cell in (800, 801):
        run = job / f"cell{cell}"
        run.mkdir(parents=True)
        (run / "best_iter.svg").write_text(SVG.format(y=40 + cell % 100 * 50))
        runs.append({"seed": cell, "run_dir": str(run), "best_svg": str(run / "best_iter.svg")})
    (job / "job.json").write_text(json.dumps({"method": "scenesketch", "runs": runs}))
    dest = tmp_path / "m.zip"
    monkeypatch.setattr(QFileDialog, "getSaveFileName", lambda *a, **k: (str(dest), ""))
    dlg = dialogs.ExportDialog("matrix", runs[0]["best_svg"], str(job), "scene_job")
    dlg.size.setValue(128)
    dlg._save()
    _wait(qapp, lambda: dlg.result() == QDialog.Accepted)
    with zipfile.ZipFile(dest) as z:
        assert {"L8_level0.svg", "L8_level1.png", "matrix.png"} <= set(z.namelist())


def test_export_dialog_remembers_the_last_choices(qapp, tmp_path, monkeypatch):
    from PySide6.QtWidgets import QFileDialog

    from clipasso_studio.gui import dialogs
    from clipasso_studio.gui.app_settings import app_settings

    run = _run_dir(tmp_path, frames=3)
    s = app_settings()
    s.data.update(export_stroke="#ff0000", export_width=2.5, export_background="transparent",
                  export_dir=str(tmp_path / "exports"))
    os.makedirs(tmp_path / "exports", exist_ok=True)
    png = dialogs.ExportDialog("png", str(run / "best_iter.svg"), str(run), "out")
    assert png.stroke.color().lower() == "#ff0000" and png.width_scale.value() == 2.5
    assert png.background.color() == "transparent"
    gif = dialogs.ExportDialog("gif", str(run / "best_iter.svg"), str(run), "out")
    assert gif.background.color().lower() == "#ffffff"  # no transparency in a GIF
    starts = []

    def fake_save(parent, title, start, filt):
        starts.append(start)
        return str(tmp_path / "elsewhere" / "sketch.png"), filt

    os.makedirs(tmp_path / "elsewhere", exist_ok=True)
    monkeypatch.setattr(QFileDialog, "getSaveFileName", fake_save)
    png._save()
    _wait(qapp, lambda: not png.busy)  # written in the background
    assert os.path.dirname(starts[0]) == str(tmp_path / "exports")
    assert s.get("export_dir") == str(tmp_path / "elsewhere") and s.get("export_last_format") == "png"
    assert os.path.isfile(tmp_path / "elsewhere" / "sketch.png")


def test_every_saved_step_gets_a_frame(qapp, tmp_path):
    """Fine "drawing process" animations: a step saved every iteration -> one frame per step."""
    from clipasso_studio.gui import dialogs, export

    run = _run_dir(tmp_path, frames=700)  # more than the old limit of 600 frames
    dlg = dialogs.ExportDialog("gif", str(run / "best_iter.svg"), str(run), "out")
    assert dlg.every_step.isVisibleTo(dlg)
    assert len(export.animation_plan(700, dlg.length.value(), hold=0, fmt="gif", size=512)[0]) < 700  # default
    dlg.every_step.click()
    assert dlg.length.value() == export.every_step_length(700, "gif") == 14.0
    assert "700" in dlg.timing.text()
    idx, _ = export.animation_plan(700, dlg.length.value(), hold=0, fmt="gif", size=512)
    assert idx == list(range(700))
    mp4 = dialogs.ExportDialog("mp4", str(run / "best_iter.svg"), str(run), "out")
    mp4.every_step.click()
    idx, _ = export.animation_plan(700, mp4.length.value(), hold=0, fmt="mp4", size=512)
    assert sorted(set(idx)) == list(range(700))
    mp4.mode.setCurrentIndex(mp4.mode.findData("strokes"))
    assert not mp4.every_step.isVisibleTo(mp4)  # only for the drawing process


def test_export_dialog_shapes(qapp, tmp_path, user_data):
    import json

    from clipasso_studio.engine import framing
    from clipasso_studio.gui import dialogs
    from clipasso_studio.gui.app_settings import app_settings

    run = tmp_path / "run"
    run.mkdir()
    svg = ('<svg xmlns="http://www.w3.org/2000/svg" width="224" height="224" viewBox="0 0 224 224">'
           '<path d="M 20 100 C 60 100 120 100 200 110" fill="none" stroke="#000" stroke-width="2"/></svg>')
    (run / "best_iter.svg").write_text(svg)
    (run / "config.json").write_text("{}")
    dlg = dialogs.ExportDialog("png", str(run / "best_iter.svg"), str(run), "x")
    photo = dlg.frame.findData("photo")
    assert not dlg.frame.model().item(photo).isEnabled()  # an old run without a known photo shape
    dlg.frame.setCurrentIndex(dlg.frame.findData("content"))
    assert dlg.margin.isVisibleTo(dlg) and dlg._shape() == {"frame": "content", "margin": 0.05}
    dlg.frame.setCurrentIndex(dlg.frame.findData("square"))
    assert not dlg.margin.isVisibleTo(dlg)
    (run / "config.json").write_text(json.dumps({"photo_frame": framing.photo_frame((300, 200))}))
    app_settings().set("export_frame", "photo")
    dlg = dialogs.ExportDialog("svg", str(run / "best_iter.svg"), str(run), "x")
    assert dlg.frame.currentData() == "photo"  # remembered, and known now
    matrix = dialogs.ExportDialog("matrix", str(run / "best_iter.svg"), str(run), "x")
    assert not matrix.frame.isVisibleTo(matrix)
    batch = dialogs.BatchExportDialog([])
    assert batch.frame.model().item(photo).isEnabled()
    app_settings().set("export_frame", "square")
