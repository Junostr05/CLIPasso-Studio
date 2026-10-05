"""The PyTorch for older graphics cards: imported from its folder instead of the bundled one when switched
on, offered once for a card the bundled PyTorch cannot use, downloaded (resumable, checked) and unpacked,
removed again, and the precision setting of the GPU."""

import hashlib
import io
import json
import os
import re
import subprocess
import sys
import threading
import zipfile
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import pytest

from clipasso_studio import gpu_runtime
from clipasso_studio.engine.errors import UserError

ROOT = Path(__file__).resolve().parent.parent
GTX1060 = {"name": "NVIDIA GeForce GTX 1060 6GB", "memory_gb": 6.0, "supported": False, "capability": [6, 1]}
RTX3060 = {"name": "NVIDIA GeForce RTX 3060", "memory_gb": 12.0, "supported": True, "capability": [8, 6]}


def _fake_runtime(folder: Path, torch_version: str = gpu_runtime.TORCH_VERSION) -> Path:
    (folder / "torch").mkdir(parents=True)
    (folder / "torch" / "__init__.py").write_text('WHERE = "runtime"\n')
    (folder / "torch" / "sub.py").write_text("X = 1\n")
    (folder / "torchvision").mkdir()
    (folder / "torchvision" / "__init__.py").write_text("")
    (folder / gpu_runtime.MARKER).write_text(json.dumps({"name": folder.name, "torch": torch_version,
                                                          "complete": True}))
    return folder


def _run(code: str, env: dict) -> str:
    out = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, cwd=str(ROOT),
                         env={**os.environ, **env}, timeout=120)
    assert out.returncode == 0, out.stderr
    return out.stdout.strip()


PROBE = ("from clipasso_studio import gpu_runtime; site = gpu_runtime.activate(); import torch, torch.sub; "
         "import torchvision; print(site); print(getattr(torch, 'WHERE', 'bundled')); print(torch.sub.__file__); "
         "print(torchvision.__file__); import os; print(os.environ.get(gpu_runtime.ENV, ''))")


def test_torch_comes_from_the_runtime(tmp_path):
    site = _fake_runtime(tmp_path / "torch-x-cu126")
    lines = _run(PROBE, {gpu_runtime.ENV: str(site)}).splitlines()
    assert lines[0] == str(site) and lines[1] == "runtime"
    assert lines[2].startswith(str(site)) and lines[3].startswith(str(site))
    assert lines[4] == str(site)  # passed on to the worker processes


def test_a_runtime_for_another_pytorch_is_not_used(tmp_path):
    site = _fake_runtime(tmp_path / "torch-old-cu126", torch_version="1.0.0")
    code = ("from clipasso_studio import gpu_runtime; print(gpu_runtime.activate()); import torch; "
            "print(torch.__file__)")
    lines = _run(code, {gpu_runtime.ENV: str(site)}).splitlines()
    assert lines[0] == "None" and not lines[1].startswith(str(site))


def test_switched_on_in_the_settings(tmp_path):
    data = tmp_path / "data"
    app = data / "CLIPassoStudio"
    _fake_runtime(app / "runtimes" / gpu_runtime.LEGACY.name)
    (app / "settings.json").write_text(json.dumps({gpu_runtime.SETTING: gpu_runtime.LEGACY.name}))
    env = {"XDG_DATA_HOME": str(data), "LOCALAPPDATA": str(data), gpu_runtime.ENV: ""}
    lines = _run(PROBE, env).splitlines()
    assert lines[1] == "runtime"
    (app / "settings.json").write_text(json.dumps({gpu_runtime.SETTING: ""}))  # switched off
    code = "from clipasso_studio import gpu_runtime; print(gpu_runtime.activate())"
    assert _run(code, env) == "None"


def test_too_late_once_torch_is_imported(tmp_path, monkeypatch):
    import torch  # noqa: F401 - the bundled one is loaded in this process

    monkeypatch.setenv(gpu_runtime.ENV, str(_fake_runtime(tmp_path / "rt")))
    monkeypatch.setitem(gpu_runtime._state, "site", None)
    assert gpu_runtime.activate() is None
    info = gpu_runtime.check()
    assert not info["ok"]  # asked for, but not used: the CI check fails


