""""Continue with CLIPasso" (the studio's ContinueDialog): a new CLIPasso job that starts from a finished sketch –
its strokes are optimised further (the ones drawn by hand stay where they are, if wished) and new strokes can be
added. Without Qt: the studio and the Mac app's engine (op ``continue_sketch``) prepare the job the same way."""

from __future__ import annotations

import os
import shutil
import time

from ..engine import jobs

NEW_STROKES = 4  # the dialog's start values
ITERATIONS = 501


def can_continue(run_dir: str) -> bool:
    """The sketch's input (the picture as its method used it) is there: the strokes line up with it."""
    return bool(run_dir) and os.path.isfile(os.path.join(run_dir, "input.png"))


def prepare(run_dir: str, svg: str, new: int, iterations: int, keep: bool, clipasso: dict,
            output_dir: str) -> tuple[str, dict]:
    """(image, settings) of a CLIPasso job that continues ``svg``, the sketch of ``run_dir``: in a folder of its own
    under ``output_dir``/_continued, the run's input.png as the image (masked, framed, padded as the sketch's method
    used it, so the strokes line up without further steps) and the sketch as its start; ``clipasso``: the studio's
    CLIPasso settings."""
    from . import strokes

    state = jobs.read_state(os.path.dirname(os.path.normpath(run_dir))) or {}
    stem = os.path.splitext(os.path.basename(state.get("target") or ""))[0] or "sketch"
    base = os.path.join(output_dir, "_continued", time.strftime("%Y%m%d-%H%M%S"))
    folder, n = base, 1
    while os.path.exists(folder):
        n += 1
        folder = f"{base}-{n}"
    os.makedirs(folder)
    image = os.path.join(folder, f"{stem}.png")
    shutil.copyfile(os.path.join(run_dir, "input.png"), image)
    start = os.path.join(folder, f"{stem}-start.svg")
    with open(start, "w", encoding="utf-8") as f:
        f.write(svg if keep else strokes.unfix(svg))
    settings = dict(clipasso)
    settings.update(method="clipasso", path_svg=start, num_paths=strokes.shape_count(svg) + int(new),
                    num_iter=int(iterations), num_sketches=1, num_stages=1, mask_object=False,
                    frame_object=False, fix_scale=False, multiprocess=False)
    return image, settings
