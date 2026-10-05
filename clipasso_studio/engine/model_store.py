"""Model registry: bundled weights, on-demand downloads and conversion.

All checkpoints are stored as plain ``state_dict`` files (no TorchScript) so they load with
``torch.load(weights_only=True)`` inside the frozen app. U2Net, DINO and VGG are stored
in float16 to keep the executable small and converted back to float32 when loaded.
SwiftSketch checkpoints are downloaded from the authors' Google Drive on first use and
stored as ``{"args": <args.json>, "state_dict": ...}`` in float32; the LaMa inpainting network of
SceneSketch comes as TorchScript and is converted to a float16 state dict.
"""

from __future__ import annotations

import hashlib
import html
import json
import os
import re
import shutil
import tempfile
import time
import urllib.error
import urllib.parse
import urllib.request
import zipfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable


from .. import paths
from ..fileops import ensure_space, folder_size, move_entries  # noqa: F401 (folder_size: used by the GUI)
from .errors import UserError

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


@dataclass(frozen=True)
class HFFile:
    remote: str  # path inside the Hugging Face repository
    local: str  # path inside the model folder
    size: int | None = None  # expected download size (checked when given)
    fp16: bool = False  # store floating point tensors as float16


_HF = "https://huggingface.co"


def _hf_spec(key: str, folder: str, repo: str, revision: str, files, stored_mb: int) -> ModelSpec:
    """A model made of several files of a Hugging Face repository (pinned revision), stored in
    ``folder``; ``folder/manifest.json`` marks a complete installation."""
    files = tuple(f if isinstance(f, HFFile) else HFFile(*f) for f in files)
    return ModelSpec(
        key=key,
        filename=f"{folder}/manifest.json",
        urls=(f"{_HF}/{repo}",),
        download_sha256=None,
        download_size=sum(f.size or 0 for f in files),
        stored_size_mb=stored_mb,
        bundled=False,
        kind="hf",
        extra={"repo": repo, "revision": revision, "files": files},
    )


def _controlnet_spec(condition: str, repo: str, revision: str) -> ModelSpec:
    return _hf_spec(f"controlnet:{condition}", f"controlsketch/controlnet-{condition}", repo, revision, (
        ("config.json", "config.json"),
        ("diffusion_pytorch_model.safetensors", "diffusion_pytorch_model.safetensors", 1_445_157_124, True),
    ), 723)


_SD15 = ("stable-diffusion-v1-5/stable-diffusion-v1-5", "451f4fe16113bff5a5d2269ed5ad43b0592e9a14")
_SDXL = ("stabilityai/stable-diffusion-xl-base-1.0", "462165984030d82259a11f4367a4eed129e94a7b")


def _tokenizer_files(folder: str) -> tuple:
    return tuple((f"{folder}/{n}", f"{folder}/{n}") for n in
                 ("merges.txt", "special_tokens_map.json", "tokenizer_config.json", "vocab.json"))


