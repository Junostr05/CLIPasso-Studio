"""3.8: the page on a wide screen – almost the studio of the PC; a switch for phone / studio / automatic that the
browser keeps. 4.2: laid out like the 4.0 studio – a header with the areas, the steps on the left, the sketch in the
middle, the job's sketches on the right, the job in a footer."""

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
    columns = page.evaluate("""() => Object.fromEntries(['left', 'center', 'right', 'footer'].map(c =>
        [c, [...document.querySelector('#desk-' + c).children].map(e => e.id)]))""")
    assert columns["left"][:3] == ["picture-card", "method-card", "preset-card"] and "params-card" in columns["left"]
    assert columns["center"][0] == "sketch-card" and "export-card" in columns["center"]
    assert columns["right"][0] == "seeds-card"
    assert columns["footer"] == ["desk-job", "startbar", "run-buttons"]
    assert page.eval_on_selector("#seeds", "e => e.parentElement.id") == "seeds-list"
    boxes = [page.eval_on_selector(f"#desk-{c}", "e => e.getBoundingClientRect().left") for c in
             ("left", "center", "right")]
    assert boxes == sorted(boxes) and boxes[2] - boxes[0] > 600  # side by side
    # the header: the logo and the four areas in one row of 52 px; the footer: the job, at the bottom
    assert page.eval_on_selector("#tabs", "e => e.parentElement.id") == "top-tabs"
    assert page.eval_on_selector("#top", "e => Math.round(e.getBoundingClientRect().height)") <= 53
    tabs = page.evaluate("[...document.querySelectorAll('#tabs button')].map(b => b.getBoundingClientRect().top)")
    assert len(tabs) == 4 and max(tabs) - min(tabs) < 2 and max(tabs) < 40
    foot = page.eval_on_selector("#desk-footer", "e => [e.getBoundingClientRect().bottom, e.offsetHeight]")
    assert foot == [900, 76]
    for id_ in ("start", "pause", "cancel", "status"):
        assert page.eval_on_selector(f"#{id_}", "e => !!e.closest('#desk-footer')"), id_
    assert ph.width() == 1440
    _shot(ph, "desk_studio")
    for tab in ("gallery", "queue", "app"):
        ph.tab(tab)
        assert page.is_hidden("#desk") and ph.width() == 1440, tab
    _shot(ph, "desk_app")
    # a result opened from the gallery: in the middle column
    ph.tab("gallery")
    page.click("#results .result:has-text('camel')")
    page.wait_for_selector("#viewer:not([hidden])")
    page.click("#viewer-open")
    ph.wait_js("!document.querySelector('#desk').hidden && document.querySelector('#sketch').src.length > 0")
    several = page.evaluate("document.querySelectorAll('#seeds button').length") > 1
    assert page.is_visible("#seeds-card") == several  # (one sketch: no list of one)
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
    assert page.eval_on_selector("#sketch-card", "e => e.parentElement.id") == "studio-sketch"
    assert page.eval_on_selector("#tabs", "e => e.parentElement.tagName") == "BODY"  # (back at the bottom)
    assert page.eval_on_selector("#startbar", "e => e.parentElement.id") == "tab-studio"
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
    assert phone.page.evaluate("document.querySelectorAll('#tabs button').length") == 4 and phone.width() == 390
    assert phone.page.eval_on_selector("#tabs", "e => e.getBoundingClientRect().bottom") == 844  # (at the bottom)
