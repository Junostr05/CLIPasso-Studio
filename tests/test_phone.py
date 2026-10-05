"""The phone: the remote page in the home network (access code, cookie, header for changes, uploads) and the
Telegram messages (Bot API faked)."""

import io
import json
import time
import urllib.error
import urllib.request

import pytest

PNG = None


def _png() -> bytes:
    from PIL import Image

    buf = io.BytesIO()
    Image.new("RGB", (32, 32), "white").save(buf, "PNG")
    return buf.getvalue()


def _wait(qapp, cond, seconds=5.0):
    end = time.time() + seconds
    while time.time() < end:
        qapp.processEvents()
        if cond():
            return True
        time.sleep(0.02)
    return False


def test_home_network_only():
    from clipasso_studio.gui import remote

    for ip in ("192.168.1.20", "10.0.0.5", "172.16.3.4", "127.0.0.1", "::1", "fe80::1%eth0", "::ffff:192.168.0.2"):
        assert remote.allowed_client(ip), ip
    for ip in ("8.8.8.8", "2001:4860:4860::8888", "::ffff:8.8.8.8", "nonsense"):
        assert not remote.allowed_client(ip), ip


def test_access_code_url_and_qr(qapp, user_data):
    from clipasso_studio.gui import app_settings as settings_module
    from clipasso_studio.gui import remote

    settings_module._instance = None
    code = remote.token()
    assert len(code) >= 16 and remote.token() == code  # made once, then kept
    link = remote.url(9999, "192.168.1.5")
    assert link == f"http://192.168.1.5:9999/?t={code}"
    assert remote.qr_png(link).startswith(b"\x89PNG")
    settings_module._instance = None


@pytest.fixture
def server(qapp, tmp_path, user_data):
    from clipasso_studio.gui import app_settings as settings_module
    from clipasso_studio.gui import remote

    settings_module._instance = None
    bridge = remote.RemoteBridge()
    bridge.texts = {"pause": "Pause", "lang": "en"}
    srv = remote.RemoteServer(bridge, port=0, host="127.0.0.1", upload_dir=str(tmp_path / "up")).start()
    yield srv, bridge, f"http://127.0.0.1:{srv.port}", tmp_path / "up"
    srv.stop()
    settings_module._instance = None


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *args, **kwargs):
        return None


def _get(url, cookie=None):
    req = urllib.request.Request(url, headers={"Cookie": cookie} if cookie else {})
    opener = urllib.request.build_opener(_NoRedirect)
    try:
        with opener.open(req, timeout=5) as r:
            return r.status, dict(r.headers), r.read()
    except urllib.error.HTTPError as e:
        return e.code, dict(e.headers), e.read()


def _post(url, body=b"", headers=None):
    req = urllib.request.Request(url, data=body, headers=headers or {}, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=5) as r:
            return r.status, json.loads(r.read())
    except urllib.error.HTTPError as e:
        return e.code, json.loads(e.read() or b"{}")


def test_remote_page_needs_the_code(server):
    from clipasso_studio.gui import remote

    _srv, bridge, base, _up = server
    code = remote.token()
    assert _get(base + "/")[0] == 403
    assert _get(base + "/?t=wrong")[0] == 403
    assert _get(base + "/api/status")[0] == 403
    status, headers, _ = _get(base + f"/?t={code}")
    assert status == 303 and headers["Location"] == "/"
    cookie = headers["Set-Cookie"].split(";")[0]
    assert "HttpOnly" in headers["Set-Cookie"] and "SameSite=Strict" in headers["Set-Cookie"]
    status, _, body = _get(base + "/", cookie)
    assert status == 200 and b"CLIPasso Studio" in body and code.encode() in body
    bridge.set_state(busy=True, job={"name": "camel.png", "progress": 0.5})
    bridge.preview_svg = '<svg xmlns="http://www.w3.org/2000/svg"/>'
    status, _, body = _get(base + "/api/status", cookie)
    data = json.loads(body)
    assert status == 200 and data["busy"] and data["job"]["name"] == "camel.png" and data["preview"]
    status, headers, body = _get(base + "/api/preview.svg", cookie)
    assert status == 200 and headers["Content-Type"] == "image/svg+xml" and body.startswith(b"<svg")


