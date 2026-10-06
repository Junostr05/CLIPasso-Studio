"""Quality and speed benchmark: short fixed jobs of every method on the bundled samples, on the CPU.

Each case runs in its own process, so its peak memory is its own. The result – the CLIP score of every sketch,
the time, the peak memory – is compared with ``benchmarks/baseline.json``:

- a CLIP score lower by more than ``SCORE_FAIL`` points on average fails (exit code 1), by more than
  ``SCORE_WARN`` warns,
- a time longer by more than ``TIME_WARN`` (after scaling with a matrix-multiplication calibration of the
  computer, CI machines differ) or more memory than ``RSS_WARN`` warns.

The same code gives different sketches on different CPUs (tiny rounding differences grow over the optimisation:
measured 72.1 and 67.1 for the same SceneSketch run on two machines), hence the wide limit for a failure: it is
meant for real breakage (a broken loss or renderer costs far more), the warning for drifts worth a look.

A case whose models are not installed is skipped (``--fetch`` downloads them first).

**Categories and an independent judge** (``--suite METHOD``): every picture of ``benchmarks/images`` (portraits,
animals, scenes – NASA photos in the public domain) and the samples (objects, scenes), one sketch each, graded by
models that are in no optimisation of the app (``tools/judge.py``: CLIP ViT-L/14's similarity to the photo and how
recognisable the sketch is on its own) – so a change of the method cannot raise its own mark. Results per category,
a contact sheet per category; ``--set key=value`` changes a setting (a variant), ``--compare A.json B.json`` puts
two suites side by side: per picture, the mean difference and its standard error, and a verdict – a *clear gain*
only when the similarity rises by more than twice its standard error and the recognisability does not fall.
``--taste DIR`` also grades with "My taste" learnt in the app data folder ``DIR`` (locally – no thumbs in the CI).

Usage::

    python tools/benchmark.py [--cases clipasso,swiftsketch,scenesketch,controlsketch] [--out DIR]
                              [--fetch] [--baseline benchmarks/baseline.json] [--update-baseline]
                              [--summary FILE]
    python tools/benchmark.py --suite clipasso [--categories portrait,animal] [--quick] [--seeds 0,1]
                              [--set key=value ...] [--label NAME] [--taste APPDATA_DIR] [--out DIR] [--fetch]
    python tools/benchmark.py --compare A.json|DIR B.json|DIR [--summary FILE]

``.github/workflows/measure.yml`` runs the variants of ``benchmarks/variants.json`` in the CI (pushes whose message
contains [measure]): one job per variant and category, then every variant against "base".
"""

from __future__ import annotations

import argparse
import html
import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

BASELINE = ROOT / "benchmarks" / "baseline.json"
SCORE_FAIL = 5.0  # CLIP score points (mean over the sketches of a case)
SCORE_WARN = 2.0
TIME_WARN = 1.3  # x the (calibrated) time of the baseline
RSS_WARN = 1.2  # x the peak memory of the baseline

# (sample image, settings): short, but long enough that the score says something about the method
CASES: dict[str, tuple[str, dict]] = {
    "clipasso": ("camel.png", {"method": "clipasso", "num_iter": 151, "num_sketches": 2, "eval_interval": 50,
                               "save_interval": 50, "mask_model": "u2net", "multiprocess": False}),
    "swiftsketch": ("camel.png", {"method": "swiftsketch", "num_sketches": 4, "mask_model": "u2net"}),
    "scenesketch": ("ballerina.jpg", {"method": "scenesketch", "layers": "8", "simplicity_levels": 0,
                                      "num_sketches": 1, "num_iter": 151, "object_num_iter": 150,
                                      "min_eval_iter": 100, "eval_interval": 50, "save_interval": 50,
                                      "mask_model": "u2net"}),
    "controlsketch": ("camel.png", {"method": "controlsketch", "turbo": True, "num_iter": 30, "num_sketches": 2,
                                    "save_interval": 10, "condition": "depth", "caption": "a camel",
                                    "mask_model": "u2net"}),
}


