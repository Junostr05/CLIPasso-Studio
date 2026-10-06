"""Job bookkeeping shared by the worker processes and the GUI (no torch import)."""

from __future__ import annotations

import json
import os
import shutil
import time
from dataclasses import dataclass
from pathlib import Path

from .. import settings_schema as schema


class _NullReporter:
    def event(self, kind, **data):
        pass


@dataclass
class SeedResult:
    seed: int
    run_name: str
    run_dir: str
    best_loss: float
    best_iter: int
    iterations_done: int
    best_svg: str
    status: str  # done | cancelled
    method: str = "clipasso"
    clip_score: float | None = None  # CLIP ViT-B/32 similarity sketch <-> input in percent (higher = better)
    seconds: float = 0.0
    pruned: bool = False  # turbo mode: stopped early because another seed of the job was better


def job_seeds(settings: dict) -> list[int]:
    """Items of a job: seeds like run_object_sketching.py (0, 1000, 2000, ... offset by ``seed``);
    for SceneSketch the cells of the abstraction matrix (``layer * 100 + level``)."""
    if schema.method_of(settings) == "scenesketch":
        return schema.scene_cells(settings)
    base = int(settings.get("seed", 0))
    return [base + i * 1000 for i in range(int(settings.get("num_sketches", 1)))]


