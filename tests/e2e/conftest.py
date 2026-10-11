"""Browser tests of the phone page: the app runs in a process of its own (tests/e2e/app_harness.py), Chromium
(Playwright) uses the page like a phone. Skipped where Playwright or its browser is missing."""

import os
import queue
import subprocess
import sys
import threading
import time
from pathlib import Path
from types import SimpleNamespace

import pytest

ROOT = Path(__file__).resolve().parents[2]
PHONE = {"viewport": {"width": 390, "height": 844}, "device_scale_factor": 2, "is_mobile": True, "has_touch": True}


def pytest_collection_modifyitems(items):
    for item in items:
        if "tests/e2e/" in str(item.fspath).replace(os.sep, "/"):
            item.add_marker(pytest.mark.e2e)


@pytest.fixture(scope="session")
def browser():
    sync_api = pytest.importorskip("playwright.sync_api")
    with sync_api.sync_playwright() as p:
        try:
            b = p.chromium.launch()
        except Exception as exc:  # (no browser installed: python -m playwright install chromium)
            pytest.skip(f"no browser for the phone tests: {str(exc).splitlines()[0]}")
        yield b
        b.close()


def start_app(tmp: Path, lang: str = "de", port: int = 0, version: str = ""):
    """The app in a process of its own (tests/e2e/app_harness.py): (process, its address, PIN, folders, log)."""
    env = {**os.environ, "QT_QPA_PLATFORM": "offscreen",
           "PYTHONPATH": os.pathsep.join([str(ROOT), os.environ.get("PYTHONPATH", "")])}
    if version:
        env["CLIPASSO_E2E_VERSION"] = version
    args = [sys.executable, "-m", "tests.e2e.app_harness", str(tmp / "data"), str(tmp / "out"), lang]
    if port:
        args.append(str(port))
    proc = subprocess.Popen(args, cwd=ROOT, env=env, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                            stderr=subprocess.STDOUT, text=True, encoding="utf-8", errors="replace")
    lines: queue.Queue = queue.Queue()
    log: list[str] = []

    def read():
        for line in proc.stdout:
            log.append(line)
            lines.put(line)

    threading.Thread(target=read, daemon=True).start()
    found = {}
    try:
        while len(found) < 2:
            line = lines.get(timeout=180)
            key, _, value = line.strip().partition(" ")
            if key in ("URL", "PIN"):
                found[key] = value
    except queue.Empty:
        proc.kill()
        pytest.fail("the app did not start:\n" + "".join(log[-40:]))
    url = found["URL"]
    _wait_until_answering(url, proc, log)
    return proc, SimpleNamespace(url=url, base=url.split("/?", 1)[0], pin=found["PIN"], out=tmp / "out",
                                 data=tmp / "data", log=log, port=int(url.split(":")[2].split("/")[0]))


def stop_app(proc) -> None:
    proc.stdin.close()
    try:
        proc.wait(60)
    except subprocess.TimeoutExpired:
        proc.kill()


@pytest.fixture(scope="module")
def studio_app(browser, tmp_path_factory):
    proc, app = start_app(tmp_path_factory.mktemp("e2e"))
    yield app
    stop_app(proc)


def _wait_until_answering(url: str, proc, log, seconds: float = 180.0):
    """Until the app answers the page's requests (a cold start imports PyTorch in the GUI thread for a while)."""
    import urllib.error
    import urllib.request

    class NoRedirect(urllib.request.HTTPRedirectHandler):
        def redirect_request(self, *args, **kwargs):
            return None

    opener = urllib.request.build_opener(NoRedirect)
    try:
        opener.open(url, timeout=30)
        raise AssertionError("no redirect from the QR code's link")
    except urllib.error.HTTPError as e:
        cookie = e.headers["Set-Cookie"].split(";")[0]
    base = url.split("/?", 1)[0]
    end = time.time() + seconds
    while time.time() < end:
        try:
            req = urllib.request.Request(base + "/api/get/studio", headers={"Cookie": cookie})
            with urllib.request.urlopen(req, timeout=30) as r:
                if r.status == 200:
                    return
        except (urllib.error.URLError, OSError):
            pass
        if proc.poll() is not None:
            break
        time.sleep(0.5)
    proc.kill()
    pytest.fail("the app does not answer:\n" + "".join(log[-40:]))


