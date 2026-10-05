"""Quality and speed benchmark: short fixed jobs of every method on the bundled samples, on the CPU.

Each case runs in its own process, so its peak memory is its own. The result – the CLIP score of every sketch,
the time, the peak memory – is compared with ``benchmarks/baseline.json``:

- a CLIP score lower by more than ``SCORE_FAIL`` points on average fails (exit code 1),
- a time longer by more than ``TIME_WARN`` (after scaling with a matrix-multiplication calibration of the
  computer, CI machines differ) or more memory than ``RSS_WARN`` warns.

A case whose models are not installed is skipped (``--fetch`` downloads them first).

Usage::

    python tools/benchmark.py [--cases clipasso,swiftsketch,scenesketch,controlsketch] [--out DIR]
                              [--fetch] [--baseline benchmarks/baseline.json] [--update-baseline]
                              [--summary FILE]
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
SCORE_FAIL = 2.0  # CLIP score points (mean over the sketches of a case)
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
    args = parser.parse_args(argv)

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
