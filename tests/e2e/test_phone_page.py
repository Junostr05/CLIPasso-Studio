"""The phone page in a real browser (Chromium, phone size) against the running app."""

import io
import os

from PIL import Image


def test_sign_in_with_the_pin(phone, studio_app):
    page = phone.page
    page.goto(studio_app.base + "/")
    assert page.eval_on_selector("body", "b => b.className") == "login"
    page.fill("#pin", "123")
    page.click("#go")
    phone.wait_js("document.querySelector('#msg').textContent.length > 0")
    short = page.text_content("#msg")
    wrong = "000000" if studio_app.pin != "000000" else "111111"
    page.fill("#pin", wrong)
    with page.expect_response("**/login") as answer:
        page.click("#go")
    assert answer.value.status == 403
    phone.wait_js("!document.querySelector('#go').disabled && "
                  f"document.querySelector('#msg').textContent !== {short!r}")
    page.fill("#pin", studio_app.pin)
    with page.expect_response("**/login") as answer:
        page.click("#go")
    assert answer.value.status == 200
    page.wait_for_selector("#methods button")
    cookie = next(c for c in phone.context.cookies() if c["name"] == "cs_access")
    assert cookie["httpOnly"] and cookie["sameSite"] == "Strict"
    assert [e for e in phone.errors if "403" not in e] == []  # (the wrong PIN's answer is a 403)


def test_every_tab_fits_the_phone(signed_in):
    for tab in ("studio", "sketch", "gallery", "queue", "app"):
        signed_in.tab(tab)
        assert signed_in.width() == 390, tab
    assert signed_in.errors == []


def test_own_preset_made_on_the_phone(signed_in):
    page = signed_in.page
    page.click("#methods button >> nth=0")
    page.wait_for_timeout(800)
    key = page.eval_on_selector("#params details[open] .field[data-kind=int] input[type=number]",
                                "e => e.closest('.field').dataset.key")
    box = f"#params .field[data-key={key}] input[type=number]"
    page.fill(box, "7")
    page.eval_on_selector(box, "e => e.dispatchEvent(new Event('change'))")
    signed_in.wait_state(lambda st: st["settings"][key] == 7)
    page.click("#to-preset")
    assert page.evaluate("document.activeElement.id") == "preset-name"
    page.fill("#preset-name", "Vom  Handy ")
    page.press("#preset-name", "Enter")
    page.wait_for_selector("#user-presets .mine-name.on")
    st = signed_in.state()
    assert st["user_preset"] == "Vom Handy" and st["settings"][key] == 7
    page.once("dialog", lambda d: d.accept())
    page.click("#user-presets .mine-row >> nth=0 >> button.small")
    page.wait_for_selector("#user-presets .muted")
    assert signed_in.state()["user_presets"] == []
    assert signed_in.errors == []


def test_export_without_background(signed_in, tmp_path):
    page = signed_in.page
    signed_in.open_result("camel")
    page.wait_for_selector("#export-card:not([hidden])")
    page.click("#formats button:text-is('PNG')")
    page.check("#export-opts label.check input")
    page.fill("#export-opts .field:has(label:text-matches('px')) input", "128")
    page.click("#export-go")
    page.wait_for_selector("#export-dl:not([hidden])", timeout=60000)
    with page.expect_download() as info:
        page.click("#export-dl")
    path = tmp_path / info.value.suggested_filename
    info.value.save_as(path)
    im = Image.open(io.BytesIO(path.read_bytes()))
    assert path.suffix == ".png" and im.mode == "RGBA" and im.size == (128, 128) and im.getpixel((0, 0))[3] == 0
    assert signed_in.width() == 390 and signed_in.errors == []


def test_live_updates_reach_another_phone(signed_in, browser, studio_app):
    """A change made on one phone shows on another at once (server-sent events – the other asks only every 15 s)."""
    from tests.e2e.conftest import PHONE, Phone

    other = Phone(browser.new_context(**PHONE))
    try:
        other.page.goto(studio_app.url)
        other.page.wait_for_selector("#methods button")
        other.wait_js("isLive()", 5)
        signed_in.page.click("#methods button >> nth=0")
        other.wait_js("document.querySelector('#methods button:nth-child(1)').classList.contains('on')")
        signed_in.page.click("#methods button >> nth=1")
        other.wait_js("document.querySelector('#methods button:nth-child(2)').classList.contains('on')", 3)
        assert other.errors == []
    finally:
        other.context.close()
        signed_in.page.click("#methods button >> nth=0")


