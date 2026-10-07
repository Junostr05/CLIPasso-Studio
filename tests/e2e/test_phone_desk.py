"""3.8: the page on a wide screen – almost the studio of the PC (three columns, the areas in a bar on the left);
a switch for phone / studio / automatic that the browser keeps."""

import os

import pytest

from tests.e2e.conftest import Phone

DESKTOP = {"viewport": {"width": 1440, "height": 900}, "device_scale_factor": 1, "is_mobile": False,
           "has_touch": False}
TABLET = {"viewport": {"width": 1180, "height": 820}, "device_scale_factor": 2, "is_mobile": True,
          "has_touch": True}


@pytest.fixture
def screen(browser, studio_app):
    made = []

    def open_page(kind=DESKTOP) -> Phone:
        ph = Phone(browser.new_context(**kind, color_scheme="dark"))
        made.append(ph)
        ph.page.goto(studio_app.url)
        ph.page.wait_for_selector("#methods button")
        return ph

    yield open_page
    for ph in made:
        ph.context.close()


def _shot(ph: Phone, name: str):
    folder = os.environ.get("PHONE_SHOTS")
    if folder:
        os.makedirs(folder, exist_ok=True)
        ph.page.screenshot(path=os.path.join(folder, name + ".png"))


def test_the_studio_on_a_computer(screen):
    ph = screen()
    page = ph.page
    ph.wait_js("document.body.classList.contains('desk')")
    assert page.is_visible("#desk") and page.is_hidden("#tab-studio")
    columns = page.evaluate("""() => Object.fromEntries(['left', 'center', 'right'].map(c =>
        [c, [...document.querySelector('#desk-' + c).children].map(e => e.id)]))""")
    assert columns["left"][:2] == ["picture-card", "details-card"] and "export-card" in columns["left"]
    assert columns["center"][:2] == ["method-card", "sketch-card"] and columns["center"][-1] == "startbar"
    assert columns["right"][:2] == ["preset-card", "params-card"]
    boxes = [page.eval_on_selector(f"#desk-{c}", "e => e.getBoundingClientRect().left") for c in
             ("left", "center", "right")]
    assert boxes == sorted(boxes) and boxes[2] - boxes[0] > 600  # side by side
    assert page.is_hidden("#tabs button[data-tab=sketch]")  # (the sketch is part of the studio here)
    assert page.eval_on_selector("#tabs", "e => e.getBoundingClientRect().width") < 120  # a bar on the left
    assert ph.width() == 1440
    _shot(ph, "desk_studio")
    for tab in ("gallery", "queue", "app"):
        ph.tab(tab)
        assert page.is_hidden("#desk") and ph.width() == 1440, tab
    _shot(ph, "desk_app")
    # a result opened from the gallery: in the middle column, no sketch tab
    ph.tab("gallery")
    page.click("#results .result:has-text('camel')")
    page.wait_for_selector("#viewer:not([hidden])")
    page.click("#viewer-open")
    ph.wait_js("!document.querySelector('#desk').hidden && document.querySelector('#sketch').src.length > 0")
    _shot(ph, "desk_result")
    assert ph.errors == []


def test_the_switch_is_kept(screen):
    ph = screen()
    page = ph.page
    ph.wait_js("document.body.classList.contains('desk')")
    ph.tab("app")
    page.click("#layout button[data-layout=phone]")
    ph.wait_js("!document.body.classList.contains('desk')")
    ph.tab("studio")
    assert page.eval_on_selector("#picture-card", "e => e.parentElement.id") == "tab-studio"
    assert page.eval_on_selector("#sketch-card", "e => e.parentElement.id") == "tab-sketch"
    page.reload()
    page.wait_for_selector("#methods button")
    assert not page.evaluate("document.body.classList.contains('desk')")  # (kept by the browser)
    ph.tab("app")
    page.click("#layout button[data-layout=auto]")
    ph.wait_js("document.body.classList.contains('desk')")
    assert ph.errors == []


def test_tablet_across_and_the_phone(screen):
    tablet = screen(TABLET)
    tablet.wait_js("document.body.classList.contains('desk')")
    assert tablet.width() == 1180
    _shot(tablet, "desk_tablet")
    phone = screen({"viewport": {"width": 390, "height": 844}, "device_scale_factor": 2, "is_mobile": True,
                    "has_touch": True})
    assert not phone.page.evaluate("document.body.classList.contains('desk')")
    assert phone.page.is_visible("#tabs button[data-tab=sketch]") and phone.width() == 390
