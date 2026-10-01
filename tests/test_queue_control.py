"""Queue control: per job pause / cancel / retry, drag and drop order, details, total time, kept failures."""

import os

import pytest


@pytest.fixture
def window(tmp_path, monkeypatch, qapp):
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path))
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path))
    from clipasso_studio.gui import app_settings as settings_module
    from clipasso_studio.gui import theme
    from clipasso_studio.gui.app_settings import app_settings

    settings_module._instance = None
    app_settings().data["output_dir"] = str(tmp_path / "out")
    theme.apply(qapp, "dark")
    from clipasso_studio.gui.main_window import MainWindow

    w = MainWindow()
    w.controller.start_next = lambda: None  # nothing really runs
    w.resize(1300, 800)
    w.show()
    w.show_page("queue")
    yield w
    w.studio.shutdown()
    w.controller.shutdown()
    w.close()
    settings_module._instance = None


def _image(tmp_path, name):
    from PIL import Image

    path = tmp_path / name
    Image.new("RGB", (40, 30), "white").save(path)
    return str(path)


def test_order_by_drag_and_drop(window, tmp_path):
    from PySide6.QtCore import QMimeData, QPoint, QPointF, Qt
    from PySide6.QtGui import QDropEvent

    from clipasso_studio import settings_schema as schema
    from clipasso_studio.gui.pages.other_pages import QUEUE_MIME

    c = window.controller
    a, b, d = (c.enqueue(_image(tmp_path, f"{n}.png"), schema.default_settings("clipasso"), start=False)
               for n in "abd")
    queue = window.queue
    c.move_to(d.id, 0)
    assert [j.id for j in c.jobs] == [d.id, a.id, b.id]
    c.move_to(d.id, 99)
    assert [j.id for j in c.jobs] == [a.id, b.id, d.id]

    from PySide6.QtWidgets import QApplication

    QApplication.processEvents()
    rows = queue.rows
    # dropping job "d" on the upper half of the first row puts it first
    data = QMimeData()
    data.setData(QUEUE_MIME, str(d.id).encode("ascii"))
    first = rows[a.id]
    pos = queue.list_host.mapTo(queue, QPoint(10, first.y() + 5))
    queue.dropEvent(QDropEvent(QPointF(pos), Qt.MoveAction, data, Qt.LeftButton, Qt.NoModifier))
    assert [j.id for j in c.jobs] == [d.id, a.id, b.id]
    # ... and below the last row last
    QApplication.processEvents()  # (the rows have moved)
    last = rows[b.id]
    pos = queue.list_host.mapTo(queue, QPoint(10, last.y() + last.height() - 2))
    queue.dropEvent(QDropEvent(QPointF(pos), Qt.MoveAction, data, Qt.LeftButton, Qt.NoModifier))
    assert [j.id for j in c.jobs] == [a.id, b.id, d.id]


def test_details_load_and_replace(window, tmp_path):
    from clipasso_studio import settings_schema as schema

    c = window.controller
    job = c.enqueue(_image(tmp_path, "cat.png"), {**schema.default_settings("clipasso"), "num_paths": 8,
                                                  "turbo": True}, start=False)
    queue = window.queue
    queue.rows[job.id].selected.emit(job.id)
    assert queue.detail.isVisibleTo(queue) and queue.selected_id == job.id
    text = queue.detail.changes.text()
    assert "8" in text and "16" in text  # strokes 8 (default 16)
    assert queue.detail.replace_btn.isVisibleTo(queue.detail)
    queue.detail.load_btn.click()
    assert window.studio.image_path == job.target and window.studio.params.settings()["num_paths"] == 8
    window.studio.params.fields["num_paths"].set_value(24, emit=True)
    window.show_page("queue")
    queue.detail.replace_btn.click()
    assert job.settings["num_paths"] == 24
    assert queue.total.isVisibleTo(queue) and "≈" in queue.total.text()


def test_retry_continues_and_failures_are_kept(window, tmp_path):
    from clipasso_studio import settings_schema as schema
    from clipasso_studio.engine import jobs
    from clipasso_studio.gui.app_settings import app_settings
    from clipasso_studio.gui.controller import JobController

    c = window.controller
    target = _image(tmp_path, "dog.png")
    job = c.enqueue(target, {**schema.default_settings("clipasso"), "num_sketches": 2}, start=False)
    job_dir = str(tmp_path / "out" / "dog_job")
    os.makedirs(job_dir)
    jobs.write_state(job_dir, target, job.settings, "failed")
    job.status, job.job_dir, job.message = "failed", job_dir, "RuntimeError: boom"
    c._persist_queue()
    c.queue_changed.emit()
    saved = app_settings().get("queue")
    assert saved[0]["status"] == "failed" and saved[0]["job_dir"] == job_dir

    other = JobController()  # after a restart: the failed job is still there and can be tried again
    try:
        kept = other.jobs[0]
        assert kept.status == "failed" and kept.message == "RuntimeError: boom" and kept.job_dir == job_dir
    finally:
        other.shutdown()

    row = window.queue.rows[job.id]
    assert row.retry.isVisibleTo(row) and not row.pause.isVisibleTo(row)
    row.retry.click()
    assert job.status == "queued" and job.resume_dir == job_dir and job.message == ""
    assert app_settings().get("queue")[0].get("status") is None  # waiting again
    assert c.retry(job.id) is None  # only failed / cancelled jobs


def test_running_row_controls(window, tmp_path, monkeypatch):
    from PySide6.QtWidgets import QMessageBox

    from clipasso_studio import settings_schema as schema

    c = window.controller
    job = c.enqueue(_image(tmp_path, "owl.png"), schema.default_settings("clipasso"), start=False)
    job.status, job.eta = "running", 120.0
    c.current = job
    calls = []
    monkeypatch.setattr(c.runner, "pause", lambda: calls.append("pause"))
    monkeypatch.setattr(c.runner, "resume", lambda: calls.append("resume"))
    monkeypatch.setattr(c.runner, "cancel", lambda: calls.append("cancel"))
    monkeypatch.setattr(QMessageBox, "question", lambda *a, **k: QMessageBox.Yes)
    try:
        c.queue_changed.emit()
        row = window.queue.rows[job.id]
        assert row.pause.isVisibleTo(row) and row.cancel.isVisibleTo(row) and not row.remove.isEnabled()
        row.pause.click()
        assert job.status == "paused"
        row.pause.click()
        assert job.status == "running"
        row.cancel.click()
        assert calls == ["pause", "resume", "cancel"] and job.message == "cancel"
        assert c.remaining_seconds() == pytest.approx(120.0)
    finally:
        c.current = None
        job.status = "cancelled"
        c.queue_changed.emit()
