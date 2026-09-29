"""Model registry: bundled weights, on-demand downloads and conversion.

All checkpoints are stored as plain ``state_dict`` files (no TorchScript) so they load with
``torch.load(weights_only=True)`` inside the frozen app. U2Net, DINO and VGG are stored
in float16 to keep the executable small and converted back to float32 when loaded.
SwiftSketch checkpoints are downloaded from the authors' Google Drive on first use and
stored as ``{"args": <args.json>, "state_dict": ...}`` in float32.
"""

from __future__ import annotations

import hashlib
import html
import json
import os
import re
import shutil
import tempfile
import urllib.parse
import urllib.request
import zipfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable

import torch

from .. import paths

ProgressFn = Callable[[int, int], None]

_OPENAI = "https://openaipublic.azureedge.net/clip/models/"
_OPENAI_BLOB = "https://openaipublic.blob.core.windows.net/clip/models/"

_CLIP_SOURCES = {
    "RN50": "afeb0e10f9e5a86da6080e35cf09123aca3b358a0c3e3b6c78a7b63bc04b6762/RN50.pt",
    "RN101": "8fa8567bab74a42d41c5915025a8e4538c3bdbe8804a470a72f30b0d94fab599/RN101.pt",
    "RN50x4": "7e526bd135e493cef0776de27d5f42653e6b4c8bf9e0f653bb11773263205fdd/RN50x4.pt",
    "RN50x16": "52378b407f34354e150460fe41077663dd5b39c54cd0bfd2b27167a4a06ec9aa/RN50x16.pt",
    "ViT-B/32": "40d365715913c9da98579312b702a82c18be219cc2a73407c4526f58eba950af/ViT-B-32.pt",
    "ViT-B/16": "5806e77cd80f8b59890b7e101eabd078d9fb84e6937f9e85e4ecb61988df416f/ViT-B-16.pt",
}


@dataclass(frozen=True)
class ModelSpec:
    key: str  # e.g. "clip:RN101", "u2net", "dino", "vgg16"
    filename: str  # relative to a models dir
    urls: tuple[str, ...]
    download_sha256: str | None  # checksum of the downloaded file (None = size check only)
    download_size: int
    stored_size_mb: int
    bundled: bool
    kind: str
    extra: dict = field(default_factory=dict)


def _clip_spec(name: str, bundled: bool, size: int, stored_mb: int) -> ModelSpec:
    src = _CLIP_SOURCES[name]
    return ModelSpec(
        key=f"clip:{name}",
        filename=f"clip/{name.replace('/', '-')}.pt",
        urls=(_OPENAI + src, _OPENAI_BLOB + src),
        download_sha256=src.split("/")[0],
        download_size=size,
        stored_size_mb=stored_mb,
        bundled=bundled,
        kind="clip",
    )


SPECS: dict[str, ModelSpec] = {s.key: s for s in (
    _clip_spec("RN101", True, 291_791_292, 290),
    _clip_spec("ViT-B/32", True, 353_976_522, 350),
    _clip_spec("RN50", False, 255_827_503, 255),
    _clip_spec("RN50x4", False, 421_854_225, 420),
    _clip_spec("RN50x16", False, 661_125_706, 660),
    _clip_spec("ViT-B/16", False, 350_837_078, 350),
    ModelSpec(
        key="u2net",
        filename="u2net/u2net_fp16.pt",
        urls=(
            "https://huggingface.co/flashingtt/U-2-Net/resolve/main/u2net.pth",
            "gdrive:1ao1ovG1Qtx4b7EoskHXmi2E9rp5CHLcZ",
        ),
        download_sha256=None,
        download_size=176_290_937,
        stored_size_mb=88,
        bundled=True,
        kind="u2net",
    ),
    ModelSpec(
        key="dino",
        filename="dino/dino_vits8_fp16.pt",
        urls=("https://dl.fbaipublicfiles.com/dino/dino_deitsmall8_pretrain/dino_deitsmall8_pretrain.pth",),
        download_sha256=None,
        download_size=86_728_949,
        stored_size_mb=44,
        bundled=True,
        kind="dino",
    ),
    ModelSpec(
        key="swiftsketch:diffusion",
        filename="swiftsketch/sketch_diffusion.pt",
        urls=("gdrive:19FryO99dCmz-Dw1jzeZITUI0uuksiOA-",),
        download_sha256=None,
        download_size=357_580_707,
        stored_size_mb=144,
        bundled=False,
        kind="swiftsketch",
    ),
    ModelSpec(
        key="swiftsketch:refine",
        filename="swiftsketch/refinement_network.pt",
        urls=("gdrive:1OrLzwaJXZ4SlDw3hqn71Yg1L01ytLv2x",),
        download_sha256=None,
        download_size=356_303_267,
        stored_size_mb=144,
        bundled=False,
        kind="swiftsketch",
    ),
    ModelSpec(
        key="vgg16",
        filename="vgg/vgg16_features_fp16.pt",
        urls=("https://download.pytorch.org/models/vgg16-397923af.pth",),
        download_sha256=None,
        download_size=553_433_881,
        stored_size_mb=30,
        bundled=True,
        kind="vgg",
    ),
)}