# ---------------------------------------------------------------- categories (--suite)
IMAGES = ROOT / "benchmarks" / "images"
CATEGORIES = ("object", "portrait", "animal", "scene")
SAMPLE_IMAGES = (("object", "camel.png", "camel"), ("object", "flamingo.png", "flamingo"),
                 ("object", "horse.png", "horse"), ("object", "rose.jpeg", "rose"),
                 ("scene", "ballerina.jpg", "ballerina"), ("scene", "house.jpg", "house"))
# per method: the settings of a measurement – long enough that the sketches differ by more than chance
SUITES: dict[str, dict] = {
    "clipasso": {"method": "clipasso", "num_iter": 301, "num_sketches": 1, "eval_interval": 50,
                 "save_interval": 100, "mask_model": "u2net", "multiprocess": False},
}
QUICK = {"num_iter": 151}  # --quick (the CI): fewer iterations, one picture per category
SIMILARITY, RECOG = "clip_l14", "recog"


def suite_images(categories: list[str] | None = None, quick: bool = False) -> list[dict]:
    """The pictures of the suite: {category, name, path, label}, by category."""
    from clipasso_studio import paths

    items = [{"category": c, "name": os.path.splitext(f)[0], "path": str(paths.resource("samples", f)),
              "label": label} for c, f, label in SAMPLE_IMAGES]
    for src in json.loads((IMAGES / "sources.json").read_text(encoding="utf-8")):
        items.append({"category": src["category"], "name": Path(src["file"]).stem, "path": str(IMAGES / src["file"]),
                      "label": src["label"]})
    items = [it for it in items if not categories or it["category"] in categories]
    items.sort(key=lambda it: (CATEGORIES.index(it["category"]), it["name"]))
    if quick:
        seen: set = set()
        items = [it for it in items if not (it["category"] in seen or seen.add(it["category"]))]
    return items


def parse_value(text: str):
    """``--set`` values: JSON where it parses (numbers, true/false, lists), else the text."""
    try:
        return json.loads(text)
    except ValueError:
        return text


def load_taste_model(folder: str) -> dict | None:
    """"My taste" learnt in an app data folder (``taste.json`` somewhere below it)."""
    for path in sorted(Path(folder).rglob("taste.json")):
        try:
            model = json.loads(path.read_text(encoding="utf-8")).get("model")
        except (OSError, ValueError):
            continue
        if model:
            return model
    return None


def run_suite(method: str, overrides: dict, images: list[dict], out_dir: Path, seeds: list[int],
              taste_model: dict | None = None) -> dict:
    """One sketch per picture and seed, graded by the judges -> {"rows": [...], "categories": {...}, ...}."""
    sys.path.insert(0, str(ROOT / "tools"))
    from judge import Judge

    from clipasso_studio.engine import pipeline

    labels = sorted({it["label"] for it in suite_images()})
    judge = Judge(labels)
    scorer = None
    rows = []
    for it in images:
        for seed in seeds:
            settings = {**SUITES[method], **overrides, "seed": seed, "device": "cpu"}
            job_dir = out_dir / f"{it['category']}_{it['name']}_s{seed}"
            start = time.perf_counter()
            summary = pipeline.run_job(settings, it["path"], str(job_dir), pipeline.Reporter())
            seconds = round(time.perf_counter() - start, 1)
            row = {**it, "seed": seed, "seconds": seconds, "best_svg": summary["best_svg"],
                   "clip_b32": summary.get("clip_score"), **judge.score(it["path"], summary["best_svg"], it["label"])}
            if taste_model:
                from clipasso_studio.engine import aesthetic
                from clipasso_studio.engine.scoring import get_scorer

                scorer = scorer or get_scorer("cpu")
                row["taste"] = round(aesthetic.taste(scorer.embed_svg(summary["best_svg"]), taste_model), 3)
            rows.append(row)
            print(f"suite: {it['category']}/{it['name']} seed {seed}: {SIMILARITY} {row[SIMILARITY]}, "
                  f"{RECOG} {row[RECOG]}, {seconds} s", flush=True)
    return {"method": method, "overrides": overrides, "seeds": seeds, "rows": rows,
            "categories": summarise(rows)}


