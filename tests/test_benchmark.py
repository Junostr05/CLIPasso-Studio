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
        "swiftsketch": _result(61.5),  # 5.5 points lower: fails
        "scenesketch": _result(70.0, wall=50.0, rss=3e9),  # (50 s on a 2x computer = 100 s) more memory: warns
        "controlsketch": _result(60.0),  # not in the baseline
        "extra": {"skipped": "models missing: sd15"},
    }}
    rows, failed = bench.compare(current, baseline)
    by = {r["case"]: r for r in rows}
    assert failed
    assert by["clipasso"]["verdict"] == "ok" and by["clipasso"]["time_ratio"] == 1.2  # 60 s x 2 / 100 s
    assert by["clipasso"]["score_delta"] == -1.0
    assert by["swiftsketch"]["verdict"] == "fail" and "CLIP score -5.50" in by["swiftsketch"]["notes"]
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
    scores["clipasso"] = 77.0  # 3 points lower: a warning only (CPUs differ)
    assert bench.main(["--cases", "clipasso", "--out", str(tmp_path / "o"), "--baseline", str(base),
                       "--summary", str(summary)]) == 0
    assert "| clipasso | warn |" in summary.read_text()
    scores["clipasso"] = 74.0
    assert bench.main(["--cases", "clipasso", "--out", str(tmp_path / "o"), "--baseline", str(base),
                       "--summary", str(summary)]) == 1
    assert summary.read_text().count("## Benchmark") == 3
    assert (tmp_path / "o" / "index.html").is_file() and (tmp_path / "o" / "benchmark.json").is_file()
    assert bench.main(["--cases", "nothing"]) == 2


def test_the_baseline_in_the_repository(bench):
    data = json.loads((ROOT / "benchmarks" / "baseline.json").read_text())
    assert data["calibration_gflops"] > 0 and set(data["cases"]) <= set(bench.CASES)
    assert all(c["mean_score"] > 0 and c["wall"] > 0 and c["peak_rss"] > 0 for c in data["cases"].values())


def test_every_case_names_its_models(bench):
    for case in bench.CASES:
        keys = bench.required_models(case)
        assert keys and all(isinstance(k, str) for k in keys)
    assert "sd15" in bench.required_models("controlsketch") and "lama" in bench.required_models("scenesketch")


# ---------------------------------------------------------------- categories and the independent judge (3.7)
def test_the_suite_pictures(bench):
    items = bench.suite_images()
    cats = {c: [it for it in items if it["category"] == c] for c in bench.CATEGORIES}
    assert len(cats["object"]) == 4 and len(cats["portrait"]) == 3 and len(cats["animal"]) == 4
    assert len(cats["scene"]) == 4
    for it in items:
        assert Path(it["path"]).is_file() and it["label"]
    quick = bench.suite_images(quick=True)
    assert [it["category"] for it in quick] == list(bench.CATEGORIES)
    assert {it["category"] for it in bench.suite_images(["portrait"])} == {"portrait"}
    # every photo of the benchmark is listed with its source and a public-domain licence
    sources = json.loads((ROOT / "benchmarks" / "images" / "sources.json").read_text(encoding="utf-8"))
    listed = (ROOT / "benchmarks" / "images" / "SOURCES.md").read_text(encoding="utf-8")
    on_disk = sorted(p.relative_to(ROOT / "benchmarks" / "images").as_posix()
                     for p in (ROOT / "benchmarks" / "images").rglob("*.jpg"))
    assert sorted(s["file"] for s in sources) == on_disk
    assert all(s["nasa_id"] in listed and s["url"].startswith("https://images.nasa.gov/") for s in sources)


def _rows(values, key="clip_l14", rec=None):
    rows = []
    for i, v in enumerate(values):
        rows.append({"category": "object" if i % 2 else "animal", "name": f"p{i}", "seed": 0, key: v,
                     "recog": (rec[i] if rec else 50.0)})
    return {"rows": rows}


def test_paired_comparison_and_verdict(bench):
    a = _rows([60.0, 62.0, 58.0, 61.0, 59.0, 63.0])
    better = _rows([62.1, 64.0, 60.2, 63.1, 60.9, 65.2])  # about 2 points, every picture: a clear gain
    res = bench.paired(a, better)
    assert res["all"]["n"] == 6 and res["all"]["clip_l14"]["diff"] == pytest.approx(2.08, abs=0.01)
    assert res["all"]["verdict"] == "gain"
    noisy = _rows([63.0, 59.0, 60.0, 64.0, 57.0, 62.0])  # up and down: no clear difference
    assert bench.paired(a, noisy)["all"]["verdict"] == "no clear difference"
    # more similar but clearly less recognisable: no gain
    worse_rec = _rows([62.1, 64.0, 60.2, 63.1, 60.9, 65.2], rec=[30.0, 31.0, 29.0, 32.0, 30.0, 28.0])
    assert bench.paired(a, worse_rec)["all"]["verdict"] == "no clear difference"
    assert bench.paired(better, a)["all"]["verdict"] == "loss"
    assert bench.paired(a, better)["animal"]["verdict"] == "gain"  # (3 pictures per category)
    # pictures in only one of them are left out; too few pictures: no verdict
    assert bench.paired(a, {"rows": better["rows"][:2]})["all"]["verdict"] == "too few pictures"
    md = bench.compare_markdown(res, "A", "B")
    assert "| all | 6 | +2.08 ± " in md and "gain" in md


