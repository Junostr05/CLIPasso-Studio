"""3.8: the update from the phone in a real browser – the "App" tab, the PIN, and the page that comes back by itself
when the app has restarted with a new version (the app is ended and started again on the same port, saying it is
a newer version)."""

import pytest

from tests.e2e.conftest import start_app, stop_app


@pytest.fixture
def restartable(browser, tmp_path):
    procs = []

    def start(**kw):
        proc, app = start_app(tmp_path, **kw)
        procs.append(proc)
        return proc, app

    yield start
    for proc in procs:
        if proc.poll() is None:
            stop_app(proc)


def test_the_page_comes_back_after_the_update(phone, restartable):
    proc, app = restartable()
    page = phone.page
    page.goto(app.url)
    page.wait_for_selector("#methods button")
    phone.tab("app")
    version = page.text_content("#app-version")
    assert version and page.is_visible("#update-check") and not page.is_visible("#update-install")
    assert phone.width() == 390
    # the PIN sheet (opened as after "Download & install")
    page.evaluate("document.querySelector('#update-install').hidden = false")
    page.click("#update-install")
    page.wait_for_selector("#pin-sheet:not([hidden])")
    page.fill("#pin-input", "12")
    with page.expect_response("**/api/do") as answer:
        page.click("#pin-ok")
    assert answer.value.status == 403
    phone.wait_js("document.querySelector('#pin-msg').textContent.length > 0")
    page.click("#pin-close")
    # the app installs and restarts: gone for a moment, then back as 99.0.0 on the same port
    page.evaluate("updating = true")
    stop_app(proc)
    page.wait_for_selector("#restart:not([hidden])", timeout=30000)
    _, again = restartable(port=app.port, version="99.0.0")
    assert again.port == app.port
    phone.wait_js("document.readyState === 'complete' && typeof CFG !== 'undefined' && CFG.version === '99.0.0'", 60)
    page.wait_for_selector("#toast:not([hidden])")
    assert "99.0.0" in page.text_content("#toast")
    assert page.is_hidden("#restart")
    assert [e for e in phone.errors if "Failed to load" not in e and "ERR_" not in e and "403" not in e] == []
