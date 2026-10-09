"""Diagnostics and logs: app.log is rotated, a crashed worker leaves its stacks, crash logs name the
edition / torch / GPU, and the settings copy or save one text with everything a bug report needs."""

import faulthandler
import os
import subprocess
import sys

import pytest

HW = {"torch": "2.11.0+cu128", "cuda_build": "12.8", "cuda": True, "version": None,
      "gpus": [{"name": "NVIDIA GeForce RTX 4070", "memory_gb": 12.0, "supported": True}]}


@pytest.fixture
def fresh_settings(user_data):
    from clipasso_studio import __version__
    from clipasso_studio.gui import app_settings as settings_module
    from clipasso_studio.gui.app_settings import app_settings

    settings_module._instance = None
    app_settings().data["hardware"] = dict(HW, version=__version__)
    yield user_data
    settings_module._instance = None


def test_app_log_is_rotated(user_data):
    from clipasso_studio import logs

    stream = logs.RotatingStream(logs.logs_dir() / "app.log", max_bytes=100, backups=2)
    for i in range(40):
        stream.write(f"line {i:03d}\n")  # 9 bytes each: a new file after 12 lines
    stream.close()
    names = sorted(p.name for p in logs.logs_dir().iterdir())
    assert names == ["app.log", "app.log.1", "app.log.2"]
    assert all(p.stat().st_size <= 100 + 10 for p in logs.logs_dir().iterdir())  # (a line with "\r\n": 10 bytes)
    assert logs.tail(logs.logs_dir() / "app.log", 5)[-1] == "line 039"
    assert logs.tail(logs.logs_dir() / "app.log", 15)[0] == "line 025"  # also from app.log.1


def test_old_log_is_moved_into_the_logs_folder(user_data):
    from clipasso_studio import logs, paths

    (paths.user_data_dir() / "app.log").write_text("from 2.4\n", encoding="utf-8")
    stream = logs.open_log("app.log")
    stream.write("from 3.0\n")
    stream.close()
    assert not (paths.user_data_dir() / "app.log").exists()
    assert (logs.logs_dir() / "app.log").read_text(encoding="utf-8") == "from 2.4\nfrom 3.0\n"


def test_worker_log_is_removed_after_a_clean_end(user_data):
    from clipasso_studio import logs

    was_on = faulthandler.is_enabled()
    f = logs.start_worker_log()
    assert logs.worker_log_path(os.getpid()).exists()
    logs.end_worker_log(f)
    assert not logs.worker_log_path(os.getpid()).exists()
    assert logs.read_worker_log(os.getpid()) == ""
    # a faulthandler that was on stays on (here: pytest's – a hard crash in a later test still shows its stacks)
    assert faulthandler.is_enabled() == was_on


def test_a_crashed_worker_leaves_its_stacks(user_data):
    from clipasso_studio import logs

    code = ("from clipasso_studio import logs\nlogs.start_worker_log()\nimport faulthandler\n"
            "faulthandler._sigsegv()\n")
    proc = subprocess.Popen([sys.executable, "-c", code], env=dict(os.environ), stderr=subprocess.DEVNULL)
    assert proc.wait(timeout=60) != 0
    text = logs.read_worker_log(proc.pid)
    assert "Fatal Python error" in text and "Segmentation fault" in text
    # an empty file of a process that is gone is cleaned up, a crash is kept
    (logs.logs_dir() / "worker-999999999.log").write_text("")
    logs._prune_worker_logs()
    assert not (logs.logs_dir() / "worker-999999999.log").exists()
    assert logs.worker_log_path(proc.pid).exists()


def test_report_and_crash_header(fresh_settings):
    from clipasso_studio import __version__, logs
    from clipasso_studio.gui import crash, diagnostics

    (logs.logs_dir() / "app.log").write_text("".join(f"log line {i}\n" for i in range(80)), encoding="utf-8")
    text = diagnostics.report()
    for part in (f"Version: {__version__}", "[System]", "RAM:", "PyTorch 2.11.0+cu128 · CUDA build 12.8",
                 "GPU 0: NVIDIA GeForce RTX 4070 · 12.0 GB", "[Folders]", "Output:", "free)", "[Models]",
                 "log line 79"):
        assert part in text, part
    assert "log line 29" not in text  # only the last 50 lines
    head = crash._header()
    assert "torch 2.11.0+cu128" in head and "CUDA 12.8" in head and "RTX 4070 12 GB" in head
    assert f"{__version__} (dev)" in head
    log = crash.write_log("boom")
    assert log.read_text(encoding="utf-8").startswith(head.rsplit(" · ", 1)[0])


def test_hardware_not_probed_yet():
    from clipasso_studio.gui import diagnostics

    assert diagnostics.hardware_lines(None) == ["PyTorch: not checked yet"]
    assert diagnostics.hardware_lines({"error": "ImportError: no torch"}) == ["PyTorch: ImportError: no torch"]
    assert diagnostics.hardware_lines({"torch": "2.11.0+cpu", "cuda_build": "", "gpus": []})[-1] \
        == "GPU: none usable (CPU only)"


def test_settings_copy_and_save(qapp, fresh_settings, tmp_path):
    from PySide6.QtWidgets import QApplication

    from clipasso_studio.gui.i18n import tr
    from clipasso_studio.gui.pages.other_pages import SettingsPage

    page = SettingsPage()
    text = page.copy_diagnostics()
    assert QApplication.clipboard().text() == text and "[PyTorch]" in text
    assert page.diag_copy_btn.text() == tr("ui.diag.copied")
    out = tmp_path / "diag.txt"
    assert page.save_diagnostics(str(out)) == str(out)
    assert "[Models]" in out.read_text(encoding="utf-8")


def test_runner_shows_the_stacks_of_a_crashed_worker(user_data, tmp_path):
    import queue

    from clipasso_studio import logs
    from clipasso_studio.engine import runner

    class DeadWorker:
        pid, exitcode = 4242, -11

        def is_alive(self):
            return False

    logs.worker_log_path(4242).write_text("Fatal Python error: Segmentation fault\n  File \"painter.py\"\n")
    r = runner.JobRunner()
    r._queue = queue.Queue()
    r.job = runner.Job(settings={}, target="", output_root=str(tmp_path), job_dir=str(tmp_path / "job"),
                       workers=[DeadWorker()])
    events = r.poll()
    errors = [d for k, d in events if k == "error"]
    assert errors and "exit codes [-11]" in errors[0]["message"]
    assert "Segmentation fault" in errors[0]["traceback"] and "painter.py" in errors[0]["traceback"]
    assert ("job_failed", {"job_dir": str(tmp_path / "job")}) in events