def clip_key(name: str) -> str:
    return f"clip:{name}"


def find(spec_key: str) -> Path | None:
    """Location of an installed model file, or None."""
    spec = SPECS[spec_key]
    for base in (paths.bundled_models_dir(), paths.downloaded_models_dir()):
        candidate = base / spec.filename
        if candidate.is_file():
            return candidate
    return None


def is_available(spec_key: str) -> bool:
    return find(spec_key) is not None


def require(spec_key: str) -> Path:
    found = find(spec_key)
    if found is None:
        raise ModelMissingError(spec_key)
    return found


class ModelMissingError(RuntimeError):
    def __init__(self, spec_key: str):
        super().__init__(f"Model '{spec_key}' is not installed. Download it on the 'Models' page.")
        self.spec_key = spec_key


# ----------------------------------------------------------------------------- download


def _sha256(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


_GDRIVE_DOWNLOAD = "https://drive.usercontent.google.com/download"


def _open(url: str):
    req = urllib.request.Request(url, headers={"User-Agent": "CLIPassoStudio"})
    return urllib.request.urlopen(req, timeout=60)


def _open_gdrive(file_id: str):
    """Open a public Google Drive file for streaming.

    Files larger than ~100 MB answer with a "can't scan this file for viruses" page first; its
    download form (hidden inputs id / export / confirm / uuid) leads to the actual file.
    """
    url = f"{_GDRIVE_DOWNLOAD}?" + urllib.parse.urlencode({"id": file_id, "export": "download"})
    for _ in range(3):
        resp = _open(url)
        if "text/html" not in resp.headers.get("Content-Type", ""):
            return resp
        page = resp.read().decode("utf-8", "replace")
        resp.close()
        form = re.search(r'<form[^>]*id="download-form"[^>]*action="([^"]+)"', page)
        if not form:
            raise RuntimeError("Google Drive refused the download (daily quota exceeded?) – try again later "
                               "or download the file manually and use 'Import' on the Models page")
        fields = dict(re.findall(r'<input type="hidden" name="([^"]+)" value="([^"]*)"', page))
        url = html.unescape(form.group(1)) + "?" + urllib.parse.urlencode(
            {k: html.unescape(v) for k, v in fields.items()})
    raise RuntimeError("Google Drive did not start the download")


def _download_url(url: str, dest: Path, progress: ProgressFn | None, cancel: Callable[[], bool] | None) -> None:
    src = _open_gdrive(url.split(":", 1)[1]) if url.startswith("gdrive:") else _open(url)
    with src, open(dest, "wb") as out:
        total = int(src.headers.get("Content-Length") or 0)
        done = 0
        while True:
            if cancel and cancel():
                raise InterruptedError("download cancelled")
            buf = src.read(1 << 20)
            if not buf:
                break
            out.write(buf)
            done += len(buf)
            if progress:
                progress(done, total)


def download_raw(spec: ModelSpec, workdir: Path, progress: ProgressFn | None = None,
                 cancel: Callable[[], bool] | None = None) -> Path:
    errors = []
    for url in spec.urls:
        target = workdir / "download.bin"
        try:
            _download_url(url, target, progress, cancel)
        except InterruptedError:
            raise
        except Exception as exc:  # try the next mirror
            errors.append(f"{url}: {exc}")
            continue
        size = target.stat().st_size
        if spec.download_sha256:
            digest = _sha256(target)
            if digest != spec.download_sha256:
                errors.append(f"{url}: sha256 mismatch ({digest})")
                continue
        elif abs(size - spec.download_size) > 1024:
            errors.append(f"{url}: unexpected size {size}")
            continue
        return target
    raise RuntimeError(f"Could not download {spec.key}:\n" + "\n".join(errors))


def _half(state: dict) -> dict:
    """float16 copy of a state dict; tensors that do not fit into float16 (e.g. large
    BatchNorm statistics) stay float32."""
    out = {}
    for k, v in state.items():
        if torch.is_tensor(v) and v.is_floating_point() and v.numel():
            h = v.half()
            fits = bool(torch.isfinite(h).all()) and float(v.abs().max()) < 6.0e4
            out[k] = h if fits and "running_" not in k else v.float()
        else:
            out[k] = v
    return out


def convert(spec: ModelSpec, raw: Path, dest: Path) -> None:
    """Turn a downloaded checkpoint into the stored format."""
    dest.parent.mkdir(parents=True, exist_ok=True)
    if spec.kind == "clip":
        try:
            model = torch.jit.load(str(raw), map_location="cpu")
            state = model.state_dict()
        except RuntimeError:
            state = torch.load(str(raw), map_location="cpu", weights_only=True)
        state = {k: v for k, v in state.items() if k not in ("input_resolution", "context_length", "vocab_size")}
    elif spec.kind == "u2net":
        state = _half(torch.load(str(raw), map_location="cpu", weights_only=True))
    elif spec.kind == "dino":
        state = torch.load(str(raw), map_location="cpu", weights_only=True)
        state = _half(state.get("teacher", state) if isinstance(state, dict) and "teacher" in state else state)
    elif spec.kind == "vgg":
        state = torch.load(str(raw), map_location="cpu", weights_only=True)
        state = _half({k: v for k, v in state.items() if k.startswith("features.")})
    elif spec.kind == "swiftsketch":
        state = _swiftsketch_checkpoint(raw)
    else:
        raise ValueError(spec.kind)
    tmp = dest.with_suffix(".tmp")
    torch.save(state, str(tmp))
    os.replace(tmp, dest)


def _swiftsketch_checkpoint(raw: Path) -> dict:
    """Official SwiftSketch zip (args.json, model*.pt, opt*.pt) -> {"args", "state_dict"}.

    The optimizer state is dropped, as are the sinusoidal position tables (recomputed by the model).
    """
    with zipfile.ZipFile(raw) as zf:
        names = zf.namelist()
        args_name = next(n for n in names if n.rsplit("/", 1)[-1] == "args.json")
        model_name = max((n for n in names if re.fullmatch(r"model\d+\.pt", n.rsplit("/", 1)[-1])),
                         key=lambda n: int(re.sub(r"\D", "", n.rsplit("/", 1)[-1])))
        args = json.loads(zf.read(args_name).decode("utf-8"))
        with tempfile.TemporaryDirectory() as tmp:
            path = zf.extract(model_name, tmp)
            state = torch.load(path, map_location="cpu", weights_only=True)
    state = {k: v.float() if torch.is_tensor(v) and v.is_floating_point() else v
             for k, v in state.items() if not k.endswith("sequence_pos_encoder.pe")}
    return {"args": args, "state_dict": state}


def install(spec_key: str, dest_root: Path | None = None, progress: ProgressFn | None = None,
            cancel: Callable[[], bool] | None = None) -> Path:
    """Download + convert a model into ``dest_root`` (default: the user's model folder)."""
    spec = SPECS[spec_key]
    dest_root = dest_root or paths.downloaded_models_dir()
    dest = dest_root / spec.filename
    with tempfile.TemporaryDirectory(dir=dest_root) as tmp:
        raw = download_raw(spec, Path(tmp), progress, cancel)
        convert(spec, raw, dest)
    return dest


def install_from_file(spec_key: str, raw: str | Path, dest_root: Path | None = None) -> Path:
    """Convert a manually downloaded checkpoint (e.g. when Google Drive's quota is exceeded)."""
    spec = SPECS[spec_key]
    dest = (dest_root or paths.downloaded_models_dir()) / spec.filename
    convert(spec, Path(raw), dest)
    return dest


def uninstall(spec_key: str) -> None:
    spec = SPECS[spec_key]
    target = paths.downloaded_models_dir() / spec.filename
    if target.is_file():
        target.unlink()


def load_state(spec_key: str) -> dict:
    state = torch.load(str(require(spec_key)), map_location="cpu", weights_only=True)
    return state


def copy_tree(src: Path, dst: Path) -> None:
    shutil.copytree(src, dst, dirs_exist_ok=True)
