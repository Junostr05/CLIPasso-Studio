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
    assert cpu["error"] is None and cpu["iterations"] == 3 and cpu["seconds"] > 0 and cpu["sec_per_iter"] > 0
    assert cpu["clip_score"] is not None and 0 < cpu["clip_score"] <= 100
    mps = next(r for r in rows if r["device"] == "mps")
    if torch.backends.mps.is_available():
        assert mps["error"] is None and mps["iterations"] == 3
    else:
        assert mps["error"] == "unavailable" and mps["seconds"] is None
    assert "| clipasso | cpu |" in done.stdout and "| clipasso | mps |" in done.stdout  # the table