def test_which_gpus_it_helps():
    assert gpu_runtime.helps({"gpus": [GTX1060, RTX3060]}) == ["NVIDIA GeForce GTX 1060 6GB"]
    assert gpu_runtime.helps({"gpus": [RTX3060]}) == []
    kepler = {**GTX1060, "name": "GTX 780", "capability": [3, 5]}  # too old for the runtime too
    assert gpu_runtime.helps({"gpus": [kepler]}) == []
    assert gpu_runtime.helps({"gpus": [{**GTX1060, "capability": None}]}) == []  # probe of an older version
    assert gpu_runtime.helps(None) == []


def test_matches_the_app_and_the_build():
    """The runtime is built for the app's PyTorch and Python (requirements, CI)."""
    reqs = (ROOT / "requirements" / "torch-gpu.txt").read_text()
    torch_pin = re.search(r"^torch==([\d.]+)", reqs, re.M).group(1)
    vision_pin = re.search(r"^torchvision==([\d.]+)", reqs, re.M).group(1)
    assert gpu_runtime.TORCH_VERSION == torch_pin and gpu_runtime.TORCH_VERSION in gpu_runtime.LEGACY.name
    py = re.search(r'PYTHON_VERSION: "(\d+)\.(\d+)"', (ROOT / ".github" / "workflows" / "build.yml").read_text())
    tag = f"cp{py.group(1)}{py.group(2)}"
    names = [w.name for w in gpu_runtime.LEGACY.wheels]
    assert names[0].startswith(f"torch-{torch_pin}+cu126-{tag}-") and names[1].startswith(
        f"torchvision-{vision_pin}+cu126-{tag}-")
    assert all(w.name.endswith("win_amd64.whl") and len(w.sha256) == 64 for w in gpu_runtime.LEGACY.wheels)
    assert all(w.url.endswith(w.name.replace("+", "%2B")) for w in gpu_runtime.LEGACY.wheels)


# ----------------------------------------------------------------------------- install


def _wheel(files: dict) -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        for name, data in files.items():
            zf.writestr(name, data)
    return buf.getvalue()


class _Files(BaseHTTPRequestHandler):
    files: dict = {}
    requests: list = []

    def do_GET(self):  # noqa: N802
        name = self.path.rsplit("/", 1)[-1]
        rng = self.headers.get("Range")
        _Files.requests.append((name, rng))
        data = _Files.files[name]
        start = int(rng.split("=")[1].split("-")[0]) if rng else 0
        body = data[start:]
        self.send_response(206 if rng else 200)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *args):
        pass


@pytest.fixture
def server():
    httpd = ThreadingHTTPServer(("127.0.0.1", 0), _Files)
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    _Files.files, _Files.requests = {}, []
    yield f"http://127.0.0.1:{httpd.server_address[1]}"
    httpd.shutdown()


def _runtime(server, torch_data=None) -> gpu_runtime.Runtime:
    torch_whl = torch_data or _wheel({"torch/__init__.py": "WHERE = 'runtime'\n", "torch/lib/c10.dll": b"x" * 5000,
                                      "torch-9.dist-info/METADATA": "Name: torch\n", "../evil.txt": "no"})
    vision_whl = _wheel({"torchvision/__init__.py": ""})
    _Files.files = {"torch.whl": torch_whl, "vision.whl": vision_whl}
    wheels = tuple(gpu_runtime.Wheel(n, f"{server}/{n}", hashlib.sha256(d).hexdigest(), len(d))
                   for n, d in _Files.files.items())
    return gpu_runtime.Runtime(name="torch-test-cu126", cuda="12.6", min_capability=(5, 0), below=(7, 5),
                               wheels=wheels, unpacked=10_000)