def _mean(values: list[float]) -> float | None:
    values = [v for v in values if v is not None]
    return round(sum(values) / len(values), 2) if values else None


def summarise(rows: list[dict]) -> dict:
    """The means per category (and "all") of every mark."""
    out = {}
    for cat in [*CATEGORIES, "all"]:
        sub = [r for r in rows if cat == "all" or r["category"] == cat]
        if sub:
            out[cat] = {k: _mean([r.get(k) for r in sub]) for k in (SIMILARITY, RECOG, "clip_b32", "taste", "seconds")
                        if any(r.get(k) is not None for r in sub)}
            out[cat]["n"] = len(sub)
    return out


def paired(a: dict, b: dict) -> dict:
    """B against A, picture by picture (same picture and seed): per category and overall the mean difference of
    each judge, its standard error and the verdict."""
    import math

    index = {(r["category"], r["name"], r["seed"]): r for r in a["rows"]}
    pairs = [(index[(r["category"], r["name"], r["seed"])], r) for r in b["rows"]
             if (r["category"], r["name"], r["seed"]) in index]
    out = {}
    for cat in [*CATEGORIES, "all"]:
        sub = [(x, y) for x, y in pairs if cat == "all" or x["category"] == cat]
        if not sub:
            continue
        res = {"n": len(sub)}
        for key in (SIMILARITY, RECOG, "taste"):
            diffs = [y[key] - x[key] for x, y in sub if x.get(key) is not None and y.get(key) is not None]
            if not diffs:
                continue
            mean = sum(diffs) / len(diffs)
            sd = math.sqrt(sum((d - mean) ** 2 for d in diffs) / (len(diffs) - 1)) if len(diffs) > 1 else 0.0
            res[key] = {"diff": round(mean, 2), "se": round(sd / math.sqrt(len(diffs)), 2)}
        res["verdict"] = verdict(res)
        out[cat] = res
    return out


def verdict(res: dict) -> str:
    """"gain": the similarity clearly higher (more than twice its standard error) and the recognisability not
    clearly lower; "loss" the other way round; else "no clear difference"."""
    sim, rec = res.get(SIMILARITY), res.get(RECOG)
    if not sim or res["n"] < 3:
        return "too few pictures"
    clear_up = sim["diff"] > 2 * sim["se"] and sim["diff"] > 0
    clear_down = sim["diff"] < -2 * sim["se"] and sim["diff"] < 0
    rec_down = bool(rec) and rec["diff"] < -2 * rec["se"] and rec["diff"] < 0
    rec_up = bool(rec) and rec["diff"] > 2 * rec["se"] and rec["diff"] > 0
    if clear_up and not rec_down:
        return "gain"
    if clear_down and not rec_up:
        return "loss"
    return "no clear difference"


def suite_markdown(result: dict) -> str:
    keys = [k for k in (SIMILARITY, RECOG, "clip_b32", "taste", "seconds") if k in result["categories"].get("all", {})]
    head = {SIMILARITY: "similarity (ViT-L/14)", RECOG: "recognisable %", "clip_b32": "CLIP B/32 (app)",
            "taste": "my taste", "seconds": "s / sketch"}
    lines = [f"### Suite {result['method']} {json.dumps(result['overrides']) if result['overrides'] else ''}", "",
             "| category | n | " + " | ".join(head[k] for k in keys) + " |", "|---|---|" + "---|" * len(keys)]
    for cat, m in result["categories"].items():
        lines.append(f"| {cat} | {m['n']} | " + " | ".join(str(m.get(k, "–")) for k in keys) + " |")
    return "\n".join(lines) + "\n\n"


