"""What's new: the notes of a new release (update bar), of this version at the first start after an update
(shipped with the app), and "Check for updates now" that tells "up to date" from "offline"."""

import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest


class _Api(BaseHTTPRequestHandler):
    release: dict = {}

    def do_GET(self):  # noqa: N802
        body = json.dumps(_Api.release).encode()
        self.send_response(200)
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


def test_check_now(api):
    from clipasso_studio.gui import updates

    _Api.release = {"tag_name": "v9.0.0", "body": "## New\n- **everything**", "prerelease": False}
    result = json.loads(updates.check_now(url=api, current="3.0.0"))
    assert result["status"] == "newer" and result["release"]["body"].startswith("## New")
    assert json.loads(updates.check_now(url=api, current="9.0.0")) == {"status": "current"}
    result = json.loads(updates.check_now(url="http://127.0.0.1:9/none", current="3.0.0"))
    assert result["status"] == "error" and result["error"]


def test_notes_of_this_version():
    from clipasso_studio.gui import updates

    de, en = updates.whats_new_text("de"), updates.whats_new_text("en")
    assert de.startswith("## ") and en.startswith("## ") and de != en
    assert de.count("\n## ") == en.count("\n## ")  # the same sections
    assert updates.whats_new_text("xx") == en
    assert updates.updated_since("2.4.0", "3.0.0") and not updates.updated_since("3.0.0", "3.0.0")
    assert not updates.updated_since("", "3.0.0")  # the very first start: the guide instead


@pytest.fixture
def window(tmp_path, monkeypatch, qapp):
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path))
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path))
    from clipasso_studio.gui import app_settings as settings_module
    from clipasso_studio.gui.app_settings import app_settings

    settings_module._instance = None
    app_settings().data["output_dir"] = str(tmp_path / "out")
    made = []

    def make(**settings):
        from clipasso_studio.gui.main_window import MainWindow

        app_settings().data.update(settings)
        w = MainWindow()
        w.controller.start_next = lambda: None
        made.append(w)
        return w

    yield make
    for w in made:
        w.studio.shutdown()
        w.controller.shutdown()
        w.close()
    settings_module._instance = None


def test_first_start_after_an_update(window, monkeypatch):
    from clipasso_studio.gui import main_window
    from clipasso_studio.gui.app_settings import app_settings

    monkeypatch.setattr(main_window, "__version__", "3.0.0")
    w = window(tour_done=True)  # settings of 2.4 (no "last_version" yet)
    assert w.maybe_show_whats_new()
    assert app_settings().get("last_version") == "3.0.0"
    assert window(last_version="2.4.0", tour_done=True).maybe_show_whats_new()


def test_not_at_the_very_first_start_nor_again(window):
    from clipasso_studio import __version__

    assert not window(tour_done=False).maybe_show_whats_new()  # the guide is shown instead
    assert not window(last_version=__version__, tour_done=True).maybe_show_whats_new()


def test_update_bar_shows_the_release_notes(window):
    from clipasso_studio.gui import dialogs

    w = window()
    w.update_bar.show_release({"tag": "v9.0.0", "body": "## Big\n- **news**", "assets": []})
    assert w.update_bar.notes.isVisibleTo(w.update_bar)
    dlg = w.update_bar.show_notes()
    assert isinstance(dlg, dialogs.WhatsNewDialog) and "news" in dlg.browser.toPlainText()
    assert "**" not in dlg.browser.toPlainText()  # rendered as Markdown
    dlg.close()
    w.update_bar.show_release({"tag": "v9.0.1", "body": "", "assets": []})
    assert not w.update_bar.notes.isVisibleTo(w.update_bar)


def test_check_updates_now_says_the_result(window, monkeypatch):
    from clipasso_studio.gui import dialogs

    w = window()
    shown = []
    monkeypatch.setattr(w.toast, "show_message", lambda text, kind="info": shown.append(kind))
    for answer in ('{"status": "current"}', '{"status": "error"}',
                   json.dumps({"status": "newer", "release": {"tag": "v9.0.0", "body": "", "assets": []}})):
        monkeypatch.setattr(dialogs, "run_in_thread", lambda parent, fn, on_done=None, on_error=None, a=answer:
                            on_done(a))
        w.check_updates_now()
        assert w.settings.check_now_btn.isEnabled()
    assert shown == ["success", "warning", "success"] and w.update_bar.release["tag"] == "v9.0.0"