def test_scenesketch_background_matrix_and_layers(signed_in, studio_app):
    """SceneSketch on the phone: the background LaMa filled in, the matrix, a cell's layers."""
    page = signed_in.page
    shots = os.environ.get("PHONE_SHOTS")  # (screenshots for a look, when asked for)
    signed_in.open_result("scene")
    signed_in.wait_js("!document.querySelector('#scene-views').hidden")
    page.click("#scene-views button[data-view=background]")
    signed_in.wait_js("document.querySelector('#scene-bg').naturalWidth > 0")
    assert page.is_hidden("#no-bg") and page.is_hidden("#sketch-box")
    page.click("#scene-views button[data-view=matrix]")
    signed_in.wait_js("document.querySelectorAll('#matrix button.cell').length === 2")
    assert page.eval_on_selector("#matrix button.cell.best", "b => !!b")
    if shots:
        page.screenshot(path=os.path.join(shots, "scene_matrix.png"))
    page.click("#matrix button.cell >> nth=1")
    signed_in.wait_state(lambda st: st["shown"] == 801)
    signed_in.wait_js("!document.querySelector('#sketch-box').hidden")
    page.click("#layer-switch button[data-part=object]")
    signed_in.wait_js("document.querySelector('#sketch').src.includes('part=object')")
    signed_in.wait_js("document.querySelector('#sketch').naturalWidth > 0")
    if shots:
        page.screenshot(path=os.path.join(shots, "scene_object_layer.png"))
    assert signed_in.width() == 390 and signed_in.errors == []


def _swipe(page, selector, dx):
    """A horizontal swipe over the element (mouse pointer events, as a finger's)."""
    box = page.locator(selector).bounding_box()
    x, y = box["x"] + box["width"] / 2, box["y"] + box["height"] / 2
    page.mouse.move(x, y)
    page.mouse.down()
    page.mouse.move(x + dx / 2, y, steps=4)
    page.mouse.move(x + dx, y, steps=4)
    page.mouse.up()


def test_gallery_search_favourite_and_viewer(signed_in):
    page = signed_in.page
    signed_in.tab("gallery")
    signed_in.wait_js("document.querySelectorAll('#results .result').length >= 2")
    page.fill("#search", "scene")
    signed_in.wait_js("document.querySelectorAll('#results .result').length === 1")
    page.fill("#search", "")
    signed_in.wait_js("document.querySelectorAll('#results .result').length >= 2")
    page.click("#results .result:has-text('camel') >> .fav")
    signed_in.wait_js("document.querySelector('#results .result .fav.on') !== null")
    page.click("#filter-fav")
    signed_in.wait_js("document.querySelectorAll('#results .result').length === 1")
    page.click("#filter-fav")
    signed_in.wait_js("document.querySelectorAll('#results .result').length >= 2")
    # the large view: swipe to the next result and back
    page.click("#results .result >> nth=0")
    page.wait_for_selector("#viewer:not([hidden])")
    first = page.text_content("#viewer-name")
    _swipe(page, "#viewer-img", -150)
    signed_in.wait_js(f"document.querySelector('#viewer-name').textContent !== {first!r}")
    _swipe(page, "#viewer-img", 150)
    signed_in.wait_js(f"document.querySelector('#viewer-name').textContent === {first!r}")
    page.click("#viewer-close")
    page.click("#results .result:has-text('camel') >> .fav")  # (the favourite off again)
    assert signed_in.width() == 390 and signed_in.errors == []


