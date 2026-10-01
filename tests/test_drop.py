"""Drag & drop of images and folders onto the studio, the queue and the window."""

import os

import pytest
from PIL import Image

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")


@pytest.fixture(scope="module")
def window(tmp_path_factory):
    tmp = tmp_path_factory.mktemp("dropdata")
    env = pytest.MonkeyPatch()
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
    w.controller.start_next = lambda: None  # queue only
    w.show()
    yield w
    w.studio.shutdown()
    w.controller.shutdown()
    w.close()
    settings_module._instance = None
    env.undo()


def _images(folder, names):
    os.makedirs(folder, exist_ok=True)
    for n in names:
        Image.new("RGB", (20, 20), "white").save(os.path.join(folder, n))
    return [os.path.join(folder, n) for n in names]


def _mime(paths):
    from PySide6.QtCore import QMimeData, QUrl

    m = QMimeData()
    m.setUrls([QUrl.fromLocalFile(str(p)) for p in paths])
    return m


def _drop(widget, paths):
    from PySide6.QtCore import QPointF, Qt
    from PySide6.QtGui import QDropEvent

    mime = _mime(paths)  # the event does not own it: keep it alive while it is handled
    ev = QDropEvent(QPointF(5, 5), Qt.CopyAction, mime, Qt.LeftButton, Qt.NoModifier)
    widget.dropEvent(ev)
    return ev, mime


def test_dropped_images_files_and_folders(tmp_path):
    from clipasso_studio.gui import drop

    a, = _images(tmp_path / "loose", ["a.png"])
    _images(tmp_path / "folder", ["b.jpg", "c.PNG"])
    _images(tmp_path / "folder" / "sub", ["d.webp"])
    (tmp_path / "folder" / "notes.txt").write_text("x")
    job = tmp_path / "folder" / "result_job"
    _images(job, ["sketch.png"])
    (job / "job.json").write_text("{}")  # the app's own results are skipped
    got = drop.dropped_images(_mime([a, tmp_path / "folder", tmp_path / "loose" / "nothing.txt", a]))
    assert [os.path.basename(p) for p in got] == ["a.png", "b.jpg", "c.PNG", "d.webp"]
    assert drop.has_images(_mime([tmp_path / "folder"])) and not drop.has_images(_mime([tmp_path / "x.txt"]))


def test_drop_zone_signals(window, tmp_path, monkeypatch):
    from PySide6.QtWidgets import QMessageBox

    monkeypatch.setattr(QMessageBox, "exec", lambda self: 0)  # the studio asks about the queue
    zone = window.studio.drop
    one, many = [], []
    zone.image_dropped.connect(one.append)
    zone.images_dropped.connect(many.append)
    files = _images(tmp_path / "z", ["a.png", "b.png"])
    _drop(zone, files[:1])
    _drop(zone, files)
    assert one == files[:1] and many == [files]


def test_queue_page_drop_adds_all(window, tmp_path):
    files = _images(tmp_path / "q", ["a.png", "b.png", "c.png"])
    before = len(window.controller.jobs)
    toasts = []
    window.queue.toast.connect(lambda text, kind: toasts.append(text))
    _drop(window.queue, [tmp_path / "q"])
    assert len(window.controller.jobs) == before + 3 and toasts and "3" in toasts[-1]
    assert [j.target for j in window.controller.jobs[-3:]] == files


def test_studio_many_images(window, tmp_path, monkeypatch):
    from PySide6.QtWidgets import QMessageBox

    files = _images(tmp_path / "s", ["x.png", "y.png"])
    monkeypatch.setattr(QMessageBox, "exec", lambda self: 0)  # closed: only the first one
    before = len(window.controller.jobs)
    window.studio.images_dropped(files)
    assert window.studio.image_path == files[0] and len(window.controller.jobs) == before
    assert window.studio.queue_paths(files) == 2 and len(window.controller.jobs) == before + 2


def test_window_routes_drops(window, tmp_path, monkeypatch):
    from PySide6.QtWidgets import QMessageBox

    monkeypatch.setattr(QMessageBox, "exec", lambda self: 0)
    files = _images(tmp_path / "w", ["one.png"])
    window.show_page("gallery")
    _drop(window, files)  # another page: opened in the studio
    assert window.stack.currentWidget() is window.studio and window.studio.image_path == files[0]
    window.show_page("queue")
    before = len(window.controller.jobs)
    _drop(window, files)
    assert len(window.controller.jobs) == before + 1