CONTROLSKETCH_SPECS = (
    # Stable Diffusion 1.5 (CreativeML OpenRAIL-M) – UNet, VAE, text encoder for the SDS loss
    _hf_spec("sd15", "controlsketch/sd15", *_SD15, (
        ("scheduler/scheduler_config.json", "scheduler/scheduler_config.json"),
        ("text_encoder/config.json", "text_encoder/config.json"),
        ("text_encoder/model.fp16.safetensors", "text_encoder/model.safetensors", 246_144_864),
        *_tokenizer_files("tokenizer"),
        ("unet/config.json", "unet/config.json"),
        ("unet/diffusion_pytorch_model.fp16.safetensors", "unet/diffusion_pytorch_model.safetensors",
         1_719_125_304),
        ("vae/config.json", "vae/config.json"),
        ("vae/diffusion_pytorch_model.fp16.safetensors", "vae/diffusion_pytorch_model.safetensors", 167_335_342),
    ), 2135),
    # ControlNet 1.0 models (OpenRAIL) – one per condition
    _controlnet_spec("depth", "lllyasviel/sd-controlnet-depth", "35e42a3ea49845b3c76f202f145f257b9fb1b7d4"),
    _controlnet_spec("canny", "lllyasviel/sd-controlnet-canny", "7f2f69197050967007f6bbd23ab5e52f0384162a"),
    _controlnet_spec("hed", "lllyasviel/sd-controlnet-hed", "04473d9334ab44908daa66107bbfb6f710aa056d"),
    _controlnet_spec("scribble", "lllyasviel/sd-controlnet-scribble", "864edcd5ccc6ee2695eeebea5b4512100c83e7b3"),
    _controlnet_spec("seg", "lllyasviel/sd-controlnet-seg", "ecdcb5645b5099c9a7500a504fb9ab3f743c4d96"),
    _controlnet_spec("normal", "lllyasviel/sd-controlnet-normal", "1cbed9b3ca84422e4a2f23c14b9f5a114742b31d"),
    # Tiny AutoEncoder for SD (MIT): the turbo mode encodes the sketch with it instead of the SD VAE
    _hf_spec("taesd", "controlsketch/taesd", "madebyollin/taesd", "614f76814bbe30edbe2e627ace1c2234c81a2c0e", (
        ("config.json", "config.json"),
        ("diffusion_pytorch_model.safetensors", "diffusion_pytorch_model.safetensors", 9_793_292),
    ), 10),
    # condition detectors
    _hf_spec("dpt-hybrid", "controlsketch/dpt-hybrid-midas", "Intel/dpt-hybrid-midas",
             "11eaf7a1cf4bd70740697dbc216f98980c0aeb03", (
                 ("config.json", "config.json"),
                 ("pytorch_model.bin", "model.safetensors", 489_648_389, True),
             ), 245),
    _hf_spec("hed", "controlsketch/hed", "lllyasviel/Annotators", "982e7edaec38759d914a963c48c4726685de7d96", (
        ("ControlNetHED.pth", "ControlNetHED.safetensors", 29_444_406),
    ), 29),
    _hf_spec("upernet", "controlsketch/upernet-convnext-small", "openmmlab/upernet-convnext-small",
             "550b68d291f9a7e4874065c6eec0676b2ba821e6", (
                 ("config.json", "config.json"),
                 ("pytorch_model.bin", "model.safetensors", 327_701_893, True),
             ), 164),
    # automatic caption when no caption is given (BLIP instead of the 15 GB BLIP-2 OPT-2.7b)
    _hf_spec("blip", "controlsketch/blip-image-captioning-large", "Salesforce/blip-image-captioning-large",
             "353689b859fcf0523410b1806dace5fb46ecdf41", (
                 ("config.json", "config.json"),
                 ("preprocessor_config.json", "preprocessor_config.json"),
                 ("special_tokens_map.json", "special_tokens_map.json"),
                 ("tokenizer.json", "tokenizer.json"),
                 ("tokenizer_config.json", "tokenizer_config.json"),
                 ("vocab.txt", "vocab.txt"),
                 ("model.safetensors", "model.safetensors", 1_879_014_680, True),
             ), 940),
    # SDXL cross-attention for the stroke initialisation (attn_model = diffusion)
    _hf_spec("sdxl", "controlsketch/sdxl-base-1.0", *_SDXL, (
        ("model_index.json", "model_index.json"),
        ("scheduler/scheduler_config.json", "scheduler/scheduler_config.json"),
        ("text_encoder/config.json", "text_encoder/config.json"),
        ("text_encoder/model.fp16.safetensors", "text_encoder/model.safetensors", 246_144_152),
        ("text_encoder_2/config.json", "text_encoder_2/config.json"),
        ("text_encoder_2/model.fp16.safetensors", "text_encoder_2/model.safetensors", 1_389_382_176),
        *_tokenizer_files("tokenizer"),
        *_tokenizer_files("tokenizer_2"),
        ("unet/config.json", "unet/config.json"),
        ("unet/diffusion_pytorch_model.fp16.safetensors", "unet/diffusion_pytorch_model.safetensors",
         5_135_149_760),
        ("vae/config.json", "vae/config.json"),
        ("vae/diffusion_pytorch_model.fp16.safetensors", "vae/diffusion_pytorch_model.safetensors", 167_335_342),
    ), 6940),
)

