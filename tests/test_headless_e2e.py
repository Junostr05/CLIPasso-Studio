"""Real jobs through ``python -m clipasso_studio.headless``, as the Mac app runs them (CPU, the bundled models)."""

from __future__ import annotations

import json
import os
import time

import pytest

from clipasso_studio.engine import jobs

from tests.headless_engine import Engine, image_in, tiny_settings


@pytest.fixture
def engine(tmp_path):
    e = Engine(tmp_path)
    yield e
    e.close()
    assert e.bad == [], e.bad  # every line on stdout was JSON


def test_job_runs_with_preview_and_done(engine, tmp_path):
    target = image_in(tmp_path / "Ausgabe ö")
    answer = engine.request("start", target=str(target), settings=tiny_settings(),
                            output_root=str(tmp_path / "Ausgabe ö" / "Skizzen"))
    assert answer["ok"], answer
    job, job_dir = answer["result"]["job"], answer["result"]["job_dir"]
    done = engine.wait_event("job_done")
    assert done["job"] == job and done["data"]["job_dir"] == job_dir
    kinds = [e["event"] for e in engine.events]
    assert "iteration" in kinds and "seed_done" in kinds and kinds.index("seed_done") < kinds.index("job_done")
    previews = [e for e in engine.events if e["event"] == "preview"]
    assert previews and previews[-1]["data"]["svg"].lstrip().startswith("<svg")
    assert all(e["job"] == job for e in engine.events)
    last = [e for e in engine.events if e["event"] == "iteration"][-1]["data"]
    assert last["it"] + 1 == last["total"] == 30
    summary = json.loads((tmp_path / "Ausgabe ö" / "Skizzen" / os.path.basename(job_dir) / "job.json")
                         .read_text(encoding="utf-8"))
    assert summary["best_svg"].endswith("_best.svg") and jobs.read_state(job_dir)["status"] == "done"
    assert engine.request("pause")["error"]["code"] == "no_job"  # the job is over


def test_pause_and_resume(engine, tmp_path):
    answer = engine.request("start", target=str(image_in(tmp_path)), settings=tiny_settings(num_iter=5000),
                            output_root=str(tmp_path / "out"))
    job_dir = answer["result"]["job_dir"]
    first = engine.wait_event("iteration")
    seen = time.monotonic()
    second = engine.wait_event("iteration", since=engine.events.index(first) + 1)
    step = max(1.0, time.monotonic() - seen)  # how long one iteration takes here
    assert engine.request("pause")["result"] == {"paused": True}
    paused_at = len(engine.events)
    time.sleep(3 * step)  # the iteration under way when the pause came still ends (as in the studio)
    engine.request("hello")  # (takes in what came meanwhile)
    before = len(engine.events)
    assert len([e for e in engine.events[paused_at:] if e["event"] == "iteration"]) <= 1
    time.sleep(3 * step)
    engine.request("hello")
    assert [e for e in engine.events[before:] if e["event"] == "iteration"] == [], second
    assert engine.request("resume")["result"] == {"paused": False}
    engine.wait_event("iteration", since=len(engine.events))
    assert engine.request("cancel")["ok"]
    end = engine.wait_event("job_done", timeout=120)  # a cancelled job keeps its best sketch so far
    assert end["data"]["job_dir"] == job_dir
    assert jobs.read_state(job_dir)["status"] == "cancelled" and jobs.can_continue(job_dir)


def test_cancel_then_continue(engine, tmp_path):
    target = image_in(tmp_path)
    settings = tiny_settings(num_sketches=2, num_iter=40)
    job_dir = engine.request("start", target=str(target), settings=settings,
                             output_root=str(tmp_path / "out"))["result"]["job_dir"]
    engine.wait_event("seed_done")
    engine.request("cancel")
    engine.wait_event("job_done", since=len(engine.events) - 1)
    assert jobs.read_state(job_dir)["status"] == "cancelled" and jobs.remaining_seeds(job_dir) == [1000]
    since = len(engine.events)
    answer = engine.request("start", target=str(target), settings=settings, output_root=str(tmp_path / "out"),
                            resume_dir=job_dir)
    assert answer["ok"] and answer["result"]["job_dir"] == job_dir and answer["result"]["job"] == "j2"
    engine.wait_event("job_done", since=since)
    assert jobs.read_state(job_dir)["status"] == "done"
    assert sorted(jobs.done_results(job_dir)) == [0, 1000]


def test_eof_marks_interrupted(engine, tmp_path):
    answer = engine.request("start", target=str(image_in(tmp_path)), settings=tiny_settings(num_iter=5000),
                            output_root=str(tmp_path / "out"))
    job_dir = answer["result"]["job_dir"]
    engine.wait_event("iteration")
    started = time.monotonic()
    engine.proc.stdin.close()  # the app is gone
    assert engine.proc.wait(timeout=30) == 0
    assert time.monotonic() - started < 15
    assert jobs.read_state(job_dir)["status"] == "interrupted" and jobs.can_continue(job_dir)