def test_install_resume_and_check(server, tmp_path):
    rt = _runtime(server)
    root = tmp_path / "runtimes"
    part = root / ".partial"
    part.mkdir(parents=True)
    (part / "torch.whl").write_bytes(_Files.files["torch.whl"][:1000])  # interrupted before
    phases, seen = [], []
    folder = gpu_runtime.install(rt, root=root, progress=lambda d, t: seen.append((d, t)),
                                 phase=lambda p: phases.append(p))
    assert folder == root / rt.name and (folder / "torch" / "__init__.py").is_file()
    assert (folder / "torch" / "lib" / "c10.dll").stat().st_size == 5000
    assert not (tmp_path / "evil.txt").exists() and not (root / "evil.txt").exists()
    assert ("torch.whl", "bytes=1000-") in _Files.requests  # continued
    assert gpu_runtime.is_installed(rt, root) and not part.exists() and not (root / f"{rt.name}.tmp").exists()
    assert phases[0] == "download" and "check" in phases and phases[-1] == "unpack"
    assert seen[-1][0] == seen[-1][1]


def test_a_damaged_download_is_refused(server, tmp_path):
    rt = _runtime(server)
    bad = gpu_runtime.Wheel("torch.whl", rt.wheels[0].url, "0" * 64, rt.wheels[0].size)
    rt = gpu_runtime.Runtime(**{**rt.__dict__, "wheels": (bad, rt.wheels[1])})
    with pytest.raises(UserError) as err:
        gpu_runtime.install(rt, root=tmp_path)
    assert err.value.code == "runtime_checksum" and not (tmp_path / ".partial" / "torch.whl").exists()
    assert not gpu_runtime.is_installed(rt, tmp_path)


def test_cancel_keeps_the_partial_download(server, tmp_path):
    rt = _runtime(server, torch_data=_wheel({"torch/lib/big.dll": os.urandom(3_000_000)}))
    calls = []
    with pytest.raises(InterruptedError):
        gpu_runtime.install(rt, root=tmp_path, progress=lambda d, t: calls.append(d), cancel=lambda: bool(calls))
    assert (tmp_path / ".partial" / "torch.whl").stat().st_size > 0
    assert not gpu_runtime.is_installed(rt, tmp_path)


def test_remove_and_cleanup(tmp_path, monkeypatch):
    monkeypatch.setitem(gpu_runtime._state, "site", None)
    current = _fake_runtime(tmp_path / gpu_runtime.LEGACY.name)
    old = _fake_runtime(tmp_path / "torch-2.10.0-cu126", torch_version="2.10.0")
    (tmp_path / "half.tmp").mkdir()
    assert gpu_runtime.cleanup(tmp_path) == 2
    assert current.is_dir() and not old.exists() and not (tmp_path / "half.tmp").exists()
    monkeypatch.setitem(gpu_runtime._state, "site", current)  # in use: only switched off
    assert not gpu_runtime.remove(root=tmp_path) and current.is_dir()
    assert not gpu_runtime.is_installed(root=tmp_path)
    monkeypatch.setitem(gpu_runtime._state, "site", None)  # the next start
    assert gpu_runtime.cleanup(tmp_path) == 1 and not current.exists()


# ----------------------------------------------------------------------------- precision


def test_precision_setting(user_data, monkeypatch):
    import torch

    from clipasso_studio.engine import precision

    monkeypatch.delenv(precision.ENV, raising=False)
    assert precision.gpu_dtype("cuda") == torch.float16 and precision.gpu_dtype("cpu") == torch.float32
    app = user_data / "CLIPassoStudio"
    app.mkdir(parents=True, exist_ok=True)
    (app / "settings.json").write_text(json.dumps({precision.SETTING: "fp32"}))
    assert precision.gpu_dtype("cuda") == torch.float32 and not precision.half_precision("cuda")
    monkeypatch.setenv(precision.ENV, "auto")
    assert precision.half_precision(torch.device("cuda", 0))


# ----------------------------------------------------------------------------- the window


@pytest.fixture
def gui(qapp, user_data, monkeypatch):
    from clipasso_studio.gui import app_settings as settings_module
    from clipasso_studio.gui import gpu_runtime_ui

    settings_module._instance = None
    monkeypatch.setitem(gpu_runtime._state, "site", None)
    monkeypatch.setattr(gpu_runtime_ui, "available_here", lambda: True)
    yield gpu_runtime_ui
    settings_module._instance = None