# BiRefNet (MIT) for the object mask of all methods – the general model (Swin-L backbone) and the
# lite one (Swin-T); stored as float16 safetensors for the port in engine/birefnet.py
MASK_SPECS = (
    _hf_spec("birefnet", "masking/birefnet", "ZhengPeng7/BiRefNet", "e2bf8e4460fc8fa32bba5ea4d94b3233d367b0e4", (
        ("model.safetensors", "model.safetensors", 444_473_596, True),
    ), 444),
    _hf_spec("birefnet-lite", "masking/birefnet-lite", "ZhengPeng7/BiRefNet_lite",
             "aa62cd87eafb9cc43056d08ef3615a14628b831d", (
                 ("model.safetensors", "model.safetensors", 177_634_392, True),
             ), 89),
)

# BlazeFace (MediaPipe's face detector, Apache-2.0; PyTorch weights by M. Hollemans, Apache-2.0) for the portrait
# mode of the detail brush: the eyes, nose and mouth of a face get more detail
PORTRAIT_SPEC = ModelSpec(
    key="blazeface",
    filename="blazeface/blazeface.pt",
    urls=("https://raw.githubusercontent.com/hollance/BlazeFace-PyTorch/852bfd8e3d44ed6775761105bdcead4ef389a538/"
          "blazeface.pth",),
    download_sha256="54ecff653feaaaf1f7d44b6aff28fd2fc50e483a4e847563b6dd261369c43ba4",
    download_size=420_224,
    stored_size_mb=1,
    bundled=True,  # 0.4 MB: the portrait mode works offline from the start
    kind="blazeface",
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
        download_sha256="10025a17f49cd3208afc342b589890e402ee63123d6f2d289a4a0903695cce58",
        download_size=176_290_937,
        stored_size_mb=88,
        bundled=True,
        kind="u2net",
    ),
    ModelSpec(
        key="dino",
        filename="dino/dino_vits8_fp16.pt",
        urls=("https://dl.fbaipublicfiles.com/dino/dino_deitsmall8_pretrain/dino_deitsmall8_pretrain.pth",),
        download_sha256="55c8b267f479b614ec20858947ce361ba804846c193e20be74263a096bb6d75e",
        download_size=86_728_949,
        stored_size_mb=44,
        bundled=True,
        kind="dino",
    ),
    ModelSpec(
        key="swiftsketch:diffusion",
        filename="swiftsketch/sketch_diffusion.pt",
        urls=("gdrive:19FryO99dCmz-Dw1jzeZITUI0uuksiOA-",),
        download_sha256="d1be95d1de0e35806b31ac854edf0833cceb720afdaf145c3f3ad9b2f4fb5fde",
        download_size=357_580_707,
        stored_size_mb=144,
        bundled=False,
        kind="swiftsketch",
    ),
    ModelSpec(
        key="swiftsketch:refine",
        filename="swiftsketch/refinement_network.pt",
        urls=("gdrive:1OrLzwaJXZ4SlDw3hqn71Yg1L01ytLv2x",),
        download_sha256="c4af9d11b8116e122b03ad5804f4a81eaf02fc6ec6f189b88ad09ae7ee02e17a",
        download_size=356_303_267,
        stored_size_mb=144,
        bundled=False,
        kind="swiftsketch",
    ),
    # LaMa (big-lama, Apache-2.0) for the SceneSketch background; the file is the TorchScript export
    # distributed by IOPaint / lama-cleaner, stored as a float16 state dict for the port in
    # engine/methods/scenesketch/lama.py
    ModelSpec(
        key="lama",
        filename="scenesketch/big-lama_fp16.pt",
        urls=("https://github.com/Sanster/models/releases/download/add_big_lama/big-lama.pt",),
        download_sha256="344c77bbcb158f17dd143070d1e789f38a66c04202311ae3a258ef66667a9ea9",
        download_size=205_669_692,
        stored_size_mb=103,
        bundled=False,
        kind="lama",
    ),
    ModelSpec(
        key="vgg16",
        filename="vgg/vgg16_features_fp16.pt",
        urls=("https://download.pytorch.org/models/vgg16-397923af.pth",),
        download_sha256="397923af8e79cdbb6a7127f12361acd7a2f83e06b05044ddf496e83de57a5bf0",
        download_size=553_433_881,
        stored_size_mb=30,
        bundled=True,
        kind="vgg",
    ),
)}
SPECS.update({s.key: s for s in CONTROLSKETCH_SPECS})
SPECS.update({s.key: s for s in MASK_SPECS})
SPECS[PORTRAIT_SPEC.key] = PORTRAIT_SPEC


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


