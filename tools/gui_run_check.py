"""Drive a real run through the GUI (offscreen) and take screenshots while it runs.

Usage: python tools/gui_run_check.py OUT_DIR [--method clipasso|swiftsketch|controlsketch] [--models DIR]

``--models`` links an existing folder of downloaded models (e.g. the SwiftSketch weights) into
the temporary user data folder of the check.
"""

from __future__ import annotations

import os
import sys
import tempfile
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))


def main() -> int:
    import argparse

    ap = argparse.ArgumentParser()
    ap.add_argument("out")
    ap.add_argument("--method", default="clipasso")
    ap.add_argument("--models", default="")
    args = ap.parse_args()
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    tmp = tempfile.mkdtemp()
    os.environ["XDG_DATA_HOME"] = tmp
    os.environ["LOCALAPPDATA"] = tmp
    if args.models:
        from clipasso_studio import paths as _paths

        target = _paths.user_data_dir() / "models"
        if target.exists():
            target.rmdir()
        os.symlink(os.path.abspath(args.models), target)

    from PySide6.QtCore import QTimer
    from PySide6.QtWidgets import QApplication, QMessageBox

    from clipasso_studio import paths
    from clipasso_studio.gui import theme
    from clipasso_studio.gui.app_settings import app_settings

    app = QApplication(sys.argv)
    app_settings().data["output_dir"] = str(Path(tmp) / "results")
    theme.load_fonts()
    theme.apply(app, "dark")
    from clipasso_studio.gui.main_window import MainWindow

    QMessageBox.question = staticmethod(lambda *a, **k: QMessageBox.Yes)
    w = MainWindow()
    w.resize(1440, 900)
    w.show()
    studio = w.studio
    studio.set_image(str(paths.resource("samples", "horse.png")))
    studio.params.set_method(args.method)
    s = studio.params.settings()
    if args.method == "clipasso":
        s.update({"num_iter": 40, "num_sketches": 2, "num_paths": 12, "mask_object": True, "save_interval": 2,
                  "eval_interval": 2})
    elif args.method == "swiftsketch":
        s.update({"num_sketches": 3})
    else:
        s.update({"num_iter": 4, "save_interval": 2, "caption": "a horse", "condition": "canny"})
    studio.params.set_settings(s)
    state = {"shots": 0, "events": set(), "finished": None}

    w.controller.job_event.connect(lambda job, kind, data: state["events"].add(kind))

    def finished(job):
        state["finished"] = job.status
        QTimer.singleShot(800, lambda: (w.grab().save(str(out / "run_done.png")), app.quit()))

    w.controller.job_finished.connect(finished)

    def mid_shot():
        if state["finished"] is None:
            w.grab().save(str(out / f"run_live_{state['shots']}.png"))
            state["shots"] += 1
            if state["shots"] < 3:
                QTimer.singleShot(20000, mid_shot)

    def start():
        studio.start()
        QTimer.singleShot(30000 if args.method == "clipasso" else 12000, mid_shot)

    QTimer.singleShot(500, start)
    QTimer.singleShot(1800 * 1000, app.quit)
    app.exec()
    print("status:", state["finished"], "events:", sorted(state["events"]))
    return 0 if state["finished"] == "done" else 1


if __name__ == "__main__":
    raise SystemExit(main())