def test_parts_of_a_variant_are_merged(bench, tmp_path):
    """The CI measures every variant in one job per category: a folder's parts are compared as one suite."""
    a, b = _rows([60.0, 62.0, 58.0, 61.0, 59.0, 63.0]), _rows([62.1, 64.0, 60.2, 63.1, 60.9, 65.2])
    for name, res in (("base", a), ("better", b)):
        for cat in ("animal", "object"):
            part = tmp_path / name / cat
            part.mkdir(parents=True)
            rows = [r for r in res["rows"] if r["category"] == cat]
            (part / f"suite_{name}.json").write_text(json.dumps({"method": "clipasso", "label": name, "rows": rows}))
    merged = bench.load_suite(str(tmp_path / "base"))
    assert len(merged["rows"]) == 6 and merged["label"] == "base" and merged["categories"]["all"]["n"] == 6
    assert bench.paired(merged, bench.load_suite(str(tmp_path / "better")))["all"]["verdict"] == "gain"
    single = tmp_path / "base" / "animal" / "suite_base.json"
    assert len(bench.load_suite(str(single))["rows"]) == 3
    with pytest.raises(SystemExit):
        bench.load_suite(str(tmp_path / "empty"))


def test_the_measured_variants(bench):
    """benchmarks/variants.json (the CI's measurements): every setting exists, "base" changes nothing."""
    from clipasso_studio import settings_schema as schema

    spec = json.loads((ROOT / "benchmarks" / "variants.json").read_text(encoding="utf-8"))
    assert spec["method"] in bench.SUITES and set(spec["categories"]) <= set(bench.CATEGORIES)
    assert spec["variants"]["base"]["set"] == []
    keys = {p.key for p in schema.METHOD_PARAMS[spec["method"]]}
    for name, v in spec["variants"].items():
        assert set(v.get("categories", [])) <= set(bench.CATEGORIES), name
        assert v.get("against", "base") in spec["variants"], name  # (compared with "base" or this one)
        for item in v["set"]:
            assert item.partition("=")[0] in keys, (name, item)


def test_summary_and_table(bench):
    rows = [{"category": "object", "name": "a", "seed": 0, "clip_l14": 60.0, "recog": 40.0, "clip_b32": 70.0,
             "seconds": 10.0},
            {"category": "portrait", "name": "b", "seed": 0, "clip_l14": 50.0, "recog": 20.0, "clip_b32": 60.0,
             "seconds": 12.0}]
    summary = bench.summarise(rows)
    assert summary["all"] == {"clip_l14": 55.0, "recog": 30.0, "clip_b32": 65.0, "seconds": 11.0, "n": 2}
    assert summary["object"]["n"] == 1 and "animal" not in summary
    table = bench.suite_markdown({"method": "clipasso", "overrides": {"num_iter": 51}, "categories": summary})
    assert "| portrait | 1 | 50.0 | 20.0 | 60.0 | 12.0 |" in table and '"num_iter": 51' in table


def test_set_values_and_the_taste_file(bench, tmp_path):
    assert bench.parse_value("true") is True and bench.parse_value("0.5") == 0.5
    assert bench.parse_value("[1, 2]") == [1, 2] and bench.parse_value("ViT-B/16") == "ViT-B/16"
    assert bench.load_taste_model(str(tmp_path)) is None
    (tmp_path / "CLIPassoStudio").mkdir()
    (tmp_path / "CLIPassoStudio" / "taste.json").write_text(json.dumps({"samples": {}, "model": {"w": [1.0]}}))
    assert bench.load_taste_model(str(tmp_path)) == {"w": [1.0]}


def test_the_judge_is_in_no_optimisation():
    """The judge's model is used by nothing the app optimises with, and is not offered on the models page."""
    from clipasso_studio import settings_schema as schema
    from clipasso_studio.engine import model_store
    from clipasso_studio.gui.pages.other_pages import model_group

    spec = model_store.SPECS["clip:ViT-L/14"]
    assert spec.extra.get("purpose") == "benchmark" and not spec.bundled and model_group(spec.key) == "benchmark"
    for params in schema.METHOD_PARAMS.values():
        for p in params:
            assert "ViT-L/14" not in [str(c) for c in (p.choices or [])], p.key
    users = [f.relative_to(ROOT).as_posix() for f in (ROOT / "clipasso_studio").rglob("*.py")
             if "ViT-L/14" in f.read_text(encoding="utf-8")]
    assert users == ["clipasso_studio/engine/model_store.py"]