def model_dir(spec_key: str) -> Path:
    """Folder of an installed multi-file model (kind 'hf')."""
    return require(spec_key).parent


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
            raise UserError("gdrive_quota", "Google Drive refused the download (daily quota exceeded?) – try "
                            "again later or download the file manually and use 'Import' on the Models page")
        fields = dict(re.findall(r'<input type="hidden" name="([^"]+)" value="([^"]*)"', page))
        url = html.unescape(form.group(1)) + "?" + urllib.parse.urlencode(
            {k: html.unescape(v) for k, v in fields.items()})
    raise UserError("gdrive_no_start", "Google Drive did not start the download")


def _download_url(url: str, dest: Path, progress: ProgressFn | None, cancel: Callable[[], bool] | None,
                  offset: int = 0) -> None:
    """Stream ``url`` into ``dest``; with ``offset`` > 0 the download resumes (HTTP range request)."""
    if url.startswith("gdrive:"):
        src = _open_gdrive(url.split(":", 1)[1])
        offset = 0
    elif offset:
        req = urllib.request.Request(url, headers={"User-Agent": "CLIPassoStudio", "Range": f"bytes={offset}-"})
        try:
            src = urllib.request.urlopen(req, timeout=60)
        except urllib.error.HTTPError as exc:
            if exc.code == 416:  # nothing left to download: the file is already complete
                return
            raise
        if src.status != 206:  # server ignored the range
            offset = 0
    else:
        src = _open(url)
    with src, open(dest, "ab" if offset else "wb") as out:
        length = int(src.headers.get("Content-Length") or 0)
        total = length + offset
        done = offset
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
    if length and done < total:  # http.client ends a dropped connection like a finished download
        raise ConnectionError(f"connection lost after {done} of {total} bytes")


def partial_dir(dest_root: Path | None = None) -> Path:
    """Where unfinished downloads wait until they are resumed."""
    return (dest_root or paths.downloaded_models_dir()) / ".partial"


def _safe_name(key: str) -> str:
    return re.sub(r"[^A-Za-z0-9._-]+", "_", key)


def download_raw(spec: ModelSpec, workdir: Path, progress: ProgressFn | None = None,
                 cancel: Callable[[], bool] | None = None, attempts: int = 3) -> Path:
    """Download the checkpoint of ``spec`` to ``workdir/<key>.part`` and verify it.

    An interrupted download (network error, cancel, app closed) continues from the partial file the
    next time (HTTP range request; Google Drive starts over); network errors are retried ``attempts``
    times per mirror before the next mirror is tried."""
    workdir.mkdir(parents=True, exist_ok=True)
    target = workdir / f"{_safe_name(spec.key)}.part"
    meta = target.with_suffix(".json")
    errors = []
    for url in spec.urls:
        # every mirror serves the same file: a partial download of another mirror continues here
        info = {"size": spec.download_size, "sha256": spec.download_sha256}
        try:
            saved = json.loads(meta.read_text(encoding="utf-8"))
            same = {k: saved.get(k) for k in info} == info
        except (OSError, ValueError, AttributeError):
            same = False
        if not same:  # a different file: start over
            target.unlink(missing_ok=True)
        meta.write_text(json.dumps({**info, "url": url}), encoding="utf-8")
        failure = None
        for attempt in range(attempts):
            offset = target.stat().st_size if target.exists() else 0
            try:
                _download_url(url, target, progress, cancel, offset=offset)
                failure = None
                break
            except InterruptedError:
                raise  # cancelled: the partial file stays for the next attempt
            except Exception as exc:  # network error: try again from where it stopped
                failure = exc
                if attempt < attempts - 1:
                    time.sleep(min(2 ** attempt, 8))
        if failure is not None:
            errors.append(f"{url}: {failure}")
            continue
        if progress:
            progress(0, 0)  # downloaded; checking (and converting) takes a moment without measurable progress
        size = target.stat().st_size
        if spec.download_sha256:
            digest = _sha256(target)
            if digest != spec.download_sha256:
                errors.append(f"{url}: sha256 mismatch ({digest})")
                target.unlink(missing_ok=True)
                continue
        elif abs(size - spec.download_size) > 1024:
            errors.append(f"{url}: unexpected size {size}")
            target.unlink(missing_ok=True)
            continue
        return target
    raise UserError("download_failed", f"Could not download {spec.key}:\n" + "\n".join(errors), model=spec.key,
                    details="\n".join(errors))


