"""What runs where (engine/device_analysis.py): a worker's steps split into drawing, CLIP, model, backward and
optimiser, each with its time and device, written to the job's analysis/ and added up over the workers."""

from __future__ import annotations

import json

import torch

from clipasso_studio.engine import device_analysis, renderer


class _Events:
    def __init__(self):
        self.seen = []
        self.worker_id = 3

    def event(self, kind, **data):
        self.seen.append(kind)


def _step(points):
    shapes = [renderer.Path(torch.tensor([2]), points, torch.tensor(1.5))]
    groups = [renderer.ShapeGroup(torch.tensor([0]), None, torch.tensor([0.0, 0.0, 0.0, 1.0]))]
    img = renderer.render_on_white(64, 64, shapes, groups)
    img.mean().backward()


def test_a_job_is_measured_part_by_part(tmp_path):
    events = _Events()
    reporter = device_analysis.begin(events, events.worker_id)
    reporter.event("job_start", job_dir=str(tmp_path), device="cpu", seeds=[0], method="clipasso")
    points = (torch.rand(4, 2) * 50 + 5).requires_grad_(True)
    optimizer = torch.optim.Adam([points], lr=0.1)
    reporter.event("stage", seed=0, name="optimizing")
    for it in range(3):
        optimizer.zero_grad()
        _step(points)
        optimizer.step()
        reporter.event("iteration", seed=0, it=it, total=3)
    reporter.event("seed_done", seed=0)
    device_analysis.end()
    assert events.seen == ["job_start", "stage", "iteration", "iteration", "iteration", "seed_done"]  # (passed on)

    data = json.loads((tmp_path / "analysis" / "worker-3.json").read_text())
    parts = {p["key"]: p for p in data["parts"]}
    assert data["finished"] and data["method"] == "clipasso" and data["device"] == "cpu" and data["iterations"] == 3
    assert parts["draw"]["calls"] == 3 and parts["draw"]["devices"] == ["cpu"] and parts["draw"]["seconds"] > 0
    assert parts["backward"]["calls"] == 3 and parts["optimizer"]["calls"] == 3
    assert parts["clip"]["calls"] == 0 and data["fallbacks"] == []
    assert data["seconds"] >= data["optimizing_seconds"] > 0 and data["draw_device"] == "cpu"

    # nothing is measured outside a job; the workers of a job are added up
    _step(points.detach().requires_grad_(True))
    assert device_analysis.current() is None
    other = dict(data, worker=4, iterations=5)
    (tmp_path / "analysis" / "worker-4.json").write_text(json.dumps(other))
    both = device_analysis.read(str(tmp_path))
    assert both["workers"] == 2 and both["iterations"] == 8
    assert {p["key"]: p["calls"] for p in both["parts"]}["draw"] == 6
    assert device_analysis.read(str(tmp_path / "nothing")) is None


def test_the_operations_the_cpu_computes_for_the_apple_gpu_are_listed(tmp_path):
    import warnings

    reporter = device_analysis.begin(_Events())
    reporter.event("job_start", job_dir=str(tmp_path), device="cpu", method="clipasso")
    with warnings.catch_warnings():  # (as in the engine: pyproject's test settings ignore UserWarnings)
        warnings.simplefilter("default", UserWarning)
        warnings.warn("The operator 'aten::grid_sampler_2d_backward' is not currently supported on the MPS backend "
                      "and will fall back to run on the CPU. This may have performance implications.", UserWarning)
    device_analysis.end()
    data = device_analysis.read(str(tmp_path))
    assert data["fallbacks"] == ["aten::grid_sampler_2d_backward"]
