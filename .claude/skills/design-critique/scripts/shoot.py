"""Screenshots of the studio for a design review: every page in dark and light, English and German (German texts
are longer – that is where things clip), optionally at the smallest window size, plus one contact sheet per page
with the variants side by side.

Wraps tools/screenshots.py (offscreen Qt; the user's settings are untouched).
Usage: python .claude/skills/design-critique/scripts/shoot.py OUT_DIR [--pages studio,gallery,...]
       [--themes dark,light] [--langs en,de] [--small] [--demo] [--job JOB_DIR ...] [--queue IMAGE[:METHOD] ...]
       [--set KEY=VALUE ...]
--demo fills the screens: finished CLIPasso, SwiftSketch and SceneSketch results (tests/helpers.py – simple
placeholder strokes, not real sketches) and two waiting jobs in the queue.
Pages: studio, studio:<method>[:<view>] (e.g. studio:scenesketch:matrix), compare, queue, gallery, models,
settings, about. --small adds the smallest window (MIN_WIDTH × 760). Look at OUT_DIR/sheet_<page>.png first.
"""

from __future__ import annotations

import argparse
import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[4]
SCREENSHOTS = ROOT / "tools" / "screenshots.py"
DEFAULT_PAGES = "studio,compare,queue,gallery,models,settings,about"


def min_width() -> int:
    for line in (ROOT / "clipasso_studio" / "gui" / "main_window.py").read_text(encoding="utf-8").splitlines():
        if line.startswith("MIN_WIDTH"):
            return int(line.split("=")[1].split("#")[0])
    return 1200


def run(out: Path, theme: str, lang: str, pages: str, size: str, extra: list[str]) -> bool:
    cmd = [sys.executable, str(SCREENSHOTS), str(out), "--theme", theme, "--lang", lang, "--pages", pages,
           "--size", size, *extra]
    env = {**os.environ, "QT_QPA_PLATFORM": "offscreen"}
    res = subprocess.run(cmd, cwd=ROOT, env=env, capture_output=True, text=True, timeout=900)
    if res.returncode:
        print(f"screenshots failed ({theme}/{lang}/{size}):\n{res.stdout[-2000:]}{res.stderr[-2000:]}", file=sys.stderr)
    return res.returncode == 0


def demo_jobs() -> tuple[list[str], list[str]]:
    """Finished results of three methods and two waiting images, in a fresh folder (the app's real data is never
    touched)."""
    import shutil
    import tempfile

    sys.path.insert(0, str(ROOT))
    from tests.helpers import fake_job, fake_scene_job

    out = Path(tempfile.mkdtemp(prefix="shoot_demo_")) / "out"
    out.mkdir(parents=True)
    photo = out.parent / "rose.jpeg"
    shutil.copy(ROOT / "clipasso_studio" / "resources" / "samples" / "rose.jpeg", photo)
    jobs = [fake_job(str(out), "rose_clipasso", str(photo), 29.4, method="clipasso"),
            fake_job(str(out), "rose_swiftsketch", str(photo), 31.2, method="swiftsketch",
                     created="2026-09-30 09:30:00"),
            fake_scene_job(str(out), "rose_scene", str(photo), levels=3)]
    return jobs, [f"{photo}:clipasso", f"{photo}:swiftsketch"]


def sheet(files: list[tuple[str, Path]], target: Path, width: int = 900) -> None:
    from PIL import Image, ImageDraw

    tiles = []
    for label, path in files:
        if not path.exists():
            continue
        im = Image.open(path).convert("RGB")
        im = im.resize((width, round(im.height * width / im.width)))
        tiles.append((label, im))
    if not tiles:
        return
    cols = 2
    rows = (len(tiles) + cols - 1) // cols
    cell_h = max(im.height for _, im in tiles) + 28
    canvas = Image.new("RGB", (cols * width + (cols - 1) * 12, rows * cell_h), (128, 128, 128))
    draw = ImageDraw.Draw(canvas)
    for i, (label, im) in enumerate(tiles):
        x, y = (i % cols) * (width + 12), (i // cols) * cell_h
        draw.rectangle([x, y, x + width, y + 26], fill=(20, 20, 20))
        draw.text((x + 8, y + 7), label, fill=(255, 255, 255))
        canvas.paste(im, (x, y + 28))
    canvas.save(target)


def main() -> int:
    if hasattr(sys.stdout, "reconfigure"):  # (Windows consoles default to a code page without ✅ “ ” →)
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("out")
    ap.add_argument("--pages", default=DEFAULT_PAGES)
    ap.add_argument("--themes", default="dark,light")
    ap.add_argument("--langs", default="en,de")
    ap.add_argument("--size", default="1480x920")
    ap.add_argument("--small", action="store_true", help="also the smallest window size")
    ap.add_argument("--job", action="append", default=[], help="a finished job folder to show (see tools/screenshots)")
    ap.add_argument("--queue", action="append", default=[], help="IMAGE[:METHOD] waiting in the queue")
    ap.add_argument("--set", action="append", default=[], help="app setting KEY=VALUE")
    ap.add_argument("--demo", action="store_true", help="show demo results and a queue (placeholder sketches)")
    args = ap.parse_args()
    out = Path(args.out)
    jobs, waiting = list(args.job), list(args.queue)
    if args.demo:
        demo, demo_queue = demo_jobs()
        jobs, waiting = jobs or demo, waiting or demo_queue
    extra = ([a for j in jobs for a in ("--job", j)] + [a for q in waiting for a in ("--queue", q)]
             + [a for s in args.set for a in ("--set", s)])
    sizes = [("", args.size)] + ([("small", f"{min_width()}x760")] if args.small else [])
    variants = []
    ok = True
    for tag, size in sizes:
        for theme in args.themes.split(","):
            for lang in args.langs.split(","):
                folder = out / tag if tag else out
                ok &= run(folder, theme, lang, args.pages, size, extra)
                variants.append((f"{theme} · {lang}{' · ' + size if tag else ''}", folder, theme, lang))
    for page in args.pages.split(","):
        name = page.replace(":", "_")
        files = [(label, folder / f"{name}_{theme}_{lang}.png") for label, folder, theme, lang in variants]
        sheet(files, out / f"sheet_{name}.png")
    print(f"screenshots in {out}:")
    for path in sorted(out.rglob("*.png")):
        print(" ", path.relative_to(out))
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