def _drop_partial(raw: Path) -> None:
    raw.unlink(missing_ok=True)
    raw.with_suffix(".json").unlink(missing_ok=True)


def _half(state: dict) -> dict:
    """float16 copy of a state dict; tensors that do not fit into float16 (e.g. large
    BatchNorm statistics) stay float32."""
    import torch  # here: the GUI imports this module and starts without PyTorch

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
    import torch  # here: the GUI imports this module and starts without PyTorch

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
    elif spec.kind == "blazeface":
        state = torch.load(str(raw), map_location="cpu", weights_only=True)
    elif spec.kind == "lama":
        model = torch.jit.load(str(raw), map_location="cpu")
        state = _half({k[len("generator."):]: v for k, v in model.state_dict().items() if k.startswith("generator.")})
    else:
        raise ValueError(spec.kind)
    tmp = dest.with_suffix(".tmp")
    torch.save(state, str(tmp))
    os.replace(tmp, dest)


def _swiftsketch_checkpoint(raw: Path) -> dict:
    """Official SwiftSketch zip (args.json, model*.pt, opt*.pt) -> {"args", "state_dict"}.

    The optimizer state is dropped, as are the sinusoidal position tables (recomputed by the model).
    """
    import torch  # here: the GUI imports this module and starts without PyTorch

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


def space_needed(spec: ModelSpec, dest_root: Path) -> int:
    """Bytes an install still needs on the drive: what is left to download, plus the converted model
    (the raw download is removed only after the conversion)."""
    part = partial_dir(dest_root)
    if spec.kind == "hf":
        raw = part / _safe_name(spec.key)
        have = folder_size(raw) if raw.is_dir() else 0
    else:
        raw = part / f"{_safe_name(spec.key)}.part"
        have = raw.stat().st_size if raw.is_file() else 0
    return max(spec.download_size - have, 0) + spec.stored_size_mb * 1_000_000


def install(spec_key: str, dest_root: Path | None = None, progress: ProgressFn | None = None,
            cancel: Callable[[], bool] | None = None) -> Path:
    """Download + convert a model into ``dest_root`` (default: the user's model folder)."""
    spec = SPECS[spec_key]
    dest_root = dest_root or paths.downloaded_models_dir()
    ensure_space(dest_root, space_needed(spec, dest_root), spec.key)
    if spec.kind == "hf":
        return _install_hf(spec, dest_root, progress, cancel)
    dest = dest_root / spec.filename
    raw = download_raw(spec, partial_dir(dest_root), progress, cancel)
    convert(spec, raw, dest)
    _drop_partial(raw)
    return dest


def _hf_download(url: str, target: Path, progress: ProgressFn | None, cancel, attempts: int = 4,
                 size: int | None = None) -> None:
    """Download with up to ``attempts`` tries, resuming interrupted transfers (also a partial file
    left by an earlier, interrupted install)."""
    target.parent.mkdir(parents=True, exist_ok=True)
    if target.exists() and (not size or target.stat().st_size > size):
        target.unlink()  # unknown or impossible size: start over
    for attempt in range(attempts):
        offset = target.stat().st_size if target.exists() else 0
        if size and offset == size:
            return
        try:
            _download_url(url, target, progress, cancel, offset=offset)
            return
        except InterruptedError:
            raise
        except Exception:
            if attempt == attempts - 1:
                raise
            time.sleep(2 ** attempt)


