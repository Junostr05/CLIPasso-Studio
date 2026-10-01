"""Crash log and update notice."""

import json
import os
import sys
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest

from tests.helpers import wait_until


def _wait(app, condition, timeout=10.0):
    wait_until(app, condition, timeout)


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


# ------------------------------------------------------------- update install
RELEASE_ASSETS = ["CLIPassoStudio-CPU-Portable.exe", "CLIPassoStudio-CPU-Setup.exe", "CLIPassoStudio-GPU-Setup-1.bin",
                  "CLIPassoStudio-GPU-Setup-2.bin", "CLIPassoStudio-GPU-Setup.exe", "SHA256SUMS-CPU.txt",
                  "SHA256SUMS-GPU.txt"]


def _release(base="http://x", sizes=None):
    sizes = sizes or {}
    return {"tag": "v9.0.0", "url": "https://example.invalid/r",
            "assets": [{"name": n, "url": f"{base}/{n}", "size": sizes.get(n, 100)} for n in RELEASE_ASSETS]}


def test_update_files_per_edition():
    from clipasso_studio.gui import updates

    names = lambda files: [f["name"] for f in files]  # noqa: E731
    files, sums = updates.update_files(_release(), "gpu", "installed")
    assert names(files) == ["CLIPassoStudio-GPU-Setup.exe", "CLIPassoStudio-GPU-Setup-1.bin",
                            "CLIPassoStudio-GPU-Setup-2.bin"] and sums["name"] == "SHA256SUMS-GPU.txt"
    assert names(updates.update_files(_release(), "cpu", "portable")[0]) == ["CLIPassoStudio-CPU-Portable.exe"]
    assert updates.can_install(_release(), "cpu", "installed")
    assert not updates.can_install(_release(), "gpu", "portable")  # there is no portable GPU edition
    assert not updates.can_install(_release(), "dev", "dev")
    sums_text = "a" * 64 + "  CLIPassoStudio-CPU-Setup.exe\n" + "B" * 64 + " *dist/x.bin\n"
    assert updates.parse_sums(sums_text) == {"CLIPassoStudio-CPU-Setup.exe": "a" * 64, "x.bin": "b" * 64}


class _Files(BaseHTTPRequestHandler):
    files: dict = {}

    def do_GET(self):  # noqa: N802
        data = _Files.files.get(self.path.rsplit("/", 1)[-1])
        if data is None:
            self.send_response(404)
            self.end_headers()
            return
        rng = self.headers.get("Range")
        start = int(rng.split("=")[1].split("-")[0]) if rng else 0
        body = data[start:]
        self.send_response(206 if rng else 200)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *args):
        pass


def test_download_and_install_command(tmp_path):
    import hashlib

    from clipasso_studio.gui import updates

    setup, part1, part2 = os.urandom(3000), os.urandom(2000), os.urandom(1000)
    sums = "".join(f"{hashlib.sha256(d).hexdigest()}  {n}\n" for n, d in (
        ("CLIPassoStudio-GPU-Setup.exe", setup), ("CLIPassoStudio-GPU-Setup-1.bin", part1),
        ("CLIPassoStudio-GPU-Setup-2.bin", part2)))
    _Files.files = {"CLIPassoStudio-GPU-Setup.exe": setup, "CLIPassoStudio-GPU-Setup-1.bin": part1,
                    "CLIPassoStudio-GPU-Setup-2.bin": part2, "SHA256SUMS-GPU.txt": sums.encode()}
    httpd = ThreadingHTTPServer(("127.0.0.1", 0), _Files)
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    base = f"http://127.0.0.1:{httpd.server_address[1]}/dl"
    try:
        release = _release(base, {"CLIPassoStudio-GPU-Setup.exe": 3000, "CLIPassoStudio-GPU-Setup-1.bin": 2000,
                                  "CLIPassoStudio-GPU-Setup-2.bin": 1000})
        progress = []
        path = updates.download_update(release, "gpu", "installed", tmp_path / "upd",
                                       progress=lambda a, b: progress.append((a, b)))
        assert path.endswith("CLIPassoStudio-GPU-Setup.exe") and open(path, "rb").read() == setup
        assert (tmp_path / "upd" / "CLIPassoStudio-GPU-Setup-2.bin").read_bytes() == part2
        assert progress[-1] == (6000, 6000)
        # a corrupted file is refused and removed
        _Files.files["CLIPassoStudio-GPU-Setup-1.bin"] = b"x" * 2000
        with pytest.raises(RuntimeError, match="checksum"):
            updates.download_update(release, "gpu", "installed", tmp_path / "bad")
        assert not (tmp_path / "bad" / "CLIPassoStudio-GPU-Setup-1.bin").exists()
    finally:
        httpd.shutdown()
    program, args = updates.install_command(path, "installed", app_dir=str(tmp_path))
    assert program == path and "/SILENT" in args and "/UPDATE" in args and "/CURRENTUSER" in args
    assert updates.install_command(path, "portable") == (path, [])
    exe_dir = tmp_path / "app"
    exe_dir.mkdir()
    placed = updates.place_portable(path, "v9.0.0", exe=str(exe_dir / "CLIPassoStudio-CPU-Portable.exe"))
    assert placed == str(exe_dir / "CLIPassoStudio-GPU-Setup-9.0.0.exe") and os.path.isfile(placed)


