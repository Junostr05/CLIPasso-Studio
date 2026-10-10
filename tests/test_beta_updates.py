"""4.0: beta versions – "Also offer beta versions" (PC and phone, Windows only), the newest of all releases,
and the small update of a beta from the beta before it."""

import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest

RELEASES = [
    {"tag_name": "v4.0.0b2", "prerelease": True, "html_url": "https://example.invalid/b2"},
    {"tag_name": "v9.9.9", "draft": True},
    {"tag_name": "v3.8.1", "prerelease": False},
    {"tag_name": "v4.0.0b1", "prerelease": True},
]


class _Api(BaseHTTPRequestHandler):
    releases: list = []

    def do_GET(self):  # noqa: N802 - /releases: all of them, /releases/latest: the latest final one
        if self.path.endswith("/latest"):
            final = [r for r in _Api.releases if not r.get("draft") and not r.get("prerelease")]
            body = json.dumps(final[0] if final else {}).encode()
        else:
            body = json.dumps(_Api.releases).encode()
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
    _Api.releases = list(RELEASES)
    yield f"http://127.0.0.1:{httpd.server_address[1]}"
    httpd.shutdown()


@pytest.fixture
def settings(user_data):
    from clipasso_studio.gui import app_settings as settings_module

    settings_module._instance = None
    yield
    settings_module._instance = None


def test_the_beta_channel_finds_the_newest_beta(api):
    """4.0: with betas the newest of all releases (no drafts); without, betas are not offered."""
    from clipasso_studio.gui import updates

    found = json.loads(updates.check(url=f"{api}/releases", current="4.0.0b1", betas=True))
    assert found["tag"] == "v4.0.0b2" and found["prerelease"] and found["url"] == "https://example.invalid/b2"
    assert updates.check(url=f"{api}/releases/latest", current="4.0.0b1", betas=False) == ""
    assert json.loads(updates.check(url=f"{api}/releases/latest", current="3.8.0", betas=False))["tag"] == "v3.8.1"
    _Api.releases = [{"tag_name": "v4.0.0", "prerelease": False}] + RELEASES  # the final one ranks above its betas
    assert json.loads(updates.check(url=f"{api}/releases", current="4.0.0b2", betas=True))["tag"] == "v4.0.0"
    assert updates.check(url=f"{api}/releases", current="4.0.0", betas=True) == ""
    result = json.loads(updates.check_now(url=f"{api}/releases", current="3.8.1", betas=True))
    assert result["status"] == "newer" and result["release"]["tag"] == "v4.0.0"


def test_betas_only_on_windows(settings, monkeypatch):
    """4.0: betas are built for Windows only – elsewhere the setting offers nothing."""
    from clipasso_studio.gui import updates
    from clipasso_studio.gui.app_settings import app_settings

    assert app_settings().get("beta_updates") is False
    app_settings().data["beta_updates"] = True
    monkeypatch.setattr(updates.sys, "platform", "linux")
    assert not updates.beta_allowed() and not updates.beta_channel()
    assert updates._channel(None, None) == (updates.RELEASES_API, False)
    monkeypatch.setattr(updates.sys, "platform", "win32")
    assert updates.beta_channel() and updates._channel(None, None) == (updates.RELEASES_LIST, True)
    app_settings().data["beta_updates"] = False
    assert not updates.beta_channel()


@pytest.mark.parametrize("platform", ["win32", "linux"])
def test_the_switch_on_the_pc_and_on_the_phone(qapp, settings, monkeypatch, platform):
    """4.0: "Also offer beta versions" in the settings and on the phone's App page – on Windows only."""
    from clipasso_studio.gui import updates
    from clipasso_studio.gui.app_settings import app_settings
    from clipasso_studio.gui.i18n import tr
    from clipasso_studio.gui.pages.other_pages import SettingsPage
    from clipasso_studio.gui.phone_api import PhoneApi, PhoneError

    monkeypatch.setattr(updates.sys, "platform", platform)
    page = SettingsPage()
    api = PhoneApi(controller=None)
    api.settings_page = page
    keys = [s["key"] for s in api.get_app_settings({})["settings"]]
    if platform != "win32":
        assert page.beta_row.isHidden() and "beta_updates" not in keys
        with pytest.raises(PhoneError):
            api.do_app_setting({"key": "beta_updates", "value": True})
        return
    assert not page.beta_row.isHidden() and page.beta_switch_label.text() == tr("ui.settings.beta_updates")
    entry = next(s for s in api.get_app_settings({})["settings"] if s["key"] == "beta_updates")
    assert entry == {"key": "beta_updates", "label": tr("ui.settings.beta_updates"), "kind": "bool", "value": False}
    api.do_app_setting({"key": "beta_updates", "value": True})  # from the phone: through the PC's switch
    assert page.beta_switch.isChecked() and app_settings().get("beta_updates") is True
    assert updates.beta_channel()
    page.beta_switch.setChecked(False)
    assert app_settings().get("beta_updates") is False


def test_a_beta_is_patched_from_the_beta_before(monkeypatch):
    """4.0: the small update of a beta starts from the newest release of any kind (who has betas has the
    one before); a final release from the final one before (who has no betas)."""
    import importlib.util
    import io
    from pathlib import Path

    spec = importlib.util.spec_from_file_location("manifest_tool", Path(__file__).resolve().parents[1] / "tools"
                                                  / "manifest.py")
    manifest = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(manifest)

    listing = [{"tag_name": t, "prerelease": pre, "assets": [
        {"name": "CLIPassoStudio-CPU-manifest.json", "browser_download_url": f"https://x.invalid/{t}"}]}
        for t, pre in (("v4.0.0b2", True), ("v4.0.0b1", True), ("v3.8.1", False), ("v3.8.0", False))]
    fetched = []

    class _Resp(io.BytesIO):
        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

    def urlopen(req, timeout=0):
        url = req.full_url
        if url.endswith("per_page=30"):
            return _Resp(json.dumps(listing).encode())
        fetched.append(url.rsplit("/", 1)[1])
        return _Resp(json.dumps({"version": fetched[-1]}).encode())

    monkeypatch.setattr(manifest.urllib.request, "urlopen", urlopen)
    assert manifest.is_beta("v4.0.0b3") and manifest.is_beta("v2.1.0-beta.1") and not manifest.is_beta("v4.0.0")
    assert manifest.previous_manifest("o/r", "cpu", "v4.0.0b3") == {"version": "v4.0.0b2"}
    assert manifest.previous_manifest("o/r", "cpu", "v4.0.0b1") == {"version": "v3.8.1"}
    assert manifest.previous_manifest("o/r", "cpu", "v4.0.0") == {"version": "v3.8.1"}
