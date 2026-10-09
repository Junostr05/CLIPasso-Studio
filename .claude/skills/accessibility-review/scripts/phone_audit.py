"""Accessibility audit of the phone page in a real browser – the page the phone remote serves, with the app running
offscreen (tests/e2e/app_harness.py: own folders, one finished result, one SceneSketch result).

For every tab (studio, sketch, gallery, queue) in light and dark it takes a phone-sized screenshot and checks what
is on screen:
- controls without a name, or whose name is only a symbol (✎, ×, ★ … – screen readers read the glyph's name);
- touch targets below 24 × 24 px (WCAG 2.2 AA 2.5.8) and below 44 × 44 px (the comfortable size, 2.5.5 AAA);
- text contrast below 4.5:1 (3:1 for large text), measured on the computed colours;
- form fields without a label, images without alt, a state shown only by the "on" class (no aria-pressed /
  aria-selected / aria-current).

Needs the dev requirements (PySide6, Playwright) and Chromium: python -m playwright install chromium.
Usage: python .claude/skills/accessibility-review/scripts/phone_audit.py OUT_DIR [--lang en|de]
       [--schemes light,dark] [--tabs studio,sketch,gallery,queue]
The report is printed and saved as OUT_DIR/phone_audit.md; the screenshots are next to it.
"""

from __future__ import annotations

import argparse
import os
import queue
import subprocess
import sys
import tempfile
import threading
from pathlib import Path

ROOT = Path(__file__).resolve().parents[4]
PHONE = {"viewport": {"width": 390, "height": 844}, "device_scale_factor": 2, "is_mobile": True, "has_touch": True}