def test_remote_changes_need_the_header(server, qapp):
    from clipasso_studio.gui import remote

    _srv, bridge, base, up = server
    code = remote.token()
    calls = []
    bridge.pause.connect(lambda: calls.append("pause"))
    bridge.upload.connect(lambda path, method: calls.append((path, method)))
    assert _post(base + "/api/pause")[0] == 403  # a page elsewhere cannot send this (no header)
    assert _post(base + "/api/pause", headers={"X-Access": "wrong"})[0] == 403
    assert _post(base + "/api/pause", headers={"X-Access": code}) == (200, {"ok": True})
    assert _wait(qapp, lambda: "pause" in calls)
    status, data = _post(base + "/api/upload", _png(), {"X-Access": code, "X-Filename": "my%20dog.png",
                                                       "X-Method": "swiftsketch"})
    assert status == 200 and data["ok"]
    assert _wait(qapp, lambda: any(isinstance(c, tuple) for c in calls))
    path, method = next(c for c in calls if isinstance(c, tuple))
    assert method == "swiftsketch" and path.startswith(str(up)) and path.endswith("my dog.png")
    status, data = _post(base + "/api/upload", b"not a picture", {"X-Access": code, "X-Filename": "x.png"})
    assert status == 415 and not data["ok"] and len(list(up.iterdir())) == 1
    status, data = _post(base + "/api/upload", b"", {"X-Access": code})
    assert status == 413
    req = urllib.request.Request(base + "/api/upload", data=b"x", method="POST",
                                 headers={"X-Access": code, "Content-Length": str(remote.MAX_UPLOAD + 1)})
    try:
        urllib.request.urlopen(req, timeout=5)
        code_seen = 200
    except urllib.error.HTTPError as e:
        code_seen = e.code
    except (urllib.error.URLError, ConnectionError):
        code_seen = 413  # (the server answers before the body is sent and closes)
    assert code_seen == 413


class _FakeTelegram:
    """Answers the Bot API calls urlopen gets."""

    def __init__(self):
        self.calls = []
        self.updates = [{"update_id": 7, "message": {"text": "hello", "chat": {"id": 1}}},
                        {"update_id": 8, "message": {"text": "/start", "chat": {"id": 4242, "first_name": "Juno"}}}]

    def __call__(self, req, timeout=None):
        method = req.full_url.rsplit("/", 1)[1]
        self.calls.append((method, req.data, req.headers))
        result = {"getMe": {"username": "sketch_bot"}, "getUpdates": self.updates,
                  "sendMessage": {"message_id": 1}, "sendPhoto": {"message_id": 2}}.get(method)
        if method == "boom":
            raise urllib.error.URLError("no network")
        body = json.dumps({"ok": result is not None, "result": result, "description": "Not Found"}).encode()
        return io.BytesIO(body)


TOKEN = "123456789:" + "A" * 35


def test_telegram_calls(monkeypatch):
    from clipasso_studio.gui import telegram

    fake = _FakeTelegram()
    monkeypatch.setattr(telegram.urllib.request, "urlopen", fake)
    assert telegram.valid_token(TOKEN) and not telegram.valid_token("123:abc") and not telegram.valid_token("")
    with pytest.raises(telegram.TelegramError):
        telegram.call("bad", "getMe")
    assert telegram.bot_name(TOKEN) == "sketch_bot"
    assert telegram.find_chat(TOKEN, seconds=5) == ("4242", "Juno")
    telegram.send(TOKEN, "4242", "done", b"\x89PNG data")
    method, data, headers = fake.calls[-1]
    assert method == "sendPhoto" and b'name="chat_id"' in data and b"\x89PNG data" in data
    assert headers["Content-type"].startswith("multipart/form-data")
    with pytest.raises(telegram.TelegramError) as err:
        telegram.call(TOKEN, "boom")
    assert TOKEN not in str(err.value)  # never the token in an error text
    with pytest.raises(telegram.TelegramError):
        telegram.call(TOKEN, "unknownMethod")