def compare_markdown(res: dict, a_name: str, b_name: str) -> str:
    def cell(r, key):
        v = r.get(key)
        return f"{v['diff']:+.2f} ± {v['se']:.2f}" if v else "–"

    lines = [f"### {b_name} against {a_name}", "",
             "| category | n | similarity | recognisable | my taste | verdict |", "|---|---|---|---|---|---|"]
    for cat, r in res.items():
        lines.append(f"| {cat} | {r['n']} | {cell(r, SIMILARITY)} | {cell(r, RECOG)} | {cell(r, 'taste')} | "
                     f"{r['verdict']} |")
    return "\n".join(lines) + "\n\n"


def suite_sheet(result: dict, out_dir: Path) -> Path:
    """An HTML contact sheet: per category the photo and its sketch with the judges' marks."""
    parts = []
    for cat in CATEGORIES:
        rows = [r for r in result["rows"] if r["category"] == cat]
        if not rows:
            continue
        cells = []
        for r in rows:
            stem = f"{cat}_{r['name']}_s{r['seed']}"
            photo = out_dir / f"{stem}_photo{Path(r['path']).suffix}"
            shutil.copyfile(r["path"], photo)
            shutil.copyfile(r["best_svg"], out_dir / f"{stem}.svg")
            cells.append(f"<figure><img src='{photo.name}' height='180'><img src='{stem}.svg' height='180'>"
                         f"<figcaption>{html.escape(r['name'])}: {r[SIMILARITY]} · {r[RECOG]} %</figcaption></figure>")
        parts.append(f"<h2>{cat}</h2>" + "".join(cells))
    page = out_dir / "suite.html"
    style = ("body{font-family:sans-serif}figure{display:inline-block;margin:8px;text-align:center}"
             "img{background:#fff;border:1px solid #ccc;margin:2px}")
    page.write_text(f"<!doctype html><meta charset='utf-8'><title>Suite</title><style>{style}</style>" + "".join(parts),
                    encoding="utf-8")
    return page


def suite_main(args) -> int:
    if args.suite not in SUITES:
        print(f"unknown suite {args.suite}: {', '.join(SUITES)}")
        return 2
    sys.path.insert(0, str(ROOT / "tools"))
    import judge as judge_module

    overrides = dict(QUICK if args.quick else {})
    for item in args.set or []:
        key, _, value = item.partition("=")
        overrides[key.strip()] = parse_value(value.strip())
    from clipasso_studio.engine import model_store
    from clipasso_studio.engine.methods import requirements

    needed = set(getattr(requirements, args.suite)({**SUITES[args.suite], **overrides}))
    needed |= set(judge_module.REQUIRED_MODELS)
    missing = sorted(k for k in needed if not model_store.is_available(k))
    if missing and args.fetch:
        for key in missing:
            print(f"benchmark: downloading {key} …", flush=True)
            model_store.install(key)
        missing = []
    if missing:
        print(f"suite skipped: models missing: {', '.join(missing)} (--fetch downloads them)")
        return 0
    categories = [c.strip() for c in (args.categories or "").split(",") if c.strip()] or None
    images = suite_images(categories, args.quick)
    seeds = [int(x) for x in args.seeds.split(",")]
    out = Path(args.out or tempfile.mkdtemp(prefix="clipasso_suite_"))
    out.mkdir(parents=True, exist_ok=True)
    taste_model = load_taste_model(args.taste) if args.taste else None
    if args.taste and taste_model is None:
        print(f"suite: no trained taste below {args.taste} (10 ratings needed) – graded without it")
    from clipasso_studio import __version__

    result = run_suite(args.suite, overrides, images, out, seeds, taste_model)
    result.update(version=__version__, date=time.strftime("%Y-%m-%d"), label=args.label or "")
    name = f"suite_{args.label or args.suite}.json"
    (out / name).write_text(json.dumps(result, indent=1), encoding="utf-8")
    table = suite_markdown(result)
    print(table)
    if args.summary:
        with open(args.summary, "a", encoding="utf-8") as f:
            f.write(table)
    page = suite_sheet(result, out)
    print(f"suite: {out / name}, contact sheet {page}")
    return 0