AUDIT_JS = r"""
() => {
  const visible = el => {
    if (!el.getClientRects().length) return false;
    const s = getComputedStyle(el);
    if (s.visibility === "hidden" || s.display === "none" || +s.opacity === 0) return false;
    return !el.closest("[hidden]");
  };
  const describe = el => {
    let d = el.tagName.toLowerCase();
    if (el.id) d += "#" + el.id;
    for (const c of [...el.classList].slice(0, 3)) d += "." + c;
    for (const a of el.getAttributeNames())
      if (a.startsWith("data-") && a !== "data-t") d += `[${a}=${el.getAttribute(a)}]`;
    return d;
  };
  const name = el => {
    const aria = el.getAttribute("aria-label");
    if (aria && aria.trim()) return aria.trim();
    const by = el.getAttribute("aria-labelledby");
    if (by) return by.split(/\s+/).map(id => (document.getElementById(id) || {}).textContent || "").join(" ").trim();
    if (el.id) {
      const l = document.querySelector(`label[for="${el.id}"]`);
      if (l && l.textContent.trim()) return l.textContent.trim();
    }
    const wrap = el.closest("label");
    if (wrap && wrap !== el && wrap.textContent.trim()) return wrap.textContent.trim();
    if (el.tagName === "IMG") return (el.getAttribute("alt") || "").trim();
    let t = "";
    for (const n of el.childNodes) {
      if (n.nodeType === 3) t += n.textContent;
      else if (n.nodeType === 1 && n.getAttribute("aria-hidden") !== "true") t += name(n) || n.textContent;
    }
    t = t.replace(/\s+/g, " ").trim();
    if (t) return t;
    const img = el.querySelector("img[alt]"); if (img && img.alt.trim()) return img.alt.trim();
    return (el.getAttribute("title") || el.getAttribute("placeholder") || "").trim();
  };
  const rgb = c => { const m = c.match(/[\d.]+/g); return m ? m.map(Number) : [0, 0, 0, 1]; };
  const lum = ([r, g, b]) => { const f = v => (v /= 255) <= 0.03928 ? v / 12.92 : ((v + 0.055) / 1.055) ** 2.4;
                                return 0.2126 * f(r) + 0.7152 * f(g) + 0.0722 * f(b); };
  const ratio = (a, b) => { const [h, l] = [lum(a), lum(b)].sort((x, y) => y - x); return (h + 0.05) / (l + 0.05); };
  const bgOf = el => {
    for (let e = el; e; e = e.parentElement) {
      const s = getComputedStyle(e);
      if (s.backgroundImage !== "none" && e.tagName !== "BODY") return null;  // (text on a picture: judge by eye)
      const c = rgb(s.backgroundColor);
      if ((c[3] ?? 1) > 0.5) return c;
    }
    return rgb(getComputedStyle(document.body).backgroundColor);
  };
  const out = [];
  const add = (kind, el, detail) => out.push({kind, el: describe(el), text: (name(el) || "").slice(0, 60), detail});
  const selector = "button, a[href], input, select, textarea, [role=button], [tabindex]:not([tabindex='-1'])";
  const controls = [...document.querySelectorAll(selector)].filter(visible);
  for (const el of controls) {
    const n = name(el);
    const type = (el.getAttribute("type") || "").toLowerCase();
    if (type === "hidden") continue;
    if (!n) add(["INPUT", "SELECT", "TEXTAREA"].includes(el.tagName) ? "field-without-label" : "no-name", el, "");
    else if (!/[\p{L}\p{N}]/u.test(n)) add("symbol-only-name", el, `name is “${n}”`);
    else if (/^[^\p{L}\p{N}\s(“"„'…]+\s*\p{L}/u.test(n) && el.tagName !== "SELECT")
      add("glyph-in-name", el, `name is “${n}”`);
    const r = el.getBoundingClientRect();
    const inline = el.tagName === "A" && getComputedStyle(el).display === "inline";
    if (!inline && type !== "range" && type !== "file") {
      const w = Math.round(r.width), h = Math.round(r.height);
      if (w < 24 || h < 24) add("target-below-24", el, `${w}×${h} px`);
      else if (w < 44 || h < 44) add("target-below-44", el, `${w}×${h} px`);
    }
    const states = ["aria-pressed", "aria-selected", "aria-current", "aria-checked"];
    if (el.classList.contains("on") && !states.some(a => el.hasAttribute(a)))
      add("state-only-visual", el, "class “on” without aria-pressed/selected/current");
  }
  for (const img of [...document.querySelectorAll("img")].filter(visible))
    if (!img.hasAttribute("alt")) add("img-without-alt", img, img.getAttribute("src") || "");
  const walker = document.createTreeWalker(document.body, NodeFilter.SHOW_TEXT);
  const seen = new Set();
  for (let n = walker.nextNode(); n; n = walker.nextNode()) {
    const el = n.parentElement;
    if (!el || seen.has(el) || !n.textContent.trim() || !visible(el)) continue;
    if (["SCRIPT", "STYLE", "OPTION"].includes(el.tagName)) continue;
    seen.add(el);
    if (el.closest(":disabled, [aria-disabled=true], .btn.off")) continue;  // (inactive controls are exempt from 1.4.3)
    const s = getComputedStyle(el);
    const fg = rgb(s.color), bg = bgOf(el);
    if (!bg) continue;
    const alpha = (fg[3] ?? 1) * +s.opacity;
    const mixed = fg.slice(0, 3).map((c, i) => c * alpha + bg[i] * (1 - alpha));
    const size = parseFloat(s.fontSize), bold = +s.fontWeight >= 700;
    const need = size >= 24 || (bold && size >= 18.66) ? 3 : 4.5;
    const r = ratio(mixed, bg);
    const where = `${s.color} on rgb(${bg.slice(0, 3).join(", ")}) · ${size}px`;
    if (r < need) out.push({kind: "text-contrast", el: describe(el), text: n.textContent.trim().slice(0, 50),
                            detail: `${r.toFixed(2)}:1 (needs ${need}:1) · ${where}`});
  }
  if (!document.documentElement.lang) out.push({kind: "no-lang", el: "html", text: "", detail: ""});
  return out;
}
"""

KINDS = {
    "no-name": ("🔴", "Control without a name (4.1.2)", "Give it text, an aria-label, or a label."),
    "field-without-label": ("🔴", "Field without a label (1.3.1, 3.3.2)", "Add <label for> or aria-label."),
    "symbol-only-name": ("🟡", "Name is only a symbol (4.1.2)",
                         "Screen readers read the glyph's Unicode name. Add aria-label with words (from the texts)."),
    "glyph-in-name": ("🟢", "Decorative glyph read before the name",
                      "Wrap the glyph in <span aria-hidden=\"true\"> so only the word is read."),
    "target-below-24": ("🔴", "Touch target below 24 × 24 px (2.5.8 AA)", "Raise min-height/min-width or padding."),
    "target-below-44": ("🟢", "Touch target below 44 × 44 px (2.5.5 AAA, comfortable size)",
                        "Fine for AA; for thumbs on a phone 44 px is kinder where space allows."),
    "state-only-visual": ("🟡", "Selected/pressed state only visual (4.1.2)",
                          "Set aria-pressed (toggles), aria-selected (tabs) or aria-current (navigation) with the "
                          "class."),
    "img-without-alt": ("🟡", "Image without alt (1.1.1)", "alt=\"\" when decorative, else a short description."),
    "text-contrast": ("🔴", "Text contrast too low (1.4.3)", "Use a darker/lighter token in phone.css :root."),
    "no-lang": ("🟡", "Page without lang (3.1.1)", "Set <html lang>."),
}


