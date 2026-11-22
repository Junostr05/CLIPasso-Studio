"""tools/bench_device.py measures the CPU against the Apple GPU (MPS) per method – a device that is not there is
reported as unavailable, never left out."""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import torch

ROOT = Path(__file__).resolve().parent.parent
SAMPLE = ROOT / "clipasso_studio" / "resources" / "samples" / "camel.png"


def test_bench_runs_tiny_cpu(tmp_path):
    out = tmp_path / "bench.json"
    done = subprocess.run([sys.executable, str(ROOT / "tools" / "bench_device.py"), "--methods", "clipasso",
                           "--devices", "cpu,mps", "--iters", "3", "--repeats", "1", "--images", str(SAMPLE),
                           "--out", str(out), "--work", str(tmp_path / "work")],
                          capture_output=True, text=True, cwd=ROOT, timeout=900)
    assert done.returncode == 0, done.stderr[-4000:]
    rows = json.loads(out.read_text(encoding="utf-8"))
    assert {r["device"] for r in rows} == {"cpu", "mps"}
    cpu = next(r for r in rows if r["device"] == "cpu")
    assert cpu["method"] == "clipasso" and cpu["image"] == "camel.png" and cpu["repeat"] == 1
    assert cpu["error"] is None and cpu["traceback"] is None, cpu["traceback"]
    assert cpu["iterations"] == 3 and cpu["seconds"] > 0 and cpu["sec_per_iter"] > 0
    assert cpu["clip_score"] is not None and 0 < cpu["clip_score"] <= 100
    # every sketch also judged by the same scorer on the CPU (a device's own score is not comparable)
    assert cpu["cpu_clip_score"] == cpu["clip_score"] and cpu["nan_in_svg"] is False
    mps = next(r for r in rows if r["device"] == "mps")
    if torch.backends.mps.is_available():
        assert mps["error"] is None, mps["traceback"]
        assert mps["iterations"] == 3
    else:
        assert mps["error"] == "unavailable" and mps["seconds"] is None and mps["traceback"] is None
    assert "| clipasso | cpu |" in done.stdout and "| clipasso | mps |" in done.stdout  # the table


def test_clip_agreement_on_the_cpu():
    """The check of the embeddings: the CPU against itself agrees exactly; a missing device is reported."""
    import importlib.util

    spec = importlib.util.spec_from_file_location("bench_device", ROOT / "tools" / "bench_device.py")
    bench = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(bench)
    rows = bench.clip_agreement("cpu", [SAMPLE, SAMPLE])
    assert [r["cosine_to_cpu"] for r in rows if r["check"] == "clip_embedding"] == [1.0, 1.0]
    pairs = next(r for r in rows if r["check"] == "clip_pairs")
    assert pairs["cpu_mean_pair"] == pairs["device_mean_pair"] == 1.0  # (the same image twice)
    assert bench.clip_agreement("no-such-device", [SAMPLE]) == [
        {"check": "clip_embedding", "device": "no-such-device", "error": "unavailable"}]
