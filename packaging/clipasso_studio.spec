# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller spec for CLIPasso Studio.

Environment variables:
    EDITION = cpu | gpu        (only used for naming)
    MODE    = onefile | onedir (onefile = portable single exe; both show a splash screen)
    MODELS  = folder with the converted models (default: ./models)
"""

import os
import sys
from pathlib import Path

from PyInstaller.utils.hooks import collect_submodules, copy_metadata

ROOT = Path(SPECPATH).resolve().parent
EDITION = os.environ.get("EDITION", "cpu").lower()
MODE = os.environ.get("MODE", "onedir").lower()
MODELS = Path(os.environ.get("MODELS", ROOT / "models"))
IS_WIN = sys.platform == "win32"

if not (MODELS / "clip" / "RN101.pt").is_file():
    raise SystemExit(f"models not found in {MODELS} – run tools/fetch_models.py first")

# build info shown in the app
# MODE: the onefile exe is the portable edition, the onedir build goes into the installer
INSTALL_MODE = "portable" if MODE == "onefile" else "installed"
(ROOT / "clipasso_studio" / "gui" / "_build_info.py").write_text(
    f'EDITION = "{EDITION}"\nMODE = "{INSTALL_MODE}"\n', encoding="utf-8")

datas = [
    (str(ROOT / "clipasso_studio" / "resources"), "clipasso_studio/resources"),
    (str(ROOT / "clipasso_studio" / "engine" / "clip_" / "bpe_simple_vocab_16e6.txt.gz"), "clipasso_studio/engine/clip_"),
    (str(ROOT / "LICENSE"), "."),
    (str(ROOT / "THIRD_PARTY_NOTICES.md"), "."),
]
for sub in ("clip", "u2net", "dino", "vgg", "blazeface"):
    datas.append((str(MODELS / sub), f"models/{sub}"))

# every module of the app, listed from the source tree (collect_submodules imports packages in a helper
# process and silently skips a subtree when that fails)
_pkg = ROOT / "clipasso_studio"
hiddenimports = sorted({
    ".".join(p.relative_to(ROOT).with_suffix("").parts[:-1] if p.name == "__init__.py"
             else p.relative_to(ROOT).with_suffix("").parts)
    for p in _pkg.rglob("*.py") if "__pycache__" not in p.parts
}) + ["PySide6.QtSvg"]
# ControlSketch: diffusers / transformers import their model classes lazily by name
for pkg in ("transformers.models.auto", "transformers.models.clip", "transformers.models.dpt",
            "transformers.models.upernet", "transformers.models.convnext", "transformers.models.blip",
            "transformers.models.bert", "diffusers.models", "diffusers.schedulers", "diffusers.loaders",
            "diffusers.pipelines.stable_diffusion_xl"):
    hiddenimports += collect_submodules(pkg)
# diffusers checks the installed versions of its dependencies through their metadata
for dist in ("diffusers", "transformers", "tokenizers", "safetensors", "huggingface_hub", "accelerate", "torch",
             "numpy", "Pillow", "regex", "requests", "filelock", "packaging", "tqdm", "PyYAML"):
    try:
        datas += copy_metadata(dist)
    except Exception:
        pass

excludes = [
    "matplotlib", "IPython", "jupyter", "notebook", "pandas", "scipy", "skimage", "sklearn", "cv2",
    "PyQt5", "PyQt6", "PySide2", "torch.utils.tensorboard", "tensorboard", "caffe2", "triton",
    "PySide6.QtWebEngineCore", "PySide6.QtWebEngineWidgets", "PySide6.QtQuick", "PySide6.QtQml",
    "PySide6.Qt3DCore", "PySide6.QtCharts", "PySide6.QtDataVisualization",  # (QtMultimedia: the webcam)
    "PySide6.QtPdf", "PySide6.QtBluetooth", "PySide6.QtPositioning", "PySide6.QtSql", "PySide6.QtTest",
    "PySide6.QtDesigner", "PySide6.QtHelp", "PySide6.QtOpenGL", "PySide6.QtOpenGLWidgets",
    "PySide6.QtXml", "PySide6.QtConcurrent", "PySide6.QtDBus",  # (QtNetwork: needed by QtMultimedia)
    "PySide6.QtSpatialAudio", "PySide6.QtSerialPort", "PySide6.QtUiTools",
]

a = Analysis(
    [str(ROOT / "packaging" / "launch.py")],
    pathex=[str(ROOT)],
    binaries=[],
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=excludes,
    noarchive=False,
    optimize=0,
    # the app's own modules as single .pyc files next to the exe, not in the archive inside it: a bug-fix update
    # then changes only those files (small patches), and the exe stays the same (see the version below)
    module_collection_mode={"clipasso_studio": "pyc"},
)
pyz = PYZ(a.pure)

icon = str(ROOT / "packaging" / "app.ico") if IS_WIN else None
version = None
# The exe's file version is the release in which the exe last changed – not the app's version (the app shows that
# itself): the exe holds the launcher and the bundled libraries, the app's own modules are files next to it. So it
# stays byte for byte the same from one release to the next and an update leaves it out (75 MB). Set it to the
# app's version when the libraries change (PyTorch, Qt, …) – then the exe changes anyway.
EXE_VERSION = "3.3"
if IS_WIN:
    _nums = [int(n) for n in EXE_VERSION.split(".")]
    _info = (ROOT / "packaging" / "version_info.in").read_text(encoding="utf-8")
    _info = _info.replace("{version}", EXE_VERSION)
    _info = _info.replace("{vtuple}", str(tuple(_nums + [0] * (4 - len(_nums)))))
    version = os.path.join(workpath, "version_info.txt")
    os.makedirs(workpath, exist_ok=True)
    Path(version).write_text(_info, encoding="utf-8")

# the splash screen shows until the window is up (both builds; the app suppresses it for its worker processes)
splash = None
if IS_WIN:
    splash = Splash(
        str(ROOT / "packaging" / "splash.png"),
        binaries=a.binaries,
        datas=a.datas,
        text_pos=(56, 330),
        text_size=9,
        text_color="#9AA3B4",
        minify_script=True,
        always_on_top=False,
    )

if MODE == "onefile":
    splash_args = [splash, splash.binaries] if splash is not None else []
    exe = EXE(
        pyz,
        a.scripts,
        *splash_args,
        a.binaries,
        a.datas,
        [],
        name=f"CLIPassoStudio-{EDITION.upper()}-Portable",
        debug=False,
        bootloader_ignore_signals=False,
        strip=False,
        upx=False,
        runtime_tmpdir=None,
        console=False,
        disable_windowed_traceback=False,
        icon=icon,
        version=version,
    )
else:
    exe = EXE(
        pyz,
        *([splash] if splash is not None else []),
        a.scripts,
        [],
        exclude_binaries=True,
        name="CLIPassoStudio",
        debug=False,
        bootloader_ignore_signals=False,
        strip=False,
        upx=False,
        console=False,
        disable_windowed_traceback=False,
        icon=icon,
        version=version,
    )
    coll = COLLECT(
        exe,
        *([splash.binaries] if splash is not None else []),
        a.binaries,
        a.datas,
        strip=False,
        upx=False,
        name="CLIPassoStudio",
    )
