"""Cleaning up and disk space: old update downloads go, a complete download is checked instead of loaded
again, downloads stop early without space, a partial download continues on another mirror, caches can be
cleared, and the results move along with the output folder (the jobs find their files again)."""

import hashlib
import json
import os
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest

from clipasso_studio.engine.errors import UserError


@pytest.fixture
def fresh(user_data, tmp_path):
    from clipasso_studio.gui import app_settings as settings_module
    from clipasso_studio.gui.app_settings import app_settings

    settings_module._instance = None
    app_settings().data["output_dir"] = str(tmp_path / "out")
    os.makedirs(tmp_path / "out")
    yield tmp_path
    settings_module._instance = None


class _Files(BaseHTTPRequestHandler):
    files: dict = {}
    requests: list = []

    def do_GET(self):  # noqa: N802
        name = self.path.rsplit("/", 1)[-1]
        _Files.requests.append((name, self.headers.get("Range")))
        data = _Files.files[name]
        rng = self.headers.get("Range")
        start = int(rng.split("=")[1].split("-")[0]) if rng else 0
        body = data[start:]
        self.send_response(206 if rng else 200)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *args):
        pass


@pytest.fixture
def files_server():
    httpd = ThreadingHTTPServer(("127.0.0.1", 0), _Files)
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    _Files.files, _Files.requests = {}, []
    yield f"http://127.0.0.1:{httpd.server_address[1]}/dl"
    httpd.shutdown()


# ----------------------------------------------------------------------------- free space


def test_ensure_space(tmp_path, monkeypatch):
    from clipasso_studio import fileops

    fileops.ensure_space(tmp_path / "not" / "there", 1000)  # a folder still to be made: its drive counts
    monkeypatch.setattr(fileops, "free_space", lambda folder: 1_000_000)
    with pytest.raises(UserError) as err:
        fileops.ensure_space(tmp_path, 2_000_000_000, "test")
    assert err.value.code == "no_space" and err.value.params["need"] == "2.1"


def test_model_install_stops_without_space(tmp_path, monkeypatch):
    from clipasso_studio import fileops
    from clipasso_studio.engine import model_store

    spec = model_store.ModelSpec(key="test:big", filename="t/big.pt", urls=("http://127.0.0.1:9/never",),
                                 download_sha256=None, download_size=3_000_000_000, stored_size_mb=1500,
                                 bundled=False, kind="test")
    monkeypatch.setitem(model_store.SPECS, spec.key, spec)
    monkeypatch.setattr(fileops, "free_space", lambda folder: 4_000_000_000)
    with pytest.raises(UserError, match="not enough free space"):
        model_store.install(spec.key, dest_root=tmp_path)
    part = model_store.partial_dir(tmp_path)
    part.mkdir(parents=True)
    (part / "test_big.part").write_bytes(b"x" * 1000)
    assert model_store.space_needed(spec, tmp_path) == 3_000_000_000 - 1000 + 1_500_000_000


def test_checksums_of_all_single_file_models():
    from clipasso_studio.engine import model_store

    for key in ("u2net", "dino", "vgg16", "swiftsketch:diffusion", "swiftsketch:refine"):
        assert len(model_store.SPECS[key].download_sha256 or "") == 64, key
    assert model_store.SPECS["vgg16"].download_sha256.startswith("397923af")  # as in its file name


def test_a_partial_download_continues_on_another_mirror(files_server, tmp_path):
    from clipasso_studio.engine import model_store

    data = os.urandom(300_000)
    _Files.files["model.bin"] = data
    spec = model_store.ModelSpec(key="test:mirror", filename="t/m.pt", urls=(f"{files_server}/model.bin",),
                                 download_sha256=hashlib.sha256(data).hexdigest(), download_size=len(data),
                                 stored_size_mb=1, bundled=False, kind="test")
    (tmp_path / "test_mirror.part").write_bytes(data[:100_000])
    (tmp_path / "test_mirror.json").write_text(json.dumps(
        {"url": "https://first-mirror.invalid/model.bin", "size": len(data), "sha256": spec.download_sha256}))
    assert model_store.download_raw(spec, tmp_path).read_bytes() == data
    assert _Files.requests == [("model.bin", "bytes=100000-")]


# ----------------------------------------------------------------------------- updates


def _release(base, sizes):
    return {"tag": "v9.0.0", "assets": [{"name": n, "url": f"{base}/{n}", "size": s} for n, s in sizes.items()]
            + [{"name": "SHA256SUMS-CPU.txt", "url": f"{base}/SHA256SUMS-CPU.txt", "size": 0}]}


