"""Crash log and update notice."""

import json
import os
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")


@pytest.fixture(scope="module")
def qapp():
    from PySide6.QtWidgets import QApplication

    return QApplication.instance() or QApplication([])


def _wait(app, condition, timeout=10.0):
    end = time.time() + timeout
    while not condition():
        if time.time() > end:
            raise AssertionError("timed out")
        app.processEvents()
        time.sleep(0.01)


# ------------------------------------------------------------------ updates
def test_versions():
    from clipasso_studio.gui.updates import is_newer, parse_version

    assert is_newer("v2.2.0", "2.1.0")
    assert is_newer("v2.1.0", "2.1.0b1")  # the final release after the experimental build
    assert parse_version("v2.1.0-beta.1") == parse_version("2.1.0b1")
    assert not is_newer("v2.1.0", "2.1.0") and not is_newer("v2.0.1", "2.1.0")
    assert is_newer("v10.0.0", "9.9.9") and is_newer("v2.1.1", "2.1")


class _Api(BaseHTTPRequestHandler):
    release: dict = {}

    def do_GET(self):  # noqa: N802
        body = json.dumps(_Api.release).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *args):
        pass


@pytest.fixture
def api():
    httpd = ThreadingHTTPServer(("127.0.0.1", 0), _Api)
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    yield f"http://127.0.0.1:{httpd.server_address[1]}/releases/latest"
    httpd.shutdown()


def test_update_check(api):
    from clipasso_studio.gui import updates

    _Api.release = {"tag_name": "v9.0.0", "html_url": "https://example.invalid/r", "prerelease": False}
    found = json.loads(updates.check(url=api, current="2.2.0"))
    assert found["tag"] == "v9.0.0" and found["url"] == "https://example.invalid/r"
    _Api.release = {"tag_name": "v2.2.0", "prerelease": False}
    assert updates.check(url=api, current="2.2.0") == ""
    _Api.release = {"tag_name": "v9.0.0-beta.1", "prerelease": True}
    assert updates.check(url=api, current="2.2.0") == ""
    assert updates.check(url="http://127.0.0.1:9/nothing", current="2.2.0") == ""  # offline: nothing


def test_update_bar(qapp, api, tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path))
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path))
    from clipasso_studio.gui.app_settings import app_settings
    from clipasso_studio.gui.main_window import MainWindow

    app_settings().data.update(output_dir=str(tmp_path / "out"), check_updates=True, skipped_version="")
    w = MainWindow()
    w.show()
    _Api.release = {"tag_name": "v9.1.0", "html_url": "https://example.invalid/r", "prerelease": False}
    w.start_update_check(url=api)
    _wait(qapp, lambda: w.update_wrap.isVisible())
    assert "9.1.0" in w.update_bar.text.text()
    w.update_bar.skip.click()
    assert not w.update_wrap.isVisible() and app_settings().get("skipped_version") == "v9.1.0"
    w.start_update_check(url=api)  # the skipped version is not shown again
    time.sleep(0.3)
    for _ in range(30):
        qapp.processEvents()
        time.sleep(0.01)
    assert not w.update_wrap.isVisible()
    app_settings().data["check_updates"] = False
    w.controller.shutdown()
    w.close()


# -------------------------------------------------------------- crash log
@pytest.fixture
def crash(qapp, tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path))
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path))
    from clipasso_studio.gui import crash as mod

    shown = []
    monkeypatch.setattr(mod, "_show_dialog",
                        lambda path, details: shown.append((threading.current_thread() is threading.main_thread(),
                                                            path, details)))
    mod.install()
    yield mod, shown
    mod.uninstall()


def test_an_error_in_a_slot_is_logged_and_shown(crash, qapp):
    from PySide6.QtCore import QTimer

    mod, shown = crash

    def broken():
        raise ValueError("boom in a slot")

    QTimer.singleShot(0, broken)
    _wait(qapp, lambda: shown)
    in_gui_thread, path, details = shown[0]
    assert in_gui_thread and "boom in a slot" in details
    assert os.path.isfile(path) and "boom in a slot" in open(path, encoding="utf-8").read()


def test_an_error_in_a_background_thread_is_shown_in_the_gui_thread(crash, qapp):
    mod, shown = crash

    def worker():
        raise RuntimeError("boom in a thread")

    t = threading.Thread(target=worker, name="worker-1")
    t.start()
    t.join()
    _wait(qapp, lambda: shown)
    in_gui_thread, path, details = shown[0]
    assert in_gui_thread and "boom in a thread" in details and "worker-1" in details


def test_qt_warnings_go_to_the_log(crash):
    from PySide6.QtCore import qWarning

    mod, _ = crash
    qWarning("a test warning")
    assert "a test warning" in (mod.logs_dir() / "qt.log").read_text(encoding="utf-8")


def test_a_hard_crash_is_reported_at_the_next_start(qapp, tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path))
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path))
    from clipasso_studio.gui import crash as mod

    (mod.logs_dir() / mod.FAULT_LOG).write_text("Fatal Python error: Segmentation fault\n")
    mod.install()
    try:
        previous = mod.previous_crash()
        assert previous is not None and "Segmentation fault" in previous.read_text(encoding="utf-8")
        assert (mod.logs_dir() / mod.FAULT_LOG).stat().st_size == 0  # ready for this session
    finally:
        mod.uninstall()
