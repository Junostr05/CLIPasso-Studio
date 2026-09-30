"""Render screenshots of every page (offscreen) – used for the README and to review the UI.

Usage: python tools/screenshots.py OUT_DIR [--job JOB_DIR ...] [--theme dark|light] [--lang de|en]
                                   [--pages studio,studio:swiftsketch,compare,...]

``studio:<method>`` shows the studio with that method selected (and the given job of that method,
if any). All jobs must be in the same output folder, which the gallery / compare pages then show.
"""

from __future__ import annotations

import argparse
import os
import sys
import tempfile
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("out")
    ap.add_argument("--job", action="append", default=[])
    ap.add_argument("--theme", default="dark")
    ap.add_argument("--lang", default="de")
    ap.add_argument("--pages", default="studio,compare,queue,gallery,models,settings,about")
    ap.add_argument("--size", default="1480x920")
    ap.add_argument("--models", default="", help="folder of downloaded models to show as installed")
    args = ap.parse_args()

    # isolated user data so the real settings are untouched
    os.environ["XDG_DATA_HOME"] = tempfile.mkdtemp()
    os.environ["LOCALAPPDATA"] = os.environ["XDG_DATA_HOME"]
    if args.models:
        from clipasso_studio import paths as _paths

        target = _paths.user_data_dir() / "models"
        if target.exists():
            target.rmdir()
        os.symlink(os.path.abspath(args.models), target)

    from PySide6.QtCore import QTimer
    from PySide6.QtWidgets import QApplication

    from clipasso_studio.gui import theme
    from clipasso_studio.gui.app_settings import app_settings
    from clipasso_studio.gui.i18n import i18n

    app = QApplication(sys.argv)
    s = app_settings()
    s.data["theme"] = args.theme
    s.data["language"] = args.lang
    if args.job:
        s.data["output_dir"] = str(Path(args.job[0]).parent)
    theme.load_fonts()
    theme.apply(app, args.theme)
    i18n.set_language(args.lang)

    from clipasso_studio.gui.main_window import MainWindow

    w = MainWindow()
    width, height = (int(v) for v in args.size.split("x"))
    w.resize(width, height)
    w.show()
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    pages = args.pages.split(",")

    import json

    jobs = {}
    for j in args.job:
        with open(Path(j) / "job.json", encoding="utf-8") as f:
            summary = json.load(f)
        jobs[summary.get("method", "clipasso")] = j

    def shoot(i=0):
        if i >= len(pages):
            app.quit()
            return
        page, _, method = pages[i].partition(":")
        name = pages[i].replace(":", "_")
        w.show_page(page)
        if page == "studio":
            method = method or "clipasso"
            if method in jobs:
                w.studio.show_job_dir(jobs[method])
                w.studio.image_path = w.studio.image_path  # keep the job's image for the compare page
            else:
                w.studio.params.set_method(method)
            w.studio.modes.set_current("sketch")
            w.studio.params.expand_all(False)
            for sec in ("basics", "image", "init", "diffusion", "sds"):
                if sec in w.studio.params.sections and (sec != "sds" or method == "controlsketch"):
                    w.studio.params.sections[sec].set_expanded(sec in ("basics", "image", "init", "diffusion"))

        def grab():
            app.processEvents()
            w.grab().save(str(out / f"{name}_{args.theme}_{args.lang}.png"))
            shoot(i + 1)

        QTimer.singleShot(400, grab)

    QTimer.singleShot(300, shoot)
    app.exec()
    print("screenshots in", out)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