def test_a_complete_update_is_checked_not_loaded_again(files_server, tmp_path):
    from clipasso_studio.gui import updates

    setup = os.urandom(5000)
    sums = f"{hashlib.sha256(setup).hexdigest()}  CLIPassoStudio-CPU-Setup.exe\n"
    _Files.files = {"CLIPassoStudio-CPU-Setup.exe": setup, "SHA256SUMS-CPU.txt": sums.encode()}
    dest = tmp_path / "upd"
    dest.mkdir()
    (dest / "CLIPassoStudio-CPU-Setup.exe").write_bytes(setup)  # downloaded, the check did not finish
    release = _release(files_server, {"CLIPassoStudio-CPU-Setup.exe": 5000})
    path = updates.download_update(release, "cpu", "installed", dest)
    assert open(path, "rb").read() == setup
    assert [n for n, _ in _Files.requests] == ["SHA256SUMS-CPU.txt"]
    assert (dest / "CLIPassoStudio-CPU-Setup.exe.ok").is_file()
    # damaged while waiting: loaded again
    (dest / "CLIPassoStudio-CPU-Setup.exe").write_bytes(b"x" * 5000)
    (dest / "CLIPassoStudio-CPU-Setup.exe.ok").unlink()
    _Files.requests = []
    assert open(updates.download_update(release, "cpu", "installed", dest), "rb").read() == setup
    assert ("CLIPassoStudio-CPU-Setup.exe", None) in _Files.requests


def test_an_update_needs_space(files_server, tmp_path, monkeypatch):
    from clipasso_studio import fileops
    from clipasso_studio.gui import updates

    monkeypatch.setattr(fileops, "free_space", lambda folder: 100)
    with pytest.raises(UserError) as err:
        updates.download_update(_release(files_server, {"CLIPassoStudio-CPU-Setup.exe": 5000}), "cpu", "installed",
                                tmp_path / "upd")
    assert err.value.code == "no_space" and _Files.requests == []


def test_old_update_downloads_are_removed(user_data):
    from clipasso_studio import paths
    from clipasso_studio.gui import updates

    root = paths.user_data_dir() / "updates"
    for tag in ("v2.4.0", "v3.0.0", "v3.1.0"):
        (root / tag).mkdir(parents=True)
        (root / tag / "setup.exe").write_bytes(b"x" * 100)
    assert updates.remove_old_updates("3.0.0") == 200
    assert sorted(p.name for p in root.iterdir()) == ["v3.1.0"]  # newer: not installed yet


# ----------------------------------------------------------------------------- storage


def test_clear_areas(fresh):
    from clipasso_studio import paths
    from clipasso_studio.gui import storage

    masks = paths.user_data_dir() / "cache" / "masks"
    masks.mkdir(parents=True)
    (masks / "a.png").write_bytes(b"m" * 500)
    pasted = fresh / "out" / "_pasted"
    pasted.mkdir()
    (pasted / "keep.png").write_bytes(b"k" * 100)
    (pasted / "old.png").write_bytes(b"o" * 300)
    (fresh / "out" / "_webcam" / "sub").mkdir(parents=True)
    (fresh / "out" / "_webcam" / "sub" / "w.png").write_bytes(b"w" * 50)
    sizes = storage.sizes()
    assert sizes["masks"] == 500 and sizes["inputs"] == 450 and sizes["updates"] == 0
    assert storage.clear("masks") == 500 and masks.is_dir() and not any(masks.iterdir())
    assert storage.clear("inputs", keep=[str(pasted / "keep.png")]) == 350
    assert (pasted / "keep.png").is_file() and not (fresh / "out" / "_webcam" / "sub").exists()


def test_settings_storage_card(qapp, fresh, monkeypatch):
    from clipasso_studio import paths
    from clipasso_studio.gui.pages.other_pages import SettingsPage

    thumbs = paths.user_data_dir() / "cache" / "thumbs"
    thumbs.mkdir(parents=True)
    (thumbs / "t.png").write_bytes(b"t" * 2_500_000)
    page = SettingsPage()
    page.refresh_storage()
    name, size, clear = page.storage_rows["thumbs"]
    assert size.text() == "2 MB" and clear.isEnabled() and not page.storage_rows["updates"][2].isEnabled()
    assert page.clear_storage("thumbs", confirm=False) == 2_500_000
    assert not clear.isEnabled() and page.storage_rows["thumbs"][1].text() == "0 KB"


# ----------------------------------------------------------------------------- output folder