def test_telegram_message_for_a_job(qapp, user_data, monkeypatch, tmp_path):
    from types import SimpleNamespace

    from clipasso_studio.gui import app_settings as settings_module
    from clipasso_studio.gui import telegram
    from clipasso_studio.gui.app_settings import app_settings

    settings_module._instance = None
    fake = _FakeTelegram()
    monkeypatch.setattr(telegram.urllib.request, "urlopen", fake)
    svg = tmp_path / "best.svg"
    svg.write_text('<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 10 10">'
                   '<path d="M 1 1 L 9 9" stroke="#000" fill="none"/></svg>')
    job = SimpleNamespace(name="camel.png", status="done", message="", started=100.0, finished=190.0,
                          best_svg=str(svg), settings={"method": "swiftsketch"})
    notifier = telegram.Notifier()
    assert not notifier.job_finished(job)  # not set up
    app_settings().data.update(telegram_on=True, telegram_token=TOKEN, telegram_chat="4242")
    assert telegram.configured()
    sent = []
    notifier.sent.connect(lambda ok, err: sent.append((ok, err)))
    assert notifier.job_finished(job, {"clip_score": 81.234})
    assert _wait(qapp, lambda: sent)
    method, data, _ = fake.calls[-1]
    assert sent == [(True, "")] and method == "sendPhoto" and b"camel.png" in data and b"81.2" in data
    assert b"1:30" in data  # how long it took
    failed = SimpleNamespace(**{**vars(job), "status": "failed", "message": "out of memory"})
    app_settings().data["telegram_failed"] = False
    assert not notifier.job_finished(failed)
    app_settings().data["telegram_failed"] = True
    assert notifier.job_finished(failed)
    assert _wait(qapp, lambda: len(sent) == 2)
    assert fake.calls[-1][0] == "sendMessage" and b"out+of+memory" in fake.calls[-1][1]
    notifier.stop()
    settings_module._instance = None


def test_phone_link(qapp, user_data, tmp_path, monkeypatch):
    from types import SimpleNamespace

    from PySide6.QtCore import QObject, Signal

    from clipasso_studio.gui import app_settings as settings_module
    from clipasso_studio.gui.app_settings import app_settings
    from clipasso_studio.gui.phone import PhoneLink

    settings_module._instance = None

    class Controller(QObject):
        queue_changed = Signal()
        job_started = Signal(object)
        job_event = Signal(object, str, dict)
        job_finished = Signal(object)

        def __init__(self):
            super().__init__()
            self.jobs, self.current, self.queued = [], None, []
            self.paused = False

        def is_busy(self):
            return self.current is not None

        def pause(self):
            self.paused = True

        def resume(self):
            self.paused = False

        def cancel(self):
            pass

        def enqueue(self, target, settings, start=True):
            self.queued.append((target, settings, start))

    c = Controller()
    link = PhoneLink(c, lambda: {"method": "clipasso", "num_strokes": 12})
    assert not link.running()  # off by default
    job = SimpleNamespace(name="a.png", status="running", settings={"method": "clipasso"}, progress=0.25,
                          eta=75.0, job_dir="", best_svg="", started=0, finished=0, message="")
    c.current = job
    c.job_event.emit(job, "preview", {"svg": "<svg/>"})
    st = link.bridge.state
    assert st["busy"] and st["job"]["eta"] == "1:15" and link.bridge.preview_svg == "<svg/>"
    link.bridge.pause.emit()
    assert c.paused
    link.bridge.upload.emit(str(tmp_path / "p.jpg"), "clipasso")
    link.bridge.upload.emit(str(tmp_path / "q.jpg"), "swiftsketch")
    assert c.queued[0][1] == {"method": "clipasso", "num_strokes": 12}  # the studio's settings
    assert c.queued[1][1]["method"] == "swiftsketch" and c.queued[1][2]
    c.current = None
    job.status = "done"
    c.job_finished.emit(job)
    assert link.bridge.state["last"] == {"name": "a.png", "status": "done"} and not link.bridge.state["busy"]
    # switched on: the page is served
    import socket

    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        port = s.getsockname()[1]
    app_settings().data.update(remote_on=True, remote_port=port)
    assert link.apply_settings() == "" and link.running() and link.server.port == port
    app_settings().data["remote_on"] = False
    link.apply_settings()
    assert not link.running()
    link.shutdown()
    settings_module._instance = None