def test_install_scope_follows_the_installation(tmp_path, monkeypatch):
    """An all-users installation (Program Files) is updated for all users, a per-user one per user."""
    from clipasso_studio.gui import updates

    def scope_of(registered, writable=True):
        monkeypatch.setattr(updates, "_registered_scope", lambda edition: registered)
        monkeypatch.setattr(updates, "_folder_writable", lambda folder: writable)
        return updates.install_command("setup.exe", "installed", app_dir=str(tmp_path), edition="gpu")[1][-2]

    assert scope_of("all") == "/ALLUSERS"
    assert scope_of("user", writable=False) == "/CURRENTUSER"  # the registration wins
    assert scope_of(None, writable=False) == "/ALLUSERS"
    assert scope_of(None, writable=True) == "/CURRENTUSER"
    monkeypatch.undo()
    assert updates._folder_writable(str(tmp_path)) and not os.listdir(tmp_path)  # the probe file is gone
    assert not updates._folder_writable(str(tmp_path / "missing"))


@pytest.mark.skipif(sys.platform != "win32", reason="the Windows registry")
def test_registered_scope_of_an_unknown_edition():
    from clipasso_studio.gui import updates

    assert updates._registered_scope("no-such-edition") is None


def test_update_bar_offers_install(qapp, tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path))
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path))
    from clipasso_studio.gui import app_settings as settings_module
    from clipasso_studio.gui import updates

    settings_module._instance = None
    from clipasso_studio.gui.app_settings import app_settings
    from clipasso_studio.gui.main_window import MainWindow

    app_settings().data.update(output_dir=str(tmp_path / "out"))
    w = MainWindow()
    w.show()
    monkeypatch.setattr(updates, "build_info", lambda: ("cpu", "installed"))
    w._update_found(json.dumps(_release()))
    assert w.update_bar.install.isVisibleTo(w)
    requested = []
    monkeypatch.setattr(w, "install_update", lambda release: requested.append(release))
    w.update_bar.install_requested.disconnect()
    w.update_bar.install_requested.connect(w.install_update)
    w.update_bar.install.click()
    assert requested and requested[0]["tag"] == "v9.0.0"
    monkeypatch.setattr(updates, "build_info", lambda: ("dev", "dev"))
    w.update_bar.retranslate()
    assert not w.update_bar.install.isVisibleTo(w)  # from source: only the release page
    w.controller.shutdown()
    w.close()
    settings_module._instance = None


def test_plan_workers():
    """The seeds of a job run in parallel automatically only on a big CPU with enough memory."""
    from clipasso_studio import settings_schema as schema
    from clipasso_studio.engine.runner import plan_workers

    clip = schema.default_settings("clipasso")  # 3 sketches
    gb = 1_000_000_000
    assert plan_workers(clip, 3, auto=True, hw=(8, 16 * gb)) == 3
    assert plan_workers(clip, 3, auto=True, hw=(4, 32 * gb)) == 1  # too few cores
    assert plan_workers(clip, 3, auto=True, hw=(8, 6 * gb)) == 1  # 6 - 2 GB reserve: room for one
    assert plan_workers(clip, 3, auto=True, hw=(16, 9 * gb)) == 2
    assert plan_workers(clip, 3, auto=False, hw=(16, 64 * gb)) == 1  # switched off
    assert plan_workers(clip, 3, auto=True, cuda=True, hw=(16, 64 * gb)) == 1  # the GPU computes
    assert plan_workers({**clip, "device": "cpu"}, 3, auto=True, cuda=True, hw=(16, 64 * gb)) == 3
    assert plan_workers(clip, 1, auto=True, hw=(16, 64 * gb)) == 1
    assert plan_workers({**clip, "multiprocess": True}, 3, auto=False, hw=(2, 0)) == 3  # always, when chosen
    ctrl = schema.default_settings("controlsketch")
    assert plan_workers({**ctrl, "num_sketches": 3}, 3, auto=True, hw=(16, 64 * gb)) == 1  # big models
