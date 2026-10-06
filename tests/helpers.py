"""Helpers shared by the GUI tests."""

import time


def wait_until(app, condition, timeout: float = 10.0, step: float = 0.01):
    """Run the event loop until ``condition()`` is true (AssertionError after ``timeout`` seconds)."""
    end = time.time() + timeout
    while not condition():
        if time.time() > end:
            raise AssertionError("timed out")
        app.processEvents()
        time.sleep(step)


def fake_job(out, name, target, clip, method="swiftsketch", created="2026-09-29 12:00:00"):
    """A finished job folder as the app writes it (one run, a simple sketch) – for the gallery, the studio, the
    phone."""
    import json
    import os

    from PIL import Image

    from clipasso_studio import settings_schema as schema
    from clipasso_studio.engine import jobs

    job = os.path.join(out, name)
    run = os.path.join(job, f"{name}_run")
    os.makedirs(os.path.join(run, "svg_logs"))
    svg = '<svg xmlns="http://www.w3.org/2000/svg" width="224" height="224"><path d="M 10 10 C 20 20 30 30 40 40" ' \
          'stroke="rgb(0,0,0)" stroke-width="2" fill="none"/></svg>'
    for p in (os.path.join(run, "best_iter.svg"), os.path.join(job, f"{name}_run_best.svg")):
        with open(p, "w") as f:
            f.write(svg)
    if not os.path.isfile(target):
        Image.new("RGB", (30, 20), "white").save(target)
    jobs.save_input(job, target)
    summary = {"target": target, "created": created, "settings": schema.default_settings(method), "method": method,
               "clip_score": clip, "best_svg": os.path.join(job, f"{name}_run_best.svg"), "best_run": f"{name}_run",
               "runs": [{"seed": 0, "run_name": f"{name}_run", "run_dir": run, "best_loss": 0.2, "best_iter": 0,
                         "iterations_done": 1, "best_svg": os.path.join(run, "best_iter.svg"), "status": "done",
                         "method": method, "clip_score": clip, "seconds": 1.0}]}
    with open(os.path.join(job, "job.json"), "w") as f:
        json.dump(summary, f)
    return job


SCENE_BG = ['M 10 10 C 30 20 50 20 70 10', 'M 10 200 C 60 180 120 180 210 200']
SCENE_OBJ = ['M 90 90 C 100 120 120 120 130 90', 'M 95 140 C 110 150 120 150 130 140']


def _svg(ds) -> str:
    return ('<svg xmlns="http://www.w3.org/2000/svg" width="224" height="224" viewBox="0 0 224 224">'
            + "".join(f'<path d="{d}" stroke="rgb(0,0,0)" stroke-width="1.5" fill="none"/>' for d in ds) + "</svg>")


def fake_scene_job(out, name, target, levels: int = 1):
    """A finished SceneSketch job as the engine writes it: layer 8 with ``levels`` + 1 cells (background and object
    strokes, their layer files), the LaMa background, the mask and the attention map in the background's run."""
    import json
    import os

    from PIL import Image

    from clipasso_studio import settings_schema as schema
    from clipasso_studio.engine import jobs

    job = os.path.join(out, name)
    os.makedirs(job)
    if not os.path.isfile(target):
        Image.new("RGB", (40, 30), "white").save(target)
    jobs.save_input(job, target)
    Image.new("RGB", (224, 224), (120, 160, 200)).save(os.path.join(job, "background.png"))
    Image.new("L", (224, 224), 0).save(os.path.join(job, "mask.png"))
    bg_run = os.path.join(job, "runs", "background_l8", "seed0")
    os.makedirs(bg_run)
    Image.new("RGB", (224, 224), "gray").save(os.path.join(bg_run, "attention_map.png"))
    settings = {**schema.default_settings("scenesketch"), "layers": "8", "simplicity_levels": levels}
    runs = []
    for level in range(levels + 1):
        cell = schema.scene_cell_id(8, level)
        run_name = schema.scene_run_name(target, 8, level)
        cell_dir = os.path.join(job, run_name)
        os.makedirs(os.path.join(cell_dir, "svg_logs"))
        hidden = ["M 100 100 L 110 110"]  # (a background stroke the object covers: cut away in the sketch)
        for file, ds in (("best_iter.svg", SCENE_BG + SCENE_OBJ), ("background.svg", SCENE_BG + hidden),
                         ("object.svg", SCENE_OBJ)):
            with open(os.path.join(cell_dir, file), "w", encoding="utf-8") as f:
                f.write(_svg(ds))
        with open(os.path.join(cell_dir, "config.json"), "w", encoding="utf-8") as f:
            json.dump({"method": "scenesketch", "layer": 8, "level": level, "cell": cell, "background_run": bg_run,
                       "object_strokes": len(SCENE_OBJ), "background_strokes": len(SCENE_BG)}, f)
        runs.append({"seed": cell, "run_name": run_name, "run_dir": cell_dir, "best_loss": 0.3, "best_iter": 0,
                     "iterations_done": 1, "best_svg": os.path.join(cell_dir, "best_iter.svg"), "status": "done",
                     "method": "scenesketch", "clip_score": 70.0 - level, "seconds": 1.0})
    summary = {"target": target, "created": "2026-10-05 12:00:00", "settings": settings, "method": "scenesketch",
               "clip_score": 70.0, "best_svg": runs[0]["best_svg"], "best_run": runs[0]["run_name"], "runs": runs}
    with open(os.path.join(job, "job.json"), "w", encoding="utf-8") as f:
        json.dump(summary, f)
    return job