def load_suite(path: str) -> dict:
    """A suite's result: its JSON file, or a folder whose ``suite_*.json`` files (parts of one variant, e.g. one
    category per CI job) are merged."""
    p = Path(path)
    if p.is_file():
        return json.loads(p.read_text(encoding="utf-8"))
    parts = [json.loads(f.read_text(encoding="utf-8")) for f in sorted(p.rglob("suite_*.json"))]
    if not parts:
        raise SystemExit(f"no suite_*.json below {path}")
    rows = [r for part in parts for r in part["rows"]]
    return {**parts[0], "rows": rows, "categories": summarise(rows), "label": parts[0].get("label") or p.name}


def compare_main(args) -> int:
    a_path, b_path = args.compare
    a, b = load_suite(a_path), load_suite(b_path)
    table = compare_markdown(paired(a, b), a.get("label") or Path(a_path).stem, b.get("label") or Path(b_path).stem)
    print(table)
    if args.summary:
        with open(args.summary, "a", encoding="utf-8") as f:
            f.write(table)
    return 0


def required_models(case: str) -> list[str]:
    from clipasso_studio.engine.methods import requirements

    _, settings = CASES[case]
    return getattr(requirements, settings["method"])(settings)


def missing_models(case: str) -> list[str]:
    from clipasso_studio.engine import model_store

    return [k for k in required_models(case) if not model_store.is_available(k)]


def calibrate(seconds: float = 2.0) -> float:
    """GFLOPS of a float32 matrix multiplication with all threads – scales the times between computers."""
    import torch

    a, b = torch.randn(1024, 1024), torch.randn(1024, 1024)
    for _ in range(3):
        a @ b
    n, start = 0, time.perf_counter()
    while time.perf_counter() - start < seconds:
        a @ b
        n += 1
    return round(2 * 1024 ** 3 * n / (time.perf_counter() - start) / 1e9, 1)


def peak_rss() -> int:
    """Peak memory of this process in bytes."""
    if sys.platform == "win32":
        import psutil

        return int(psutil.Process().memory_info().peak_wset)
    import resource

    rss = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
    return int(rss if sys.platform == "darwin" else rss * 1024)


def run_case(case: str, out_dir: str) -> dict:
    """One case in this process -> its measurements."""
    from clipasso_studio import paths
    from clipasso_studio.engine import pipeline

    sample, settings = CASES[case]
    start = time.perf_counter()
    summary = pipeline.run_job({**settings, "device": "cpu"}, str(paths.resource("samples", sample)), out_dir,
                               pipeline.Reporter())
    wall = time.perf_counter() - start
    runs = summary["runs"]
    iterations = sum(int(r.get("iterations_done") or 0) for r in runs)
    seconds = sum(float(r.get("seconds") or 0) for r in runs)
    scores = [round(float(r["clip_score"]), 2) for r in runs if r.get("clip_score") is not None]
    return {"scores": scores, "mean_score": round(sum(scores) / len(scores), 2) if scores else None,
            "wall": round(wall, 1), "sec_per_it": round(seconds / iterations, 3) if iterations else None,
            "peak_rss": peak_rss(), "best_svg": summary["best_svg"]}


def run_isolated(case: str, out_dir: str) -> dict:
    """The case in a child process (its own peak memory)."""
    result = Path(out_dir) / f"{case}.json"
    cmd = [sys.executable, str(Path(__file__).resolve()), "--case", case, "--out", out_dir, "--result", str(result)]
    proc = subprocess.run(cmd, cwd=str(ROOT))
    if proc.returncode != 0 or not result.is_file():
        return {"error": f"exit code {proc.returncode}"}
    return json.loads(result.read_text(encoding="utf-8"))