def _convert_hf_file(src: Path, dst: Path, f: HFFile) -> None:
    import torch  # here: the GUI imports this module and starts without PyTorch

    dst.parent.mkdir(parents=True, exist_ok=True)
    if not f.local.endswith(".safetensors"):
        shutil.copyfile(src, dst)
        return
    from safetensors.torch import load_file, save_file

    if src.suffix == ".safetensors":
        state = load_file(str(src))
    else:
        state = torch.load(str(src), map_location="cpu", weights_only=True)
        state = state.get("state_dict", state) if isinstance(state, dict) else state
    out = {}
    for k, v in state.items():
        if f.fp16 and v.is_floating_point():
            v = v.half()
        out[k] = v.contiguous().clone()  # no shared storage (tied weights) for safetensors
    del state
    save_file(out, str(dst), metadata={"format": "pt"})


def _install_hf(spec: ModelSpec, dest_root: Path, progress: ProgressFn | None,
                cancel: Callable[[], bool] | None) -> Path:
    repo, revision, files = spec.extra["repo"], spec.extra["revision"], spec.extra["files"]
    dest = (dest_root / spec.filename).parent
    dest.parent.mkdir(parents=True, exist_ok=True)
    total = sum(f.size or 0 for f in files) or 1
    # the raw files wait in the partial folder, so an interrupted install continues where it stopped
    raw_dir = partial_dir(dest_root) / _safe_name(spec.key)
    stamp = raw_dir / "revision.txt"
    if raw_dir.exists() and (not stamp.is_file() or stamp.read_text(encoding="utf-8") != revision):
        shutil.rmtree(raw_dir)
    raw_dir.mkdir(parents=True, exist_ok=True)
    stamp.write_text(revision, encoding="utf-8")
    with tempfile.TemporaryDirectory(dir=dest.parent) as tmp:
        out_dir = Path(tmp) / "out"
        done = 0
        for f in files:
            target = raw_dir / f.remote
            base = done
            prog = (lambda d, t, base=base: progress(min(base + d, total), total)) if progress else None
            _hf_download(f"{_HF}/{repo}/resolve/{revision}/{f.remote}", target, prog, cancel, size=f.size)
            size = target.stat().st_size
            if f.size and size != f.size:
                raise UserError("download_size", f"Could not download {spec.key}: {f.remote} has {size} bytes, "
                                f"expected {f.size}", model=spec.key, file=f.remote)
            done += f.size or size
        if progress:
            progress(0, 0)  # converting
        for f in files:
            _convert_hf_file(raw_dir / f.remote, out_dir / f.local, f)
            (raw_dir / f.remote).unlink()
        (out_dir / "manifest.json").write_text(json.dumps(
            {"key": spec.key, "repo": repo, "revision": revision, "files": [f.local for f in files]}, indent=2))
        if dest.exists():
            shutil.rmtree(dest)
        os.replace(out_dir, dest)
    shutil.rmtree(raw_dir, ignore_errors=True)
    return dest / "manifest.json"


def install_from_file(spec_key: str, raw: str | Path, dest_root: Path | None = None) -> Path:
    """Convert a manually downloaded checkpoint (e.g. when Google Drive's quota is exceeded)."""
    spec = SPECS[spec_key]
    dest = (dest_root or paths.downloaded_models_dir()) / spec.filename
    convert(spec, Path(raw), dest)
    return dest


def uninstall(spec_key: str) -> None:
    spec = SPECS[spec_key]
    target = paths.downloaded_models_dir() / spec.filename
    if spec.kind == "hf":
        if target.is_file():
            shutil.rmtree(target.parent)
    elif target.is_file():
        target.unlink()


def load_state(spec_key: str) -> dict:
    import torch  # here: the GUI imports this module and starts without PyTorch

    state = torch.load(str(require(spec_key)), map_location="cpu", weights_only=True)
    return state


def move_models(src: Path, dst: Path, progress: ProgressFn | None = None) -> int:
    """Move every downloaded model (and unfinished download) from ``src`` to ``dst``: a rename on the
    same drive, otherwise copy + delete per folder. Folders that exist in ``dst`` are merged.
    Returns the bytes moved."""
    return move_entries(src, dst, progress=progress)


def copy_tree(src: Path, dst: Path) -> None:
    shutil.copytree(src, dst, dirs_exist_ok=True)