def _job(root, name="20260101-120000_camel_clipasso"):
    from clipasso_studio.engine import jobs

    job_dir = os.path.join(root, name)
    run_dir = os.path.join(job_dir, "camel_16strokes_seed0")
    os.makedirs(os.path.join(job_dir, "input"))
    os.makedirs(run_dir)
    init = os.path.join(job_dir, "input", "init.svg")
    with open(init, "w") as f:
        f.write("<svg/>")
    svg = os.path.join(run_dir, "best_iter.svg")
    with open(svg, "w") as f:
        f.write("<svg/>")
    settings = {"method": "clipasso", "path_svg": init}
    jobs.write_state(job_dir, os.path.join(root, "_pasted", "camel.png"), settings, "running")
    result = jobs.SeedResult(seed=0, run_name="camel_16strokes_seed0", run_dir=run_dir, best_loss=1.0, best_iter=5,
                             iterations_done=10, best_svg=svg, status="done")
    jobs.save_result(result)
    jobs.finish_job(job_dir, os.path.join(root, "_pasted", "camel.png"), settings, [result])
    return job_dir


def test_jobs_find_their_files_after_a_move(tmp_path):
    import shutil

    from clipasso_studio.engine import jobs

    os.makedirs(tmp_path / "old" / "_pasted")
    (tmp_path / "old" / "_pasted" / "camel.png").write_bytes(b"png")
    job_dir = _job(str(tmp_path / "old"))
    shutil.move(str(tmp_path / "old"), str(tmp_path / "new"))
    moved = str(tmp_path / "new" / os.path.basename(job_dir))
    summary = jobs.job_summary(moved)
    assert summary["best_svg"].startswith(moved) and os.path.isfile(summary["best_svg"])
    assert all(r["run_dir"].startswith(moved) and os.path.isfile(r["best_svg"]) for r in summary["runs"])
    assert list(jobs.saved_results(moved).values())[0].run_dir.startswith(moved)
    assert jobs.read_state(moved)["settings"]["path_svg"] == os.path.join(moved, "input", "init.svg")
    assert jobs.rebase("/elsewhere/file.svg", moved) == "/elsewhere/file.svg"  # not inside the job: unchanged


def test_settings_move_the_results_along(qapp, fresh, monkeypatch):
    from clipasso_studio.engine import jobs
    from clipasso_studio.gui import storage
    from clipasso_studio.gui.app_settings import app_settings
    from clipasso_studio.gui.pages import other_pages
    from clipasso_studio.gui.pages.other_pages import SettingsPage

    shown = []
    monkeypatch.setattr(other_pages.QMessageBox, "information", lambda *a: shown.append(a[2]))
    monkeypatch.setattr(other_pages.QMessageBox, "warning", lambda *a: shown.append(a[2]))

    old = str(fresh / "out")
    os.makedirs(os.path.join(old, "_pasted"))
    with open(os.path.join(old, "_pasted", "camel.png"), "wb") as f:
        f.write(b"png")
    job_dir = _job(old)
    with open(os.path.join(old, "holiday.jpg"), "wb") as f:  # not ours: stays
        f.write(b"jpg")
    assert storage.result_entries(old) == [os.path.basename(job_dir), "_pasted"]
    page = SettingsPage()
    changed = []
    page.output_dir_changed.connect(lambda *a: changed.append(a))
    page.busy_check = lambda: True
    new = str(fresh / "drive2" / "sketches")
    assert not page._choose_out(new, move=True)  # not while a job writes into the old folder
    assert len(shown) == 1 and not changed
    page.busy_check = lambda: False
    assert page._choose_out(new, move=True)
    assert app_settings().get("output_dir") == new and changed == [(old, new, True)]
    assert sorted(os.listdir(old)) == ["holiday.jpg"]
    moved = os.path.join(new, os.path.basename(job_dir))
    assert os.path.isfile(jobs.job_summary(moved)["best_svg"])
    assert not page._choose_out(os.path.join(new, os.path.basename(job_dir), "x"), move=True)  # into a job
    assert len(shown) == 2


def test_controller_follows_the_move(qapp, fresh):
    from clipasso_studio.gui.app_settings import app_settings
    from clipasso_studio.gui.controller import JobController, QueuedJob

    old, new = str(fresh / "out"), str(fresh / "other")
    ctl = JobController()
    ctl._timer.stop()
    ctl.jobs.append(QueuedJob(target=os.path.join(old, "_pasted", "a.png"), settings={"path_svg": ""}))
    ctl.jobs.append(QueuedJob(target="/photos/b.png", settings={}, status="failed",
                              job_dir=os.path.join(old, "job-b")))
    app_settings().data["recent_images"] = [os.path.join(old, "_webcam", "c.png"), "/photos/b.png"]
    ctl.relocate(old, new)
    assert ctl.jobs[0].target == os.path.join(new, "_pasted", "a.png")
    assert ctl.jobs[1].target == "/photos/b.png" and ctl.jobs[1].job_dir == os.path.join(new, "job-b")
    assert app_settings().get("recent_images") == [os.path.join(new, "_webcam", "c.png"), "/photos/b.png"]
    assert os.path.join(new, "_pasted", "a.png") in ctl.waiting_files()