def compare(current: dict, baseline: dict | None) -> tuple[list[dict], bool]:
    """One row per case: the values, the change against the baseline and its verdict; True if a case failed."""
    rows, failed = [], False
    base_cases = (baseline or {}).get("cases", {})
    speed = 1.0
    if baseline and baseline.get("calibration_gflops") and current.get("calibration_gflops"):
        speed = current["calibration_gflops"] / baseline["calibration_gflops"]  # > 1: this computer is faster
    for case, now in current["cases"].items():
        row = {"case": case, **now, "verdict": "ok", "notes": []}
        base = base_cases.get(case)
        if "error" in now or "skipped" in now:
            row["verdict"] = "error" if "error" in now else "skipped"
            failed |= "error" in now
        elif base and "mean_score" in base and now.get("mean_score") is not None:
            row["score_delta"] = round(now["mean_score"] - base["mean_score"], 2)
            if row["score_delta"] < -SCORE_FAIL:
                row["verdict"] = "fail"
                row["notes"].append(f"CLIP score {row['score_delta']:+.2f}")
                failed = True
            elif row["score_delta"] < -SCORE_WARN:
                row["notes"].append(f"CLIP score {row['score_delta']:+.2f}")
            if base.get("wall"):
                row["time_ratio"] = round(now["wall"] * speed / base["wall"], 2)
                if row["time_ratio"] > TIME_WARN:
                    row["notes"].append(f"time x{row['time_ratio']:.2f}")
            if base.get("peak_rss"):
                row["rss_ratio"] = round(now["peak_rss"] / base["peak_rss"], 2)
                if row["rss_ratio"] > RSS_WARN:
                    row["notes"].append(f"memory x{row['rss_ratio']:.2f}")
            if row["notes"] and row["verdict"] == "ok":
                row["verdict"] = "warn"
        else:
            row["verdict"] = "new"
        rows.append(row)
    return rows, failed


def markdown(rows: list[dict], current: dict, baseline: dict | None) -> str:
    def fmt(v, spec=""):
        return "–" if v is None else format(v, spec)

    lines = ["## Benchmark", "",
             f"Calibration: {current['calibration_gflops']} GFLOPS"
             + (f" (baseline {baseline['calibration_gflops']} GFLOPS, version {baseline.get('version', '?')})"
                if baseline else " (no baseline)"), "",
             "| Case | Verdict | CLIP score | Δ score | Time s | × time | Peak MB | × memory | Notes |",
             "|---|---|---|---|---|---|---|---|---|"]
    for r in rows:
        if r["verdict"] in ("error", "skipped"):
            lines.append(f"| {r['case']} | {r['verdict']} | | | | | | | {r.get('error') or r.get('skipped')} |")
            continue
        lines.append(f"| {r['case']} | {r['verdict']} | {fmt(r.get('mean_score'))} | {fmt(r.get('score_delta'), '+')} "
                     f"| {fmt(r.get('wall'))} | {fmt(r.get('time_ratio'))} | {r['peak_rss'] / 1e6:.0f} "
                     f"| {fmt(r.get('rss_ratio'))} | {'; '.join(r['notes'])} |")
    return "\n".join(lines) + "\n"