def test_phone_card(qapp, user_data):
    from clipasso_studio.gui import app_settings as settings_module
    from clipasso_studio.gui.app_settings import app_settings
    from clipasso_studio.gui.phone_ui import PhoneCard

    settings_module._instance = None
    card = PhoneCard()
    assert not card.remote_box.isVisibleTo(card) and not card.tg_box.isVisibleTo(card)
    card.tg_on.setChecked(True)
    assert app_settings().get("telegram_on") and card.tg_box.isVisibleTo(card)
    card.token.setText("not a token")
    card.connect_telegram()
    assert "Bot" in card.tg_status.text() or "bot" in card.tg_status.text()
    old = app_settings().get("remote_token")
    card.new_access_code()
    assert app_settings().get("remote_token") != old
    settings_module._instance = None


# ----------------------------------------------------------------------------- the studio from the phone
def _in_thread(qapp, fn, seconds=20.0):
    """Run a request in a thread while the event loop runs (the server asks the GUI thread and waits)."""
    import threading

    box = {}

    def run():
        try:
            box["value"] = fn()
        except Exception as exc:  # (handed to the test)
            box["error"] = exc

    th = threading.Thread(target=run)
    th.start()
    assert _wait(qapp, lambda: not th.is_alive(), seconds)
    if "error" in box:
        raise box["error"]
    return box["value"]


def _cookie(base):
    from clipasso_studio.gui import remote

    _status, headers, _ = _get(base + f"/?t={remote.token()}")
    return headers["Set-Cookie"].split(";")[0]


def test_page_and_its_files(server):
    from clipasso_studio.gui import remote

    _srv, bridge, base, _up = server
    cookie = _cookie(base)
    status, headers, body = _get(base + "/", cookie)
    assert status == 200 and "script-src 'self'" in headers["Content-Security-Policy"]
    assert b'id="cfg" type="application/json"' in body and remote.token().encode() in body
    assert b"<script>" not in body.replace(b'<script src="/phone.js"></script>', b"")  # nothing runs inline
    assert b'id="choose" type="file" accept="image/*" hidden' in body  # a file, not only the camera
    assert b'capture="environment"' in body  # (the camera has a button of its own)
    for name, kind in (("phone.js", "javascript"), ("phone.css", "css"), ("icon.png", "png")):
        assert _get(base + "/" + name)[0] == 403
        status, headers, data = _get(base + "/" + name, cookie)
        assert status == 200 and kind in headers["Content-Type"] and data


def test_page_texts_exist():
    """Every text the page uses has a translation (or comes from the app's other texts)."""
    import re

    from clipasso_studio import paths
    from clipasso_studio.gui.i18n import i18n

    html = paths.resource("phone", "index.html").read_text(encoding="utf-8")
    js = paths.resource("phone", "phone.js").read_text(encoding="utf-8")
    used = set(re.findall(r'data-t="([a-z_]+)"', html)) | set(re.findall(r"\bT\.([a-z_]+)", js)) \
        | set(re.findall(r'\bt\("([a-z_]+)"', js))
    extra = {"detail_title", "detail_hint", "tool_more", "tool_normal", "tool_less", "face", "rate_up", "rate_down"}
    page = {k[len("ui.phone.page."):] for k in i18n.keys("ui.phone.page.")}
    assert used - page - extra == set()
    for k in page:
        assert i18n._data["de"].get("ui.phone.page." + k) and i18n._data["en"].get("ui.phone.page." + k), k
    # the page's CSP allows no inline styles: widths and the like go through element.style
    assert not re.search(r"\bstyle:\s*[`'\"]", js) and "style=" not in html