class Phone:
    """A phone's browser tab: the page, the errors it logged, helpers."""

    def __init__(self, context):
        self.context = context
        context.set_default_timeout(60000)  # (CI machines are slow)
        self.page = context.new_page()
        self.errors: list[str] = []
        self.page.on("pageerror", lambda e: self.errors.append(f"pageerror {e}"))
        self.page.on("console", lambda m: self.errors.append(f"console {m.text}") if m.type == "error" else None)

    def state(self) -> dict:
        """The studio as the page sees it (with the page's cookie)."""
        return self.page.request.get(self.page.url.split("/?")[0].rstrip("/") + "/api/get/studio").json()

    def wait_state(self, cond, seconds: float = 15.0) -> dict:
        """Ask the studio until ``cond(state)`` holds."""
        end = time.time() + seconds
        while time.time() < end:
            st = self.state()
            if cond(st):
                return st
            self.page.wait_for_timeout(200)
        raise AssertionError("the studio did not get there")

    def wait_js(self, expression: str, seconds: float = 10.0):
        """Wait until the expression is true in the page (asked from outside: the page's CSP allows no eval, which
        Playwright's wait_for_function needs). A page that loads itself again meanwhile (after an update) is asked
        again once it is there."""
        from playwright.sync_api import Error

        end = time.time() + seconds
        while time.time() < end:
            try:
                if self.page.evaluate(expression):
                    return
            except Error as e:
                if "context was destroyed" not in str(e) and "navigat" not in str(e):
                    raise
                self.page.wait_for_load_state("load", timeout=max(1000, (end - time.time()) * 1000))
                continue
            self.page.wait_for_timeout(100)
        raise AssertionError(f"not true in time: {expression}")

    def tab(self, name: str):
        self.page.click(f"#tabs button[data-tab={name}]")
        self.page.wait_for_timeout(400)

    def open_result(self, text: str):
        """A result of the gallery in the studio (through its large view), then the sketch tab."""
        self.tab("gallery")
        self.page.click(f"#results .result:has-text('{text}')")
        self.page.wait_for_selector("#viewer:not([hidden])")
        self.page.click("#viewer-open")
        self.wait_js("!document.querySelector('#tab-sketch').hidden")

    def width(self) -> int:
        return self.page.evaluate("document.documentElement.scrollWidth")


@pytest.hookimpl(hookwrapper=True)
def pytest_runtest_makereport(item, call):
    outcome = yield
    rep = outcome.get_result()
    if rep.when == "call":
        item.failed_call = rep.failed


@pytest.fixture
def phone(browser, request):
    """A fresh phone (no cookie yet). When the test failed: what the page and the app said."""
    context = browser.new_context(**PHONE, accept_downloads=True, color_scheme="dark")
    ph = Phone(context)
    yield ph
    if getattr(request.node, "failed_call", False):
        try:
            print("page status:", ph.page.text_content("#status", timeout=3000), "| errors:", ph.errors)
        except Exception as exc:
            print("page gone:", str(exc).splitlines()[0], "| errors:", ph.errors)
        print("page url:", ph.page.url)
        try:
            print("page:", ph.page.evaluate("document.body.className + ' | ' + "
                                            "((document.querySelector('#msg') || {}).textContent || '')"))
        except Exception as exc:
            print("page not readable:", exc)
        app = request.getfixturevalue("studio_app") if "studio_app" in request.fixturenames else None
        if app is not None:
            import urllib.request

            try:
                with urllib.request.urlopen(app.base + "/login.js", timeout=5) as r:
                    print("server answers:", r.status)
            except Exception as exc:
                print("server does not answer:", exc)
            print("app log:\n" + "".join(app.log[-30:]))
    context.close()


@pytest.fixture
def signed_in(phone, studio_app):
    """A phone signed in through the QR code's link, on the studio tab."""
    phone.page.goto(studio_app.url)
    phone.page.wait_for_selector("#methods button")
    return phone