def contact_sheet(rows: list[dict], out_dir: Path) -> Path:
    """An HTML page with the best sketch of every case (for the CI artifact)."""
    cells = []
    for r in rows:
        svg = r.get("best_svg")
        if not svg or not os.path.isfile(svg):
            continue
        name = f"{r['case']}.svg"
        shutil.copyfile(svg, out_dir / name)
        cells.append(f"<figure><img src='{name}' width='256'><figcaption>{html.escape(r['case'])}: "
                     f"{r.get('mean_score')}</figcaption></figure>")
    page = out_dir / "index.html"
    style = ("body{font-family:sans-serif}figure{display:inline-block;margin:8px;text-align:center}"
             "img{background:#fff;border:1px solid #ccc}")
    page.write_text(f"<!doctype html><meta charset='utf-8'><title>Benchmark</title><style>{style}</style>"
                    + "".join(cells), encoding="utf-8")
    return page


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("--cases", default=",".join(CASES))
    parser.add_argument("--out", default="")
    parser.add_argument("--fetch", action="store_true", help="download the models the cases need first")
    parser.add_argument("--baseline", default=str(BASELINE))
    parser.add_argument("--update-baseline", action="store_true")
    parser.add_argument("--summary", default="", help="also write the Markdown table to this file (append)")
    parser.add_argument("--case", help=argparse.SUPPRESS)  # (child process)
    parser.add_argument("--result", help=argparse.SUPPRESS)
    parser.add_argument("--suite", help="the categories with the independent judge, for this method")
    parser.add_argument("--categories", default="", help="--suite: only these categories")
    parser.add_argument("--quick", action="store_true", help="--suite: one picture per category, fewer iterations")
    parser.add_argument("--seeds", default="0", help="--suite: the seeds (one sketch each)")
    parser.add_argument("--set", action="append", metavar="KEY=VALUE", help="--suite: change a setting")
    parser.add_argument("--label", default="", help="--suite: the name of the variant")
    parser.add_argument("--taste", default="", help="--suite: also grade with 'My taste' of this app data folder")
    parser.add_argument("--compare", nargs=2, metavar=("A", "B"),
                        help="two suites side by side (JSON files, or folders whose parts are merged)")
    args = parser.parse_args(argv)
    if args.compare:
        return compare_main(args)
    if args.suite:
        return suite_main(args)

    if args.case:  # child: one case
        result = run_case(args.case, args.out)
        Path(args.result).write_text(json.dumps(result), encoding="utf-8")
        return 0

    cases = [c.strip() for c in args.cases.split(",") if c.strip()]
    unknown = [c for c in cases if c not in CASES]
    if unknown:
        print(f"unknown cases: {', '.join(unknown)}")
        return 2
    out = Path(args.out or tempfile.mkdtemp(prefix="clipasso_benchmark_"))
    out.mkdir(parents=True, exist_ok=True)
    if args.fetch:
        from clipasso_studio.engine import model_store

        for key in sorted({k for c in cases for k in missing_models(c)}):
            print(f"benchmark: downloading {key} …", flush=True)
            model_store.install(key)

    from clipasso_studio import __version__

    current = {"version": __version__, "date": time.strftime("%Y-%m-%d"), "calibration_gflops": calibrate(),
               "cases": {}}
    for case in cases:
        missing = missing_models(case)
        if missing:
            current["cases"][case] = {"skipped": "models missing: " + ", ".join(missing)}
            print(f"benchmark: {case} skipped ({', '.join(missing)} missing)", flush=True)
            continue
        print(f"benchmark: {case} …", flush=True)
        current["cases"][case] = run_isolated(case, str(out / case))
        print(f"benchmark: {case} {json.dumps(current['cases'][case])}", flush=True)

    baseline_path = Path(args.baseline)
    baseline = json.loads(baseline_path.read_text(encoding="utf-8")) if baseline_path.is_file() else None
    rows, failed = compare(current, baseline)
    table = markdown(rows, current, baseline)
    print(table)
    print("benchmark: " + json.dumps({k: v for k, v in current.items()}), flush=True)  # (a baseline from the log)
    if args.summary:
        with open(args.summary, "a", encoding="utf-8") as f:
            f.write(table)
    (out / "benchmark.json").write_text(json.dumps(current, indent=2), encoding="utf-8")
    contact_sheet(rows, out)
    if args.update_baseline:
        keep = {c: {k: v for k, v in r.items() if k != "best_svg"} for c, r in current["cases"].items()
                if "error" not in r and "skipped" not in r}
        baseline_path.parent.mkdir(parents=True, exist_ok=True)
        baseline_path.write_text(json.dumps({**current, "cases": keep}, indent=2) + "\n", encoding="utf-8")
        print(f"benchmark: baseline written to {baseline_path}")
        return 0
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
