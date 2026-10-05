"""3.4.2: the exports with their options as data (for the phone), own presets, and the fixed address with a PIN."""

import json
import urllib.request

import pytest

from tests.test_phone import _get, _post, server  # noqa: F401  (the fixture)

SKETCH = {"process_frames": 0, "draw_length": 3.0, "process_length": 4.0, "photo_frame": False}


@pytest.fixture
def fresh_settings(user_data):
    from clipasso_studio.gui import app_settings as settings_module

    settings_module._instance = None
    yield
    settings_module._instance = None


def test_export_options_are_checked(fresh_settings):
    from clipasso_studio.gui import dialogs, export_jobs

    o = export_jobs.check("gif", {"stroke": "red", "width": 99, "style": "evil", "background": "transparent",
                                  "paper": "x", "vignette": -5, "frame": "photo", "margin": 80, "size": 10 ** 6,
                                  "length": "abc", "hold": 50, "mode": "process"}, SKETCH)
    assert o["stroke"] == "#000000" and o["width"] == 10.0 and o["style"] == "plain"
    assert o["background"] == "#FFFFFF"  # (a GIF has no transparency)
    assert o["paper"] == "none" and o["vignette"] == 0 and o["frame"] == "square" and o["margin"] == 50
    assert o["size"] == export_jobs.MAX_SIZE and o["length"] == 3.0 and o["hold"] == 10.0
    assert o["mode"] == "strokes"  # no saved steps: stroke by stroke
    png = export_jobs.check("png", {"background": "transparent", "stroke": "#12ab34", "size": "300"}, SKETCH)
    assert png["background"] == "transparent" and png["stroke"] == "#12ab34" and png["size"] == 300
    assert export_jobs.check("png", None, SKETCH) == export_jobs.defaults("png", SKETCH)
    with pytest.raises(ValueError):
        export_jobs.check("exe", {}, SKETCH)
    # the drawing process is an animation only with two saved steps or more (one step is a still picture)
    many = {**SKETCH, "process_frames": 5}
    assert export_jobs.applies("mp4", 5)["mode"] and not export_jobs.applies("mp4", 1)["mode"]
    assert not export_jobs.applies("lottie", 5)["mode"] and export_jobs.applies("lottie", 5)["length"]
    assert export_jobs.check("mp4", {"mode": "process"}, many)["mode"] == "process"
    assert export_jobs.defaults("mp4", {**SKETCH, "process_frames": 1})["mode"] == "strokes"
    # what applies to which format (like the dialog)
    a = export_jobs.applies("svg1")
    assert not a["style"] and not a["background"] and not a["paper"] and not a["size"]
    assert export_jobs.applies("pdf")["width_cm"] and not export_jobs.applies("matrix")["frame"]
    # the choices are remembered, shared with the dialog of the studio
    export_jobs.remember("png", png)
    assert export_jobs.defaults("png", SKETCH)["background"] == "transparent"
    assert export_jobs.defaults("gif", SKETCH)["background"] == "#FFFFFF"
    assert export_jobs.defaults("png", SKETCH)["stroke"] == "#12ab34"
    # the same formats as the dialog
    assert export_jobs.EXTENSIONS == dialogs.EXTENSIONS
    assert export_jobs.ANIMATIONS == dialogs.ANIMATIONS and export_jobs.DRAWN == dialogs.DRAWN
    assert all(export_jobs.title(f) for f in export_jobs.FORMATS)


def test_export_runs_and_cancels(fresh_settings, tmp_path):
    from PIL import Image

    from clipasso_studio.gui import export_jobs

    svg = tmp_path / "s.svg"
    svg.write_text('<svg xmlns="http://www.w3.org/2000/svg" width="224" height="224">'
                   '<path d="M 10 10 C 60 60 120 20 200 200" stroke="rgb(0,0,0)" stroke-width="2" fill="none"/>'
                   '<path d="M 20 200 L 200 20" stroke="rgb(0,0,0)" stroke-width="2" fill="none"/></svg>')
    png = tmp_path / "out.png"
    o = export_jobs.check("png", {"background": "transparent", "size": 96}, SKETCH)
    export_jobs.run("png", str(svg), str(tmp_path), str(png), o)
    im = Image.open(png)
    assert im.mode == "RGBA" and im.size == (96, 96) and im.getpixel((0, 0))[3] == 0
    gif = tmp_path / "out.gif"
    seen = []
    o = export_jobs.check("gif", {"size": 64, "length": 0.5, "hold": 0}, SKETCH)
    export_jobs.run("gif", str(svg), str(tmp_path), str(gif), o, progress=lambda a, b: seen.append((a, b)))
    assert Image.open(gif).n_frames > 1 and seen
    # cancelled: no half file is left
    cut = tmp_path / "cut.gif"
    with pytest.raises(InterruptedError):
        export_jobs.run("gif", str(svg), str(tmp_path), str(cut), o, cancel=lambda: True)
    assert not cut.exists()