def test_requests_go_to_the_app(server, qapp, monkeypatch):
    from clipasso_studio.gui import remote

    _srv, bridge, base, up = server
    code = remote.token()
    cookie = _cookie(base)
    calls = []

    def handler(action, data):
        calls.append((action, data))
        if action == "file_thing":
            return {"_bytes": b"<svg/>", "_type": "image/svg+xml", "_name": "my sketch.svg"}
        if action == "do_bad":
            return {"ok": False, "error": "no"}
        return {"ok": True, "action": action}

    bridge.handler = handler
    status, _, body = _in_thread(qapp, lambda: _get(base + "/api/get/studio?x=1", cookie))
    assert status == 200 and json.loads(body)["action"] == "get_studio" and calls[-1] == ("get_studio", {"x": "1"})
    status, headers, body = _in_thread(qapp, lambda: _get(base + "/api/file/thing?seed=3", cookie))
    assert status == 200 and body == b"<svg/>" and headers["Content-Type"] == "image/svg+xml"
    assert "attachment" in headers["Content-Disposition"] and "my%20sketch.svg" in headers["Content-Disposition"]
    assert _get(base + "/api/get/studio")[0] == 403  # (no cookie)
    head = {"X-Access": code, "Content-Type": "application/json"}
    status, data = _in_thread(qapp, lambda: _post(base + "/api/do", json.dumps({"action": "set", "key": "k",
                                                                                "value": 3}).encode(), head))
    assert status == 200 and calls[-1] == ("do_set", {"action": "set", "key": "k", "value": 3})
    assert _in_thread(qapp, lambda: _post(base + "/api/do", b'{"action": "bad"}', head))[0] == 400
    assert _post(base + "/api/do", b'{"action": "set"}', {"Content-Type": "application/json"})[0] == 403
    assert _in_thread(qapp, lambda: _post(base + "/api/do", b"not json", head))[0] == 400
    assert _in_thread(qapp, lambda: _post(base + "/api/do", b'{"action": "../x"}', head))[0] == 404
    # a picture for the studio (not the queue)
    status, data = _in_thread(qapp, lambda: _post(base + "/api/upload", _png(), {
        "X-Access": code, "X-Target": "studio", "X-Filename": "beach.png"}))
    assert status == 200 and calls[-1][0] == "set_image" and calls[-1][1]["path"].endswith("beach.png")
    # the painted detail map
    status, data = _in_thread(qapp, lambda: _post(base + "/api/details", _png(), {"X-Access": code}))
    assert status == 200 and calls[-1][0] == "set_details" and calls[-1][1]["png"].startswith(b"\x89PNG")
    assert _post(base + "/api/details", b"GIF89a", {"X-Access": code})[0] == 415
    # the app does not answer in time: "busy"
    monkeypatch.setattr(remote, "CALL_TIMEOUT", 0.3)
    status, _, body = _get(base + "/api/get/studio", cookie)  # (no events processed: no answer)
    assert status == 503 and json.loads(body)["error"] == "busy"


def test_tailscale(qapp, user_data, monkeypatch):
    """Phones of the user's tailnet (100.64.0.0/10) only when switched on; the QR code can show the tailnet address."""
    from types import SimpleNamespace

    from clipasso_studio.gui import app_settings as settings_module
    from clipasso_studio.gui import remote
    from clipasso_studio.gui.app_settings import app_settings
    from clipasso_studio.gui.phone_ui import PhoneCard

    for ip in ("100.101.102.103", "100.64.0.1", "100.127.255.254", "::ffff:100.100.1.1"):
        assert not remote.allowed_client(ip) and remote.allowed_client(ip, tailscale=True), ip
    for ip in ("100.128.0.1", "100.63.255.255", "8.8.8.8"):
        assert not remote.allowed_client(ip, tailscale=True), ip
    assert remote.allowed_client("fd7a:115c:a1e0::1")  # (the tailnet's IPv6 range counts as private anyway)
    # this computer's tailnet address (here from the host name: the container has no Tailscale interface)
    monkeypatch.setattr(remote.socket, "getaddrinfo", lambda *a, **k: [(2, 1, 6, "", ("100.88.1.2", 0)),
                                                                     (2, 1, 6, "", ("192.168.1.5", 0))])
    assert remote.tailscale_address() == "100.88.1.2"
    # the card: the switch where Tailscale runs, then a QR code of the tailnet address
    settings_module._instance = None
    app_settings().data.update(remote_on=True)
    card = PhoneCard()
    card.set_link(SimpleNamespace(running=lambda: True, server=SimpleNamespace(port=8765), error="",
                                  apply_settings=lambda: ""))
    assert card.ts_box.isVisibleTo(card) and not card.net.isVisibleTo(card) and "100.88" not in card.url.text()
    card.ts_on.setChecked(True)
    assert app_settings().get("remote_tailscale") and card.net.isVisibleTo(card)
    assert "http://100.88.1.2:8765/?t=" in card.url.text() and card.ts_hint.isVisibleTo(card)
    card.net.set_current("lan")
    card.refresh()
    assert "100.88.1.2" not in card.url.text()
    monkeypatch.setattr(remote, "tailscale_address", lambda: "")  # Tailscale stopped: a hint, the home address
    card.refresh()
    assert not card.net.isVisibleTo(card) and card.ts_hint.text() and "100.88" not in card.url.text()
    settings_module._instance = None