def run_name_for(target: str, settings: dict, seed: int) -> str:
    """Run folder name; CLIPasso keeps the original naming (<name>_<N>strokes_seed<S>)."""
    test_name = os.path.splitext(os.path.basename(target))[0]
    method = schema.method_of(settings)
    if method == "scenesketch":
        return schema.scene_run_name(target, seed // 100, seed % 100)
    prefix = test_name if method == "clipasso" else f"{test_name}_{method}"
    return f"{prefix}_{schema.num_strokes(settings)}strokes_seed{seed}"


def make_job_dir(output_root: str, target: str, method: str = "clipasso") -> str:
    test_name = os.path.splitext(os.path.basename(target))[0]
    if method != "clipasso":
        test_name = f"{test_name}_{method}"
    stamp = time.strftime("%Y%m%d-%H%M%S")
    path = Path(output_root) / f"{test_name}_{stamp}"
    n = 1
    while path.exists():
        n += 1
        path = Path(output_root) / f"{test_name}_{stamp}-{n}"
    path.mkdir(parents=True)
    save_input(str(path), target)
    return str(path)


INPUT_DIR = "input"


def save_input(job_dir: str, target: str) -> str | None:
    """Copy the input image into the job folder (``input/<file name>``) when the job starts, so the
    job can be reopened and continued even after the original file was moved or deleted."""
    dest = os.path.join(job_dir, INPUT_DIR, os.path.basename(target))
    if os.path.isfile(dest):
        return dest
    try:
        os.makedirs(os.path.dirname(dest), exist_ok=True)
        shutil.copyfile(target, dest)
    except OSError:
        return None
    save_edited_mask(job_dir, target)
    from .details import save_with_job

    save_with_job(job_dir, target)  # the detail brush map, too
    return dest


INIT_SVG = "init.svg"  # the start sketch of a job (path_svg), kept in its input folder


def save_init_svg(job_dir: str, path_svg: str) -> str:
    """Copy the start sketch (``path_svg``) into the job folder and return the copy, so the job can be
    continued even after the original was changed or deleted (the copy is never replaced)."""
    dest = os.path.join(job_dir, INPUT_DIR, INIT_SVG)
    if os.path.isfile(dest) or not os.path.isfile(path_svg):
        return dest if os.path.isfile(dest) else path_svg
    os.makedirs(os.path.dirname(dest), exist_ok=True)
    shutil.copyfile(path_svg, dest)
    return dest


EDITED_MASK_FILE = "mask-edited.png"  # the user's mask of the input, kept with the job


def save_edited_mask(job_dir: str, target: str) -> bool:
    """Copy the mask the user edited for this input into the job folder (it is found again by the
    image content, so this copy is the record – and restores the edit if the app data is lost)."""
    from . import masking
    from .imaging import load_rgb

    try:
        src = masking.edited_mask_path(load_rgb(target))
        if src.is_file():
            shutil.copyfile(src, os.path.join(job_dir, EDITED_MASK_FILE))
            return True
    except OSError:
        pass
    return False


def restore_edited_mask(job_dir: str, image_path: str) -> bool:
    """When a job is reopened: bring its edited mask back if the app data no longer has it."""
    from . import masking
    from .imaging import load_rgb

    saved = os.path.join(job_dir, EDITED_MASK_FILE)
    if not os.path.isfile(saved):
        return False
    try:
        dest = masking.edited_mask_path(load_rgb(image_path))
        if not dest.is_file():
            dest.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(saved, dest)
        return True
    except OSError:
        return False


def saved_input(job_dir: str, target: str = "") -> str | None:
    """The copy of the input image in a job folder – ``input/<name>``, or ``source.<ext>`` of
    CLIPasso Studio 2.1 and older."""
    folder = os.path.join(job_dir, INPUT_DIR)
    if os.path.isdir(folder):
        files = sorted(f for f in os.listdir(folder) if f != INIT_SVG)
        name = os.path.basename(target)
        if name in files:
            return os.path.join(folder, name)
        if files:
            return os.path.join(folder, files[0])
    if os.path.isdir(job_dir):
        old = next((f for f in sorted(os.listdir(job_dir)) if f.startswith("source.")), None)
        if old:
            return os.path.join(job_dir, old)
    return None


def reopen_input(job_dir: str, target: str) -> str | None:
    """The image to continue a job with: the original while it exists, otherwise the saved copy.
    An old ``source.<ext>`` copy is copied to ``input/<original name>`` first, so that new runs from it
    are named after the image and not "source"."""
    if target and os.path.isfile(target):
        return target
    copy = saved_input(job_dir, target)
    if copy and os.path.basename(copy).startswith("source.") and target:
        name = os.path.splitext(os.path.basename(target))[0] + os.path.splitext(copy)[1]
        dest = os.path.join(job_dir, INPUT_DIR, name)
        try:
            os.makedirs(os.path.dirname(dest), exist_ok=True)
            shutil.copyfile(copy, dest)
            return dest
        except OSError:
            return copy
    return copy


STATE_FILE = "job_state.json"
RESULT_FILE = "result.json"


def write_state(job_dir: str, target: str, settings: dict, status: str = "running") -> None:
    """``job_state.json``: what the job is meant to compute and whether it is still running – a job
    whose state says "running" although nothing runs it was interrupted (app closed, crash)."""
    path = os.path.join(job_dir, STATE_FILE)
    state = read_state(job_dir) or {"created": time.strftime("%Y-%m-%d %H:%M:%S")}
    state.update({"target": os.path.abspath(target), "settings": schema.normalize(settings),
                  "method": schema.method_of(settings), "seeds": job_seeds(settings), "status": status})
    if status == "running":
        state.pop("asked", None)  # a new run that is interrupted again is offered again
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(state, f, indent=2)
    os.replace(tmp, path)


def rebase(path: str, job_dir: str) -> str:
    """A path saved inside a job folder, for where that folder is now: the files keep absolute paths,
    and the output folder may have been moved (in the settings, or by hand)."""
    if not path or os.path.exists(path):
        return path
    parts = [p for p in path.replace("\\", "/").split("/") if p]
    name = os.path.basename(os.path.normpath(job_dir))
    if name not in parts:
        return path
    i = len(parts) - 1 - parts[::-1].index(name)
    return os.path.join(job_dir, *parts[i + 1:])


def _rebase_run(run: dict, job_dir: str) -> dict:
    for key in ("run_dir", "best_svg"):
        if isinstance(run.get(key), str):
            run[key] = rebase(run[key], job_dir)
    return run


def read_state(job_dir: str) -> dict | None:
    try:
        with open(os.path.join(job_dir, STATE_FILE), encoding="utf-8") as f:
            state = json.load(f)
    except (OSError, ValueError):
        return None
    if not isinstance(state, dict):
        return None
    if isinstance(state.get("settings"), dict):
        state["settings"].setdefault("mask_model", "u2net")  # jobs from before 2.4 were masked with U2Net
        state["settings"].setdefault("frame_object", False)  # ... and not framed
        if isinstance(state["settings"].get("path_svg"), str):  # input/init.svg of the job
            state["settings"]["path_svg"] = rebase(state["settings"]["path_svg"], job_dir)
    return state


def set_status(job_dir: str, status: str) -> None:
    state = read_state(job_dir)
    if state is not None and state.get("status") != status:
        write_state(job_dir, state["target"], state["settings"], status)


def mark_asked(job_dir: str) -> None:
    """The user was asked at the start whether to continue this interrupted job (only asked once)."""
    state = read_state(job_dir)
    if state is None:
        return
    state["asked"] = True
    if state.get("status") == "running":
        state["status"] = "interrupted"
    path = os.path.join(job_dir, STATE_FILE)
    with open(path + ".tmp", "w", encoding="utf-8") as f:
        json.dump(state, f, indent=2)
    os.replace(path + ".tmp", path)


def save_result(result: SeedResult) -> None:
    """``result.json`` in the run folder: the seed is finished (or was cancelled)."""
    if not result.run_dir or not os.path.isdir(result.run_dir):
        return
    with open(os.path.join(result.run_dir, RESULT_FILE), "w", encoding="utf-8") as f:
        json.dump(result.__dict__, f, indent=2)


def saved_results(job_dir: str) -> dict[int, SeedResult]:
    """The results saved in a job folder, by seed (cell for SceneSketch)."""
    out = {}
    if not os.path.isdir(job_dir):
        return out
    for name in sorted(os.listdir(job_dir)):
        path = os.path.join(job_dir, name, RESULT_FILE)
        try:
            with open(path, encoding="utf-8") as f:
                result = SeedResult(**_rebase_run(json.load(f), job_dir))
        except (OSError, ValueError, TypeError, AttributeError):
            continue
        if os.path.isfile(result.best_svg):
            out[int(result.seed)] = result
    return out


def done_results(job_dir: str) -> dict[int, SeedResult]:
    return {s: r for s, r in saved_results(job_dir).items() if r.status == "done"}


def progress_of(job_dir: str) -> tuple[int, int]:
    """(finished items, all items) of a job."""
    state = read_state(job_dir)
    seeds = state.get("seeds", []) if state else []
    done = done_results(job_dir)
    return sum(1 for s in seeds if s in done), len(seeds)


def remaining_seeds(job_dir: str) -> list[int]:
    state = read_state(job_dir) or {}
    done = done_results(job_dir)
    return [s for s in state.get("seeds", []) if s not in done]


CHECKPOINT_FILE = "checkpoint.pt"  # (engine/checkpoint.py, without importing torch here)
CELL_SEEDS_FILE = "cell_seeds.json"  # SceneSketch cells computed again: their new start values


def read_cell_seeds(job_dir: str) -> dict[str, int]:
    try:
        with open(os.path.join(job_dir, CELL_SEEDS_FILE), encoding="utf-8") as f:
            data = json.load(f)
        return {str(k): int(v) for k, v in data.items()}
    except (OSError, ValueError, TypeError, AttributeError):
        return {}


def rerun_scene_cell(job_dir: str, cell: int) -> list[int]:
    """Prepare a cell of a SceneSketch job to be computed again with a new start value: the cell and the later levels
    of its layer (each starts from the one before it) are removed – continuing the job computes them again. Returns
    the cells removed."""
    state = read_state(job_dir) or {}
    settings, target = state.get("settings") or {}, state.get("target") or ""
    layer, level = divmod(int(cell), 100)
    seeds = read_cell_seeds(job_dir)
    seeds[str(cell)] = seeds.get(str(cell), int(settings.get("seed", 0))) + 1
    with open(os.path.join(job_dir, CELL_SEEDS_FILE), "w", encoding="utf-8") as f:
        json.dump(seeds, f, indent=1)
    removed = []
    for lv in schema.scene_levels(settings):
        if lv < level:
            continue
        shutil.rmtree(os.path.join(job_dir, schema.scene_run_name(target, layer, lv)), ignore_errors=True)
        for part in ("background", "object"):
            shutil.rmtree(os.path.join(job_dir, "runs", f"{part}_l{layer}" + (f"_level{lv}" if lv else "")),
                          ignore_errors=True)
        removed.append(schema.scene_cell_id(layer, lv))
    return removed


def drop_checkpoints(job_dir: str) -> int:
    """Remove the checkpoints of the unfinished sketches of a job (they start again, e.g. with other
    settings); finished sketches stay. Returns how many were removed."""
    done = {os.path.normcase(os.path.abspath(r.run_dir)) for r in done_results(job_dir).values()}
    removed = 0
    for current, _dirs, files in os.walk(job_dir):
        if CHECKPOINT_FILE in files and os.path.normcase(os.path.abspath(current)) not in done:
            try:
                os.remove(os.path.join(current, CHECKPOINT_FILE))
                removed += 1
            except OSError:
                pass
    return removed


def can_continue(job_dir: str) -> bool:
    """Interrupted, cancelled or failed with work left."""
    state = read_state(job_dir)
    return bool(state) and state.get("status") in ("running", "interrupted", "cancelled", "failed") \
        and bool(remaining_seeds(job_dir))


def merge_results(old: dict[int, SeedResult], new: list[SeedResult]) -> list[SeedResult]:
    """Old results completed by the new ones (a seed computed again replaces its old result)."""
    merged = dict(old)
    for r in new:
        if r is not None:
            merged[int(r.seed)] = r
    return [merged[s] for s in sorted(merged)]


META_FILE = "meta.json"  # the user's own data about a job (favourite, name, notes, tags) – kept on continue
META_KEYS = ("favourite", "title", "notes", "tags", "albums", "ratings")  # ratings: {run name: ±1}


def read_meta(job_dir: str) -> dict:
    try:
        with open(os.path.join(job_dir, META_FILE), encoding="utf-8") as f:
            meta = json.load(f)
    except (OSError, ValueError):
        return {}
    return {k: v for k, v in meta.items() if k in META_KEYS} if isinstance(meta, dict) else {}


def write_meta(job_dir: str, **changes) -> dict:
    """Change the user's data of a job (a value of None removes it); returns all of it."""
    meta = read_meta(job_dir)
    for key, value in changes.items():
        if key not in META_KEYS:
            raise KeyError(key)
        if value is None:
            meta.pop(key, None)
        else:
            meta[key] = value
    path = os.path.join(job_dir, META_FILE)
    with open(path + ".tmp", "w", encoding="utf-8") as f:
        json.dump(meta, f, indent=2, ensure_ascii=False)
    os.replace(path + ".tmp", path)
    return meta


def job_summary(job_dir: str) -> dict | None:
    """``job.json`` of a job – or, for a job interrupted before it was finished, the same information
    built from its state and the sketches finished so far. Adds ``state`` (running / interrupted /
    cancelled / failed / done) and ``progress`` ([finished, all])."""
    summary = None
    try:
        with open(os.path.join(job_dir, "job.json"), encoding="utf-8") as f:
            summary = json.load(f)
    except (OSError, ValueError):
        pass
    state = read_state(job_dir)
    if summary is None:
        if state is None:
            return None
        results = list(saved_results(job_dir).values())
        method = state.get("method") or schema.method_of(state.get("settings"))
        best = None
        if results:
            results = [r for r in results if not r.pruned] or results
            scored = [r for r in results if r.clip_score is not None]
            best = max(scored, key=lambda r: r.clip_score) if method != "clipasso" and scored \
                else min(results, key=lambda r: r.best_loss)
        summary = {"target": state.get("target", ""), "created": state.get("created", ""),
                   "settings": state.get("settings", {}), "method": method,
                   "clip_score": best.clip_score if best else None, "best_svg": best.best_svg if best else "",
                   "best_run": best.run_name if best else "", "runs": [r.__dict__ for r in results]}
    summary["best_svg"] = rebase(summary.get("best_svg") or "", job_dir)
    for run in summary.get("runs") or []:
        if isinstance(run, dict):
            _rebase_run(run, job_dir)
    if state is not None:
        summary["state"] = state.get("status", "done")
        done, total = progress_of(job_dir)
        summary["progress"] = [done, total]
    summary.update(read_meta(job_dir))  # (a favourite of version 2.x is still in job.json)
    return summary


def summary_can_continue(summary: dict) -> bool:
    """For a :func:`job_summary`: interrupted / cancelled / failed with work left."""
    done, total = summary.get("progress") or (0, 0)
    return summary.get("state") in ("running", "interrupted", "cancelled", "failed") and done < total


EDITED_FILE = "edited.svg"  # a sketch touched up with the eraser of the studio (the original stays)


def sketch_file(run_dir: str, original: str = "") -> str:
    """The sketch of a run as it should be shown and exported: the edited one if there is one."""
    edited = os.path.join(run_dir, EDITED_FILE) if run_dir else ""
    if edited and os.path.isfile(edited):
        return edited
    return original or os.path.join(run_dir, "best_iter.svg")


def best_sketch(summary: dict) -> str:
    """The best sketch of a job summary, edited if it was touched up."""
    for r in summary.get("runs", []):
        if r.get("run_name") == summary.get("best_run") and r.get("run_dir"):
            edited = os.path.join(r["run_dir"], EDITED_FILE)
            if os.path.isfile(edited):
                return edited
    return summary.get("best_svg", "")


def set_best_run(job_dir: str, run_name: str) -> bool:
    """Make another sketch of a finished job its result (chosen by hand in the studio): ``job.json`` and the
    ``<run>_best.svg/.png`` copies, as :func:`finish_job` writes them."""
    path = os.path.join(job_dir, "job.json")
    try:
        with open(path, encoding="utf-8") as f:
            summary = json.load(f)
    except (OSError, ValueError):
        return False
    run = next((r for r in summary.get("runs", []) if r.get("run_name") == run_name), None)
    if run is None:
        return False
    run_dir = run.get("run_dir") or ""
    if not os.path.isdir(run_dir):  # (the job folder moved since)
        run_dir = os.path.join(job_dir, run_name)
    src = run.get("best_svg") or ""
    if not os.path.isfile(src):
        src = os.path.join(run_dir, "best_iter.svg")
    if not os.path.isfile(src):
        return False
    for name in os.listdir(job_dir):
        if name.endswith(("_best.svg", "_best.png")):
            try:
                os.remove(os.path.join(job_dir, name))
            except OSError:
                pass
    best_copy = os.path.join(job_dir, f"{run_name}_best.svg")
    shutil.copyfile(src, best_copy)
    png = os.path.join(run_dir, "best_iter.png")
    if os.path.isfile(png):
        shutil.copyfile(png, os.path.join(job_dir, f"{run_name}_best.png"))
    summary.update(best_run=run_name, best_svg=best_copy, clip_score=run.get("clip_score"), best_by="chosen")
    with open(path, "w", encoding="utf-8") as f:
        json.dump(summary, f, indent=2)
    return True


def finish_job(job_dir: str, target: str, settings: dict, results: list[SeedResult],
               reporter=None) -> dict:
    """Pick the best sketch and copy it to ``<run>_best.svg`` like the original.

    CLIPasso keeps its own criterion (lowest eval loss). SwiftSketch and ControlSketch have
    no such loss, so the sketch with the highest CLIP similarity to the input wins. With ``best_by``
    "beautiful" or "mine" the sketch's look counts as much (``engine/aesthetic.py``).
    """
    from . import aesthetic

    reporter = reporter or _NullReporter()
    results = [r for r in results if r is not None and os.path.isfile(r.best_svg)]
    if not results:
        raise RuntimeError("no sketch was produced")
    method = schema.method_of(settings)
    candidates = [r for r in results if not r.pruned] or results  # (turbo) the sketch that was continued
    if method != "clipasso" and all(r.clip_score is not None for r in candidates):
        fidelity = [r.clip_score for r in candidates]
    else:
        fidelity = [-r.best_loss for r in candidates]
    embs = {r.run_name: aesthetic.read_embedding(r.run_dir, r.best_svg) for r in results}
    mode = settings.get("best_by", "faithful")
    model = (aesthetic.load_taste().get("model") or None) if mode == "mine" else None
    best = candidates[aesthetic.choose(fidelity, [embs[r.run_name] for r in candidates], mode, model,
                                       [r.clip_score for r in candidates])]
    best_copy = os.path.join(job_dir, f"{best.run_name}_best.svg")
    for name in os.listdir(job_dir):  # a continued job may have another best sketch than before
        if name.endswith(("_best.svg", "_best.png")) and not name.startswith(f"{best.run_name}_best."):
            try:
                os.remove(os.path.join(job_dir, name))
            except OSError:
                pass
    shutil.copyfile(best.best_svg, best_copy)
    png = os.path.join(best.run_dir, "best_iter.png")
    if os.path.isfile(png):
        shutil.copyfile(png, os.path.join(job_dir, f"{best.run_name}_best.png"))
    save_input(job_dir, target)  # normally already done when the job folder was created
    summary = {
        "target": os.path.abspath(target),
        "created": time.strftime("%Y-%m-%d %H:%M:%S"),
        "settings": schema.normalize(settings),
        "method": method,
        "clip_score": best.clip_score,
        "seconds": round(sum(r.seconds for r in results), 1),
        "best_svg": best_copy,
        "best_run": best.run_name,
        "best_by": mode,
        "runs": [dict(r.__dict__, aesthetic=round(aesthetic.beauty(embs[r.run_name]), 3))
                 if embs[r.run_name] is not None else r.__dict__ for r in results],
    }
    with open(os.path.join(job_dir, "job.json"), "w", encoding="utf-8") as f:
        json.dump(summary, f, indent=2)
    if read_state(job_dir) is not None:
        all_done = all(r.status == "done" for r in results) and not remaining_seeds(job_dir)
        set_status(job_dir, "done" if all_done else "cancelled")
    reporter.event("job_done", job_dir=job_dir, best_svg=best_copy, best_run=best.run_name, method=method,
                   clip_score=best.clip_score, runs=summary["runs"])
    return summary