def test_own_presets_store(fresh_settings):
    from clipasso_studio import settings_schema as schema
    from clipasso_studio.gui import user_presets
    from clipasso_studio.gui.app_settings import app_settings

    s = schema.default_settings("clipasso")
    s.update(num_iter=123, path_svg="C:/Users/me/start.svg")
    entry = user_presets.save("  Fein   & schnell ", s)
    assert entry["name"] == "Fein & schnell" and entry["method"] == "clipasso"
    assert entry["settings"]["path_svg"] == "none"  # (a file of this computer is not part of a preset)
    assert user_presets.matching(s) == "Fein & schnell"  # (whatever the file)
    assert user_presets.matching({**s, "num_iter": 124}) == ""
    swift = schema.default_settings("swiftsketch")
    user_presets.save("Fein & schnell", swift)  # same name, other method: a preset of its own
    user_presets.save("Fein & schnell", {**s, "num_iter": 200})  # same name and method: replaced in its place
    presets = user_presets.all_presets()
    assert [(p["name"], p["method"]) for p in presets] == [("Fein & schnell", "clipasso"),
                                                           ("Fein & schnell", "swiftsketch")]
    assert presets[0]["settings"]["num_iter"] == 200
    assert [p["method"] for p in user_presets.for_method("swiftsketch")] == ["swiftsketch"]
    assert user_presets.find("Fein & schnell", "clipasso")["settings"]["num_iter"] == 200
    assert user_presets.find("Fein & schnell", "scenesketch") is None
    with pytest.raises(ValueError):
        user_presets.save("   ", s)
    assert len(user_presets.save("x" * 100, s)["name"]) == user_presets.MAX_NAME
    # broken entries in the settings file are skipped
    app_settings().data["user_presets"].append({"name": "bad", "method": "nope", "settings": {}})
    app_settings().data["user_presets"].append("nonsense")
    assert len(user_presets.all_presets()) == 3
    assert user_presets.delete("Fein & schnell", "swiftsketch")
    assert not user_presets.delete("Fein & schnell", "swiftsketch")
    assert [p["method"] for p in user_presets.all_presets()] == ["clipasso", "clipasso"]


# ----------------------------------------------------------------------------- the fixed address and the PIN
def test_pin(fresh_settings):
    from clipasso_studio.gui import remote
    from clipasso_studio.gui.app_settings import app_settings

    p = remote.pin()
    assert remote.valid_pin(p) and remote.pin() == p and app_settings().get("remote_pin") == p  # made once, kept
    assert all(remote.valid_pin(remote.new_pin()) for _ in range(50))
    for bad in ("12345", "1234567", "12a456", "", None, 123456):
        assert not remote.valid_pin(bad)
    app_settings().data["remote_pin"] = "broken"
    assert remote.valid_pin(remote.pin()) and remote.pin() != "broken"


def test_pin_guard_brakes_guessing(fresh_settings):
    from clipasso_studio.gui import remote

    right = remote.pin()
    wrong = "000000" if right != "000000" else "111111"
    g = remote._PinGuard()
    t = 1000.0
    for _ in range(remote.PIN_TRIES - 1):
        assert g.check("10.0.0.2", wrong, t) == (False, 0)
    ok, wait = g.check("10.0.0.2", wrong, t)
    assert not ok and wait == remote.PIN_WAIT
    assert g.check("10.0.0.2", right, t + 1) == (False, remote.PIN_WAIT - 1)  # waiting: not even the right PIN
    assert g.check("10.0.0.3", right, t + 1) == (True, 0)  # another phone is not held up
    for _ in range(remote.PIN_TRIES):
        g.check("10.0.0.2", wrong, t + remote.PIN_WAIT)
    assert g.wait("10.0.0.2", t + remote.PIN_WAIT) == 2 * remote.PIN_WAIT  # every round twice as long
    assert g.check("10.0.0.2", right, t + 10 * remote.PIN_WAIT) == (True, 0)
    # many wrong PINs from many addresses: nobody can try for a while
    g = remote._PinGuard()
    for i in range(remote.PIN_GLOBAL):
        g.check(f"192.168.0.{i + 10}", wrong, t)
    assert g.check("192.168.0.200", right, t + 1)[0] is False
    assert g.check("192.168.0.200", right, t + remote.PIN_WINDOW + 1) == (True, 0)


