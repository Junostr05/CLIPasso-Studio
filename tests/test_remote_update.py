"""3.8: the update from the phone – look for it, download it, install it and start again without a question on the PC;
only with the PIN; a running job and the queue go on after the restart; an installation for all users only
downloads."""

import hashlib
import json
import os
import threading
from http.server import ThreadingHTTPServer

import pytest

from tests.helpers import wait_until
from tests.test_reliability import _Api, _Files


class _Window:
    """What the updater needs of the main window."""

    def __init__(self):
        self.restarts = []
        self.shown = []
        self.update_bar = self

    def restart_for_update(self, path, mode, version):
        self.restarts.append((path, mode, version))

    def show_release(self, release):
        self.shown.append(release["tag"])


@pytest.fixture
def release_server(user_data):
    setup = os.urandom(4000)
    sums = f"{hashlib.sha256(setup).hexdigest()}  CLIPassoStudio-CPU-Setup.exe\n"
    _Files.files = {"CLIPassoStudio-CPU-Setup.exe": setup, "SHA256SUMS-CPU.txt": sums.encode()}
    files = ThreadingHTTPServer(("127.0.0.1", 0), _Files)
    api = ThreadingHTTPServer(("127.0.0.1", 0), _Api)
    for httpd in (files, api):
        threading.Thread(target=httpd.serve_forever, daemon=True).start()
    base = f"http://127.0.0.1:{files.server_address[1]}/dl"
    _Api.release = {"tag_name": "v99.0.0", "body": "## New\n- everything", "prerelease": False,
                    "assets": [{"name": n, "browser_download_url": f"{base}/{n}", "size": len(d)}
                               for n, d in _Files.files.items()]}
    yield f"http://127.0.0.1:{api.server_address[1]}/releases/latest", setup
    files.shutdown()
    api.shutdown()


@pytest.fixture
def updater(qapp, user_data, monkeypatch):
    from clipasso_studio.gui import app_settings as settings_module
    from clipasso_studio.gui import remote_update, updates

    settings_module._instance = None
    monkeypatch.setattr(updates, "build_info", lambda exe=None: ("cpu", "installed"))
    monkeypatch.setattr(updates, "all_users_install", lambda app_dir, edition="cpu": False)
    u = remote_update.Updater()
    u.window = _Window()
    yield u
    settings_module._instance = None


def test_check_download_and_restart(qapp, updater, release_server):
    url, setup = release_server
    assert updater.snapshot()["phase"] == "idle" and updater.install_mode() == "auto"
    assert not updater.install()  # nothing found yet
    assert updater.check(url=url)
    wait_until(qapp, lambda: updater.phase != "checking")
    snap = updater.snapshot()
    assert snap["phase"] == "found" and snap["latest"] == "99.0.0" and snap["can_install"]
    assert "everything" in snap["notes"]
    assert updater.install()
    wait_until(qapp, lambda: updater.phase in ("restarting", "failed"), 20)
    assert updater.phase == "restarting", updater.error
    wait_until(qapp, lambda: updater.window.restarts, 5)
    path, mode, version = updater.window.restarts[0]
    assert mode == "installed" and version == "99.0.0" and open(path, "rb").read() == setup
    assert updater.done == updater.total == len(setup)


def test_all_users_only_downloads(qapp, updater, release_server, monkeypatch):
    from clipasso_studio.gui import updates

    monkeypatch.setattr(updates, "all_users_install", lambda app_dir, edition="cpu": True)
    url, _ = release_server
    assert updater.install_mode() == "download"  # Windows would ask for an administrator on the PC
    updater.check(url=url)
    wait_until(qapp, lambda: updater.phase == "found")
    updater.install()
    wait_until(qapp, lambda: updater.phase in ("downloaded", "failed"), 20)
    assert updater.phase == "downloaded" and not updater.window.restarts
    assert updater.window.shown == ["v99.0.0"]  # the PC's update bar offers to install it


def test_from_source_and_up_to_date(qapp, updater, release_server, monkeypatch):
    from clipasso_studio.gui import updates

    url, _ = release_server
    _Api.release = {"tag_name": "v0.0.1", "prerelease": False, "assets": []}
    updater.check(url=url)
    wait_until(qapp, lambda: updater.phase != "checking")
    assert updater.phase == "current"
    monkeypatch.setattr(updates, "build_info", lambda exe=None: ("dev", "dev"))
    assert updater.install_mode() == "none"
    updater.check(url="http://127.0.0.1:9/none")
    wait_until(qapp, lambda: updater.phase != "checking")
    assert updater.phase == "failed" and updater.error


