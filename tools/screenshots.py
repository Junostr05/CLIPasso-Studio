"""Render screenshots of every page (offscreen) – used for the README and to review the UI.

Usage: python tools/screenshots.py OUT_DIR [--job JOB_DIR] [--theme dark|light] [--lang de|en]
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
    ap.add_argument("--job", default="")
    ap.add_argument("--theme", default="dark")
    ap.add_argument("--lang", default="de")
    ap.add_argument("--pages", default="studio,queue,gallery,models,settings,about")
    ap.add_argument("--size", default="1480x920")
    args = ap.parse_args()

    # isolated user data so the real settings are untouched
    os.environ["XDG_DATA_HOME"] = tempfile.mkdtemp()
    os.environ["LOCALAPPDATA"] = os.environ["XDG_DATA_HOME"]

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
        s.data["output_dir"] = str(Path(args.job).parent)
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

    def shoot(i=0):
        if i >= len(pages):
            app.quit()
            return
        page = pages[i]
        w.show_page(page)
        if page == "studio" and args.job:
            w.studio.show_job_dir(args.job)
            w.studio.modes.set_current("sketch")
        if page == "studio":
            w.studio.params.expand_all(False)
            w.studio.params.sections["basics"].set_expanded(True)
            w.studio.params.sections["image"].set_expanded(True)
            w.studio.params.sections["init"].set_expanded(True)

        def grab():
            app.processEvents()
            w.grab().save(str(out / f"{page}_{args.theme}_{args.lang}.png"))
            shoot(i + 1)

        QTimer.singleShot(400, grab)

    QTimer.singleShot(300, shoot)
    app.exec()
    print("screenshots in", out)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