def test_queue_several_photos_drag_and_remove(signed_in, tmp_path):
    from PIL import Image

    page = signed_in.page
    files = []
    for k, colour in enumerate(("red", "green", "blue")):
        path = tmp_path / f"photo{k}.png"
        Image.new("RGB", (64, 48), colour).save(path)
        files.append(str(path))
    signed_in.tab("queue")
    page.set_input_files("#many", files)
    signed_in.wait_js("document.querySelector('#many-msg').textContent.startsWith('3')", 30)
    signed_in.wait_js("document.querySelectorAll('#jobs .job .handle').length >= 3")
    names = lambda: page.eval_on_selector_all("#jobs .job b", "bs => bs.map(b => b.textContent)")  # noqa: E731
    before = names()
    last = page.locator("#jobs .job .handle").last
    first = page.locator("#jobs .job").first.bounding_box()
    box = last.bounding_box()
    page.mouse.move(box["x"] + 5, box["y"] + 5)
    page.mouse.down()
    page.mouse.move(box["x"] + 5, first["y"] - 10, steps=8)
    page.mouse.up()
    signed_in.wait_js(f"document.querySelector('#jobs .job b').textContent === {before[-1]!r}")
    assert names()[0] == before[-1]
    if os.environ.get("PHONE_SHOTS"):
        page.screenshot(path=os.path.join(os.environ["PHONE_SHOTS"], "queue.png"))
    for _ in range(3):  # (the queue empty again)
        page.click("#jobs .job >> nth=0 >> button.small")
        page.wait_for_timeout(400)
    signed_in.wait_js("document.querySelectorAll('#jobs .job .handle').length === 0")
    assert signed_in.errors == []


def test_compare_crop_and_swipe(signed_in):
    page = signed_in.page
    # a picture in the studio (a sample of the PC)
    page.click("#from-pc")
    page.click("#samples button >> nth=0")
    signed_in.wait_state(lambda st: st["image"] is not None)
    # compare: CLIPasso only (its models are there) – queued
    page.click("#compare-card summary")
    signed_in.wait_js("document.querySelectorAll('#compare-methods input').length === 4")
    for box in page.query_selector_all("#compare-methods input"):
        if box.get_attribute("value") != "clipasso" and box.is_checked():
            box.uncheck()
        elif box.get_attribute("value") == "clipasso" and not box.is_checked():
            box.check()
    page.click("#compare-go")
    signed_in.wait_js("document.querySelector('#compare-results .compare-item') !== null", 20)
    if os.environ.get("PHONE_SHOTS"):
        page.locator("#compare-card").screenshot(path=os.path.join(os.environ["PHONE_SHOTS"], "compare.png"))
    queue = page.request.get(page.url.split("/?")[0].rstrip("/") + "/api/get/queue").json()["jobs"]
    assert any(j["status"] == "queued" for j in queue)
    # crop: turned and cut to the left half -> a new picture
    before = signed_in.state()["image"]
    name = before["name"]
    page.click("#crop")
    signed_in.wait_js("document.querySelector('#crop-canvas').width > 0")
    page.click("#crop-right")
    canvas = page.locator("#crop-canvas").bounding_box()
    page.mouse.move(canvas["x"] + canvas["width"] - 2, canvas["y"] + canvas["height"] - 2)
    page.mouse.down()
    page.mouse.move(canvas["x"] + canvas["width"] / 2, canvas["y"] + canvas["height"] - 2, steps=5)
    page.mouse.up()
    box = page.evaluate("K.box")
    assert abs(box["w"] - 0.5) < 0.03 and box["h"] > 0.97 and box["x"] == 0
    if os.environ.get("PHONE_SHOTS"):
        page.screenshot(path=os.path.join(os.environ["PHONE_SHOTS"], "crop.png"))
    page.click("#crop-apply")
    st = signed_in.wait_state(lambda st: st["image"] and st["image"]["name"] != name)
    assert "-edited-" in st["image"]["name"]
    w0, h0 = (int(v) for v in before["size"].split("×"))
    w1, h1 = (int(v) for v in st["image"]["size"].split("×"))
    assert abs(w1 - h0 / 2) <= 0.03 * h0 and abs(h1 - w0) <= 2  # (turned a quarter, the left half)
    # swipe between the sketches of a job (the SceneSketch cells)
    signed_in.open_result("scene")
    signed_in.wait_js("document.querySelector('#sketch').naturalWidth > 0")
    shown = signed_in.state()["shown"]
    _swipe(page, "#sketch", -150 if shown == 800 else 150)
    signed_in.wait_state(lambda s: s["shown"] != shown)
    assert signed_in.errors == []