def test_the_job_and_the_queue_go_on_after_the_restart(qapp, user_data, tmp_path, monkeypatch):
    from clipasso_studio import settings_schema as schema
    from clipasso_studio.engine import jobs
    from clipasso_studio.gui import app_settings as settings_module
    from clipasso_studio.gui import remote_update
    from clipasso_studio.gui.app_settings import app_settings
    from clipasso_studio.gui.controller import JobController, QueuedJob

    settings_module._instance = None
    photo = tmp_path / "camel.png"
    photo.write_bytes(b"x")
    job_dir = tmp_path / "out" / "camel_job"
    job_dir.mkdir(parents=True)
    (job_dir / jobs.STATE_FILE).write_text(json.dumps({"status": "running", "settings": {}}), encoding="utf-8")
    c = JobController()
    try:
        running = QueuedJob(target=str(photo), settings=schema.default_settings("clipasso"), status="running",
                            job_dir=str(job_dir))
        waiting = QueuedJob(target=str(photo), settings=schema.default_settings("swiftsketch"))
        c.jobs[:] = [running, waiting]
        c.current = running
        resume = c.hold_for_restart()
        assert resume == [str(job_dir)]
        queue = app_settings().get("queue")
        assert [q.get("resume_dir", "") for q in queue] == [str(job_dir), ""]  # the job first, from its folder
        remote_update.write_pending("99.0.0", resume, run_queue=True)
    finally:
        c.shutdown()
    # the new version starts
    settings_module._instance = None
    monkeypatch.setattr(remote_update, "__version__", "99.0.0")
    c2 = JobController()
    started = []
    monkeypatch.setattr(c2, "start_next", lambda: started.append(True))
    try:
        assert [j.resume_dir for j in c2.jobs] == [str(job_dir), ""]
        u = remote_update.Updater()
        last = u.finish_pending(c2)
        assert last == {"ok": True, "from": __import__("clipasso_studio").__version__, "to": "99.0.0"}
        assert started and app_settings().get(remote_update.PENDING) is None
        assert jobs.read_state(str(job_dir)).get("asked")  # not asked about at the start: it simply goes on
        assert u.finish_pending(c2) is None  # (once)
    finally:
        c2.shutdown()
    settings_module._instance = None


def test_installing_from_the_phone_needs_the_pin(qapp, user_data, tmp_path):
    from clipasso_studio.gui import app_settings as settings_module
    from clipasso_studio.gui import remote
    from tests.test_phone import _in_thread, _post

    settings_module._instance = None
    remote.pin_guard.__init__()
    seen = []
    bridge = remote.RemoteBridge()
    bridge.texts = {"lang": "en"}
    bridge.handler = lambda action, data: (seen.append((action, data.get("_pin_ok"))), {"ok": True})[1]
    srv = remote.RemoteServer(bridge, port=0, host="127.0.0.1", upload_dir=str(tmp_path / "up")).start()
    base, head = f"http://127.0.0.1:{srv.port}", {"X-Access": remote.token(), "Content-Type": "application/json"}
    try:
        def do(body):
            return _in_thread(qapp, lambda: _post(base + "/api/do", json.dumps(body).encode(), head))

        status, answer = do({"action": "install_update", "pin": "000000" if remote.pin() != "000000" else "111111"})
        assert status == 403 and answer["error"] == "pin" and not seen
        status, answer = do({"action": "install_update", "pin": remote.pin(), "_pin_ok": True})
        assert status == 200 and seen == [("do_install_update", True)]
        seen.clear()
        status, answer = do({"action": "check_update", "_pin_ok": True})  # (only the server says the PIN was right)
        assert status == 200 and seen == [("do_check_update", None)]
        for _ in range(remote.PIN_TRIES):  # the brakes of the sign-in
            status, answer = do({"action": "install_update", "pin": "12"})
        assert status == 429 and answer["wait"] > 0
        status, _ = do({"action": "install_update", "pin": remote.pin()})
        assert status == 429  # also the right PIN waits
    finally:
        srv.stop()
        remote.pin_guard.__init__()
        settings_module._instance = None


def test_the_version_tells_the_page_to_load_again(qapp, user_data, tmp_path):
    import clipasso_studio
    from clipasso_studio.gui import app_settings as settings_module
    from clipasso_studio.gui import remote
    from tests.test_phone import _get

    settings_module._instance = None
    bridge = remote.RemoteBridge()
    bridge.texts = {"lang": "en"}
    srv = remote.RemoteServer(bridge, port=0, host="127.0.0.1", upload_dir=str(tmp_path / "up")).start()
    base = f"http://127.0.0.1:{srv.port}"
    try:
        _, headers, _ = _get(base + f"/?t={remote.token()}")
        cookie = headers["Set-Cookie"].split(";")[0]
        assert json.loads(_get(base + "/api/status", cookie)[2])["version"] == clipasso_studio.__version__
        page = _get(base + "/", cookie)[2].decode()
        assert f'"version": "{clipasso_studio.__version__}"' in page
    finally:
        srv.stop()
        settings_module._instance = None


def test_the_main_window_restarts_without_a_question(qapp, tmp_path, monkeypatch):
    """The window closes without asking (nobody may be at the PC) and says after the restart how it went."""
    from clipasso_studio.gui import app_settings as settings_module
    from clipasso_studio.gui import remote_update
    from clipasso_studio.gui.app_settings import app_settings
    from clipasso_studio.gui.main_window import MainWindow

    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path))
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path))
    settings_module._instance = None
    app_settings().data.update(output_dir=str(tmp_path / "out"), tour_done=True)
    w = MainWindow()
    w.controller.start_next = lambda: None
    try:
        assert remote_update.updater().window is w
        runs = []
        monkeypatch.setattr(w, "run_installer", lambda path, mode: (runs.append((path, mode, w._unattended)), False)[1])
        assert not w.restart_for_update("setup.exe", "installed", "99.0.0")
        assert runs == [("setup.exe", "installed", True)]
        assert not w._unattended and app_settings().get(remote_update.PENDING) is None  # (it did not close)
        remote_update.write_pending("99.0.0", [], run_queue=False)  # an update that did not get installed
        shown = []
        monkeypatch.setattr(w.toast, "show_message", lambda text, kind="info": shown.append((text, kind)))
        w.check_interrupted_jobs()
        assert shown and shown[0][1] == "warning" and "99.0.0" in shown[0][0]
        assert remote_update.updater().snapshot()["last"]["ok"] is False
    finally:
        w.studio.shutdown()
        w.controller.shutdown()
        w.close()
        remote_update.updater().last = None
        settings_module._instance = None