def start_app(lang: str):
    tmp = Path(tempfile.mkdtemp(prefix="phone_audit_"))
    env = {**os.environ, "QT_QPA_PLATFORM": "offscreen",
           "PYTHONPATH": os.pathsep.join([str(ROOT), os.environ.get("PYTHONPATH", "")])}
    proc = subprocess.Popen([sys.executable, "-m", "tests.e2e.app_harness", str(tmp / "data"), str(tmp / "out"), lang],
                            cwd=ROOT, env=env, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                            text=True, encoding="utf-8", errors="replace")
    lines: queue.Queue = queue.Queue()
    log: list[str] = []

    def read():
        for line in proc.stdout:
            log.append(line)
            lines.put(line)

    threading.Thread(target=read, daemon=True).start()
    found = {}
    while len(found) < 2:
        try:
            line = lines.get(timeout=180)
        except queue.Empty:
            proc.kill()
            raise SystemExit("the app did not start:\n" + "".join(log[-40:]))
        key, _, value = line.strip().partition(" ")
        if key in ("URL", "PIN"):
            found[key] = value
    return proc, found["URL"], log


def main() -> int:
    if hasattr(sys.stdout, "reconfigure"):  # (Windows consoles default to a code page without ✅ “ ” →)
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("out")
    ap.add_argument("--lang", default="en")
    ap.add_argument("--schemes", default="light,dark")
    ap.add_argument("--tabs", default="studio,sketch,gallery,queue")
    args = ap.parse_args()
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    from playwright.sync_api import sync_playwright

    proc, url, log = start_app(args.lang)
    findings: dict[tuple, dict] = {}
    shots = []
    try:
        with sync_playwright() as p:
            browser = p.chromium.launch()
            for scheme in args.schemes.split(","):
                ctx = browser.new_context(**PHONE, color_scheme=scheme)
                page = ctx.new_page()
                page.goto(url)
                page.wait_for_selector("#tabs button", timeout=30000)
                page.wait_for_timeout(1500)
                for tab in args.tabs.split(","):
                    button = page.locator(f'#tabs button[data-tab="{tab}"]')
                    if button.count():
                        button.click()
                        page.wait_for_timeout(900)
                    shot = out / f"phone_{tab}_{scheme}_{args.lang}.png"
                    page.screenshot(path=str(shot), full_page=True)
                    shots.append(shot.name)
                    for f in page.evaluate(AUDIT_JS):
                        key = (f["kind"], f["el"], f["text"], f["detail"] if f["kind"] == "text-contrast" else "")
                        entry = findings.setdefault(key, {**f, "where": []})
                        entry["where"].append(f"{tab}/{scheme}")
                ctx.close()
            browser.close()
    finally:
        try:
            proc.stdin.close()
            proc.wait(timeout=60)
        except Exception:
            proc.kill()

    lines = [f"# Phone page accessibility – {args.lang}, {args.schemes}", "",
             f"Screenshots in {out}: " + ", ".join(shots), ""]
    for kind, (sev, title, fix) in KINDS.items():
        rows = [f for f in findings.values() if f["kind"] == kind]
        if not rows:
            continue
        lines += [f"## {sev} {title} ({len(rows)})", fix, ""]
        for f in sorted(rows, key=lambda r: r["el"]):
            where = sorted(set(f["where"]))
            text = f" “{f['text']}”" if f["text"] else ""
            detail = f" — {f['detail']}" if f["detail"] else ""
            lines.append(f"- `{f['el']}`{text}{detail} · {', '.join(where[:4])}{' …' if len(where) > 4 else ''}")
        lines.append("")
    if not findings:
        lines.append("No findings.")
    report = "\n".join(lines)
    (out / "phone_audit.md").write_text(report, encoding="utf-8")
    print(report)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
