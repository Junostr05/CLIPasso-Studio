"""Out of memory: recognised in the worker, offered again on the CPU or with smaller settings."""

import json
import os

import pytest


def test_out_of_memory_is_recognised():
    from clipasso_studio.engine.runner import is_out_of_memory

    class OutOfMemoryError(RuntimeError):  # (torch.cuda.OutOfMemoryError)
        pass

    assert is_out_of_memory(OutOfMemoryError("CUDA out of memory. Tried to allocate 2.00 GiB"))
    assert is_out_of_memory(RuntimeError("[enforce fail at alloc_cpu.cpp:117] DefaultCPUAllocator: can't allocate "
                                         "memory: you tried to allocate 123 bytes"))
    assert is_out_of_memory(MemoryError())
    assert is_out_of_memory(RuntimeError("cuDNN error: CUDNN_STATUS_ALLOC_FAILED"))
    assert not is_out_of_memory(RuntimeError("shape mismatch"))


def test_worker_reports_it(monkeypatch):
    from clipasso_studio.engine import pipeline, runner

    events = []

    class Rec:
        def event(self, kind, **data):
            events.append((kind, data))

    def boom(*a, **k):
        raise RuntimeError("CUDA out of memory. Tried to allocate 20.00 MiB")

    monkeypatch.setattr(pipeline, "run_job", boom)
    assert runner._run_one(Rec(), {}, "x.png", "/tmp", "", None, True, None, None, False) is False
    kind, data = events[-1]
    assert kind == "error" and data["oom"] is True


def test_smaller_settings():
    from clipasso_studio import settings_schema as schema
    from clipasso_studio.gui.controller import smaller_settings

    assert smaller_settings(schema.default_settings("controlsketch")) == {"render_size": 384, "turbo": True}
    assert smaller_settings({**schema.default_settings("controlsketch"), "render_size": 256, "turbo": True}) is None
    assert smaller_settings({**schema.default_settings("clipasso"), "image_scale": 448}) == \
        {"num_aug_clip": 2, "image_scale": 224}
    assert smaller_settings({**schema.default_settings("scenesketch"), "num_aug_clip": 1}) is None
    assert smaller_settings(schema.default_settings("swiftsketch")) is None


def test_unfinished_sketches_start_again(tmp_path):
    from clipasso_studio import settings_schema as schema
    from clipasso_studio.engine import jobs

    job = tmp_path / "job"
    done, open_ = job / "a_seed0", job / "a_seed1000"
    for d in (done, open_):
        d.mkdir(parents=True)
        (d / jobs.CHECKPOINT_FILE).write_bytes(b"x")
    (done / "best_iter.svg").write_text("<svg/>")
    jobs.save_result(jobs.SeedResult(seed=0, run_name="a_seed0", run_dir=str(done), best_loss=0.1, best_iter=1,
                                     iterations_done=2, best_svg=str(done / "best_iter.svg"), status="done"))
    jobs.write_state(str(job), str(tmp_path / "a.png"), {**schema.default_settings("clipasso"), "num_sketches": 2})
    assert jobs.drop_checkpoints(str(job)) == 1
    assert (done / jobs.CHECKPOINT_FILE).exists() and not (open_ / jobs.CHECKPOINT_FILE).exists()


@pytest.fixture
def window(tmp_path, monkeypatch, qapp):
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path))
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path))
    from clipasso_studio.gui import app_settings as settings_module
    from clipasso_studio.gui.app_settings import app_settings

    settings_module._instance = None
    app_settings().data["output_dir"] = str(tmp_path / "out")
    from clipasso_studio.gui.main_window import MainWindow

    w = MainWindow()
    w.controller.start_next = lambda: None
    yield w
    w.studio.shutdown()
    w.controller.shutdown()
    w.close()
    settings_module._instance = None


def test_retry_on_the_cpu_or_smaller(window, tmp_path, monkeypatch):
    from PIL import Image

    from clipasso_studio import settings_schema as schema
    from clipasso_studio.engine import jobs
    from clipasso_studio.gui import dialogs

    target = str(tmp_path / "rose.png")
    Image.new("RGB", (20, 20), "white").save(target)
    c = window.controller
    job = c.enqueue(target, schema.default_settings("controlsketch"), start=False)
    job_dir = tmp_path / "out" / "rose_job"
    run = job_dir / "rose_controlsketch_32strokes_seed20"
    run.mkdir(parents=True)
    (run / jobs.CHECKPOINT_FILE).write_bytes(b"x")
    jobs.write_state(str(job_dir), target, job.settings, "failed")
    job.status, job.job_dir, job.device, job.oom = "failed", str(job_dir), "cuda:0", True
    asked = []
    monkeypatch.setattr(dialogs, "ask_out_of_memory", lambda parent, name, on_gpu, smaller:
                        asked.append((name, on_gpu, smaller)) or "cpu")
    assert window.offer_out_of_memory_retry(job) == "cpu"
    assert asked == [("rose.png", True, {"render_size": 384, "turbo": True})]
    assert job.status == "queued" and job.settings["device"] == "cpu" and job.resume_dir == str(job_dir)
    assert (run / jobs.CHECKPOINT_FILE).exists() and not job.oom  # continues where it stopped

    job.status, job.oom = "failed", True
    monkeypatch.setattr(dialogs, "ask_out_of_memory", lambda *a, **k: "smaller")
    window.offer_out_of_memory_retry(job)
    assert job.settings["render_size"] == 384 and job.settings["turbo"] is True
    assert not (run / jobs.CHECKPOINT_FILE).exists()  # another canvas size: that sketch starts again
    with open(job_dir / "job_state.json") as f:
        assert json.load(f)["status"] == "failed"  # (the runner writes the new state when it starts)
    assert os.path.isdir(job_dir)