def test_sign_in_with_the_pin(server, monkeypatch):  # noqa: F811
    from clipasso_studio.gui import remote

    _srv, bridge, base, _up = server
    bridge.texts = {"login_hint": "Enter the PIN", "lang": "en"}
    monkeypatch.setattr(remote, "pin_guard", remote._PinGuard())
    code, pin = remote.token(), remote.pin()
    # the fixed address without a sign-in: the PIN page (nothing secret in it), its script and style
    status, headers, body = _get(base + "/")
    assert status == 200 and b"login.js" in body and b"Enter the PIN" in body and code.encode() not in body
    assert "script-src 'self'" in headers["Content-Security-Policy"] and "Set-Cookie" not in headers
    for name in ("login.js", "phone.css", "icon.png", "manifest.webmanifest"):
        assert _get(base + "/" + name)[0] == 200, name
    assert json.loads(_get(base + "/manifest.webmanifest")[2])["start_url"] == "/"
    assert _get(base + "/phone.js")[0] == 403 and _get(base + "/api/get/studio")[0] == 403
    # a wrong PIN, then the right one: the same cookie as from the QR code, kept for long
    wrong = "000000" if pin != "000000" else "111111"
    assert _post(base + "/login", json.dumps({"pin": wrong}).encode()) == (403, {"ok": False, "wait": 0})
    assert _post(base + "/login", b"not json")[0] == 403
    req = urllib.request.Request(base + "/login", data=json.dumps({"pin": pin}).encode(), method="POST")
    with urllib.request.urlopen(req, timeout=5) as r:
        assert r.status == 200 and json.loads(r.read())["ok"]
        set_cookie = r.headers["Set-Cookie"]
    assert f"Max-Age={remote.COOKIE_AGE}" in set_cookie and "HttpOnly" in set_cookie
    cookie = set_cookie.split(";")[0]
    status, headers, body = _get(base + "/", cookie)
    assert status == 200 and code.encode() in body and "Set-Cookie" in headers  # (renewed on every visit)
    # too many wrong PINs: wait
    for _ in range(remote.PIN_TRIES):
        status, data = _post(base + "/login", json.dumps({"pin": wrong}).encode())
    assert status == 429 and data["wait"] > 0
    # a new access code on the computer: the phones signed in must sign in again
    from clipasso_studio.gui.app_settings import app_settings

    app_settings().data["remote_token"] = ""
    remote.token()
    status, _, body = _get(base + "/", cookie)
    assert status == 200 and b"login.js" in body
    status, _, body = _get(base + "/api/get/studio", cookie)
    assert status == 403 and json.loads(body)["error"] == "no access"  # (the page then loads the PIN page)


def test_phone_card_pin(qapp, fresh_settings):
    from types import SimpleNamespace

    from clipasso_studio.gui import remote
    from clipasso_studio.gui.app_settings import app_settings
    from clipasso_studio.gui.phone_ui import PhoneCard

    app_settings().data.update(remote_on=True)
    card = PhoneCard()
    card.set_link(SimpleNamespace(running=lambda: True, server=SimpleNamespace(port=8765), error="",
                                  apply_settings=lambda: ""))
    card.refresh()
    p = remote.pin()
    assert card.pin_edit.text() == p
    fixed = card.fixed.text()
    assert ":8765/'" in fixed and "?t=" not in fixed and "?t=" in card.url.text()
    card.pin_edit.setText("246810")
    card._pin_changed()
    assert app_settings().get("remote_pin") == "246810" and remote.pin() == "246810"
    card.pin_edit.setText("12")
    card._pin_changed()
    assert card.pin_edit.text() == "246810" and remote.pin() == "246810"  # (not six digits: the PIN stays)
    new = card.new_pin()
    assert remote.valid_pin(new) and remote.pin() == new and card.pin_edit.text() == new


def test_backup_leaves_the_pin_out():
    from clipasso_studio.gui import backup

    assert {"remote_pin", "remote_token", "telegram_token"} <= set(backup.SECRET_KEYS)
