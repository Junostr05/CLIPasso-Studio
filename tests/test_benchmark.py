"""tools/benchmark.py: the comparison with the baseline (scores, calibrated time, memory), the report and the
baseline file – without running the methods."""

import importlib.util
import json
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent


@pytest.fixture(scope="module")
def bench():
    spec = importlib.util.spec_from_file_location("benchmark_tool", ROOT / "tools" / "benchmark.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _result(score, wall=100.0, rss=2e9):
    return {"scores": [score, score], "mean_score": score, "wall": wall, "sec_per_it": 0.5, "peak_rss": rss}


def test_compare(bench):
    baseline = {"calibration_gflops": 100.0, "version": "3.1.0",
                "cases": {"clipasso": _result(80.0), "swiftsketch": _result(67.0), "scenesketch": _result(70.0)}}
    current = {"calibration_gflops": 200.0, "cases": {
        "clipasso": _result(79.0, wall=60.0),  # a little lower score: still ok; twice as fast a computer
        "swiftsketch": _result(64.5),  # 2.5 points lower: fails
        "scenesketch": _result(70.0, wall=50.0, rss=3e9),  # (50 s on a 2x computer = 100 s) more memory: warns
        "controlsketch": _result(60.0),  # not in the baseline
        "extra": {"skipped": "models missing: sd15"},
    }}
    rows, failed = bench.compare(current, baseline)
    by = {r["case"]: r for r in rows}
    assert failed
    assert by["clipasso"]["verdict"] == "ok" and by["clipasso"]["time_ratio"] == 1.2  # 60 s x 2 / 100 s
    assert by["clipasso"]["score_delta"] == -1.0
    assert by["swiftsketch"]["verdict"] == "fail" and "CLIP score -2.50" in by["swiftsketch"]["notes"]
    assert by["scenesketch"]["verdict"] == "warn" and by["scenesketch"]["rss_ratio"] == 1.5
    assert by["controlsketch"]["verdict"] == "new" and by["extra"]["verdict"] == "skipped"
    table = bench.markdown(rows, current, baseline)
    assert "| swiftsketch | fail |" in table and "baseline 100.0 GFLOPS, version 3.1.0" in table

    rows, failed = bench.compare({"calibration_gflops": 100.0, "cases": {"clipasso": _result(80.0)}}, None)
    assert not failed and rows[0]["verdict"] == "new"
    _, failed = bench.compare({"calibration_gflops": 1.0, "cases": {"clipasso": {"error": "exit code 1"}}}, baseline)
    assert failed


def test_main_writes_the_baseline_and_fails_on_a_worse_score(bench, tmp_path, monkeypatch):
    scores = {"clipasso": 80.0}
    monkeypatch.setattr(bench, "calibrate", lambda seconds=2.0: 100.0)
    monkeypatch.setattr(bench, "missing_models", lambda case: [])
    monkeypatch.setattr(bench, "run_isolated", lambda case, out: {**_result(scores[case]), "best_svg": ""})
    base = tmp_path / "baseline.json"
    summary = tmp_path / "summary.md"
    assert bench.main(["--cases", "clipasso", "--out", str(tmp_path / "o"), "--baseline", str(base),
                       "--update-baseline"]) == 0
    saved = json.loads(base.read_text())
    assert saved["cases"]["clipasso"]["mean_score"] == 80.0 and "best_svg" not in saved["cases"]["clipasso"]
    assert bench.main(["--cases", "clipasso", "--out", str(tmp_path / "o"), "--baseline", str(base),
                       "--summary", str(summary)]) == 0
    scores["clipasso"] = 77.0
    assert bench.main(["--cases", "clipasso", "--out", str(tmp_path / "o"), "--baseline", str(base),
                       "--summary", str(summary)]) == 1
    assert summary.read_text().count("## Benchmark") == 2
    assert (tmp_path / "o" / "index.html").is_file() and (tmp_path / "o" / "benchmark.json").is_file()
    assert bench.main(["--cases", "nothing"]) == 2


def test_every_case_names_its_models(bench):
    for case in bench.CASES:
        keys = bench.required_models(case)
        assert keys and all(isinstance(k, str) for k in keys)
    assert "sd15" in bench.required_models("controlsketch") and "lama" in bench.required_models("scenesketch")
