"""Background work of the dialogs: callbacks in the GUI thread, export / download to the end, cancel."""

import os
import threading
import time

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

SVG = ('<svg xmlns="http://www.w3.org/2000/svg" width="224" height="224" viewBox="0 0 224 224">'
       '<path d="M 10 10 C 60 {y} 120 {y} 200 200" stroke="black" stroke-width="2" fill="none"/></svg>')


@pytest.fixture(scope="module")
def qapp(tmp_path_factory):
    tmp = tmp_path_factory.mktemp("appdata")
    os.environ["XDG_DATA_HOME"] = str(tmp)
    os.environ["LOCALAPPDATA"] = str(tmp)
    from PySide6.QtWidgets import QApplication

    app = QApplication.instance() or QApplication([])
    yield app
    from clipasso_studio.gui import dialogs

    dialogs.wait_for_threads()


def _wait(app, condition, timeout=30.0):
    end = time.time() + timeout
    while not condition():
        if time.time() > end:
            raise AssertionError("timed out")
        app.processEvents()
        time.sleep(0.01)


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


@pytest.mark.parametrize("fmt", ["gif", "mp4"])
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
