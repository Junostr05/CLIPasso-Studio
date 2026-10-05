"""Settings → System: the self-test button (a stand-in process writes the log and the result like the real
``--selftest``) and "Report a problem" (prepared GitHub issue: shortened paths, address length)."""

import json
import sys
import time
import urllib.parse
from pathlib import Path

import pytest


@pytest.fixture
def own_settings(qapp, user_data):
    from clipasso_studio.gui import app_settings as settings_module

    settings_module._instance = None
    yield
    settings_module._instance = None


FAKE_SELFTEST = r"""
import json, sys, time, os
out = sys.argv[-1]
os.makedirs(out, exist_ok=True)
log = open(os.path.join(out, "selftest.log"), "a", encoding="utf-8")
for line in ["selftest: models in x", "selftest: seed 0 iter 3/5 loss 0.3", 'selftest: clipasso {"ok": true}']:
    log.write(line + "\n"); log.flush(); time.sleep(0.2)
report = {"ok": %s, "seconds": 1.5, "clipasso": {"ok": True}, "swiftsketch": {"ok": True, "clip_score": 67.1},
          "mask": {"ok": %s}}
json.dump(report, open(os.path.join(out, "selftest.json"), "w"))
"""


def _wait(dlg, seconds=20):
    from PySide6.QtWidgets import QApplication

    end = time.time() + seconds
    while dlg.result is None and time.time() < end:
        QApplication.processEvents()
        time.sleep(0.05)


@pytest.mark.parametrize("ok", [True, False])
def test_selftest_dialog(own_settings, monkeypatch, tmp_path, ok):
    from clipasso_studio.gui import selftest_ui

    flag = "True" if ok else "False"
    monkeypatch.setattr(selftest_ui, "selftest_command",
                        lambda out: (sys.executable, ["-c", FAKE_SELFTEST % (flag, flag), out]))
    dlg = selftest_ui.SelftestDialog(None, out_dir=str(tmp_path / "st"))
    dlg.start()
    _wait(dlg)
    assert dlg.result is not None and dlg.result["ok"] is ok
    text = dlg.results.toPlainText()
    assert "✓  CLIPasso" in text and "CLIP 67.1" in text
    assert ("✓" if ok else "✗") + "  " in text.splitlines()[-1]
    dlg.reject()


def test_selftest_helpers(own_settings):
    from clipasso_studio.gui import selftest_ui

    assert selftest_ui.status_line("selftest: seed 0 iter 3/5 loss 0.3") == "CLIPasso: 3/5"
    assert selftest_ui.status_line('selftest: clipasso {"ok": true}') == "CLIPasso"
    assert selftest_ui.status_line("selftest: {\"ok\": true}") is None and selftest_ui.status_line("") is None
    program, args = selftest_ui.selftest_command("/x")
    assert program == sys.executable and args[-2:] == ["--selftest", "/x"]
    assert "✗  exit code 3" in selftest_ui.summary_text({"ok": False, "error": "exit code 3"})


def test_selftest_waits_for_a_running_job(own_settings, monkeypatch):
    from PySide6.QtWidgets import QMessageBox, QWidget

    from clipasso_studio.gui import selftest_ui

    shown = []
    monkeypatch.setattr(QMessageBox, "information", lambda *a, **k: shown.append(a))
    host = QWidget()
    host.controller = type("C", (), {"is_busy": lambda self: True, "release_worker": lambda self: None})()
    assert selftest_ui.run(host) is None and shown


def test_report_text_and_address(own_settings, monkeypatch):
    from clipasso_studio import __version__
    from clipasso_studio.gui import report

    home = str(Path.home())
    body = report.issue_body("RuntimeError: boom", f"File \"{home}/x.py\", line 1", diagnostics=f"Data: {home}/data")
    assert home not in body and "~/x.py" in body and "~/data" in body
    assert "```" in body and "Traceback" in body and "Diagnostics" in body
    assert report.issue_title("RuntimeError: boom\nmore") == f"[{__version__}] RuntimeError: boom"

    url, cut = report.issue_url("t", "short")
    assert not cut and url.startswith(report.NEW_ISSUE) and "body=short" in url
    long_body = "x" * 20000
    url, cut = report.issue_url("t", long_body)
    assert cut and len(url) <= report.MAX_URL
    assert "the full text is in the clipboard" in urllib.parse.parse_qs(urllib.parse.urlparse(url).query)["body"][0]


def test_report_dialog_opens_the_issue(own_settings, monkeypatch):
    from PySide6.QtGui import QDesktopServices
    from PySide6.QtWidgets import QApplication

    from clipasso_studio.gui import report

    opened = []
    monkeypatch.setattr(QDesktopServices, "openUrl", lambda url: opened.append(url.toString()) or True)
    dlg = report.ReportDialog(None, "ValueError: x", "Traceback …", diagnostics="diag")
    url = dlg.send()
    assert len(opened) == 1 and opened[0].startswith(report.NEW_ISSUE)
    assert "ValueError" in urllib.parse.unquote_plus(url)
    assert "diag" in QApplication.clipboard().text()
    assert json.dumps(dlg.copy())  # title + text