def test_offered_once(gui, monkeypatch):
    from clipasso_studio.gui.app_settings import app_settings

    info = {"gpus": [GTX1060]}
    assert gui.should_offer(info) == ["NVIDIA GeForce GTX 1060 6GB"]
    assert gui.should_offer({"gpus": [RTX3060]}) == []
    asked, loaded = [], []
    monkeypatch.setattr(gui, "ask", lambda parent, name, again: asked.append((name, again)) or "never")
    monkeypatch.setattr(gui, "download", lambda parent: loaded.append(1) or True)
    assert gui.offer(None, info) == "never" and asked == [("NVIDIA GeForce GTX 1060 6GB", False)]
    assert gui.should_offer(info) == [] and gui.offer(None, info) is None  # not again
    app_settings().set(gui.DISMISSED, "")
    app_settings().set(gpu_runtime.SETTING, "torch-2.10.0-cu126")  # on for an earlier version
    monkeypatch.setattr(gui, "ask", lambda parent, name, again: asked.append((name, again)) or "load")
    assert gui.offer(None, info) == "load" and asked[-1][1] is True and loaded == [1]
    monkeypatch.setattr(gui, "available_here", lambda: False)  # the CPU edition: never
    assert gui.should_offer(info) == []


def test_download_dialog(gui, monkeypatch, tmp_path):
    seen = {}

    def fake_install(root=None, progress=None, cancel=None, phase=None):
        phase("download")
        progress(50, 100)
        phase("unpack")
        progress(100, 100)
        seen["done"] = True
        return str(tmp_path / "rt")

    monkeypatch.setattr(gpu_runtime, "install", fake_install)
    restarts = []
    monkeypatch.setattr(gui, "ask_restart", lambda parent: restarts.append(1))
    from clipasso_studio.gui.app_settings import app_settings

    assert gui.download(None) and seen["done"] and restarts == [1]
    assert app_settings().get(gpu_runtime.SETTING) == gpu_runtime.LEGACY.name


def test_settings_row(gui, monkeypatch):
    from clipasso_studio import paths
    from clipasso_studio.gui.app_settings import app_settings
    from clipasso_studio.gui.pages.other_pages import SettingsPage

    page = SettingsPage()
    assert page.refresh_gpu_runtime() == "missing"
    assert page.gpurt_box.isVisibleTo(page) and page.gpurt_load.isVisibleTo(page)
    assert not page.gpurt_switch.isVisibleTo(page)
    _fake_runtime(paths.user_data_dir() / "runtimes" / gpu_runtime.LEGACY.name)
    app_settings().set(gpu_runtime.SETTING, gpu_runtime.LEGACY.name)
    assert page.refresh_gpu_runtime() == "restart" and page.gpurt_switch.isChecked()
    restarts = []
    monkeypatch.setattr(gui, "ask_restart", lambda parent: restarts.append(1))
    page.gpurt_switch.setChecked(False)
    assert app_settings().get(gpu_runtime.SETTING) == "" and restarts == [1]
    assert page.refresh_gpu_runtime() == "off"
    assert page._gpurt_remove(confirm=False) and page.refresh_gpu_runtime() == "missing"
    assert not page.gpu_precision.isChecked() and page.gpu_precision_desc.text()  # a switch with its description
    page.gpu_precision.setChecked(True)
    assert app_settings().get("gpu_precision") == "fp32"
    page.gpu_precision.setChecked(False)
    assert app_settings().get("gpu_precision") == "auto"
    monkeypatch.setattr(gui, "available_here", lambda: False)  # the CPU edition without the add-on
    page.refresh_gpu_runtime()
    assert not page.gpurt_box.isVisibleTo(page)


def test_probe_cache_follows_the_runtime(gui):
    from clipasso_studio import __version__
    from clipasso_studio.gui import hardware
    from clipasso_studio.gui.app_settings import app_settings

    app_settings().set("hardware", {"version": __version__, "cuda": True, "gpus": [GTX1060], "runtime": ""})
    assert hardware.cached() is not None and not hardware.has_cuda()  # a GPU it cannot use
    app_settings().set("hardware", {"version": __version__, "cuda": True, "gpus": [GTX1060],
                                    "runtime": gpu_runtime.LEGACY.name})
    assert hardware.cached() is None  # probed with the add-on, which is not active now: probe again
