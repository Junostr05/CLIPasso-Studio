# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller spec for CLIPasso Studio.

Environment variables:
    EDITION = cpu | gpu        (only used for naming)
    MODE    = onefile | onedir (onefile = portable single exe with splash screen)
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
(ROOT / "clipasso_studio" / "gui" / "_build_info.py").write_text(f'EDITION = "{EDITION}"\n', encoding="utf-8")

datas = [
    (str(ROOT / "clipasso_studio" / "resources"), "clipasso_studio/resources"),
    (str(ROOT / "clipasso_studio" / "engine" / "clip_" / "bpe_simple_vocab_16e6.txt.gz"), "clipasso_studio/engine/clip_"),
    (str(ROOT / "LICENSE"), "."),
    (str(ROOT / "THIRD_PARTY_NOTICES.md"), "."),
]
for sub in ("clip", "u2net", "dino", "vgg"):
    datas.append((str(MODELS / sub), f"models/{sub}"))

hiddenimports = collect_submodules("clipasso_studio") + ["PySide6.QtSvg"]
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
    "PySide6.Qt3DCore", "PySide6.QtMultimedia", "PySide6.QtCharts", "PySide6.QtDataVisualization",
    "PySide6.QtPdf", "PySide6.QtBluetooth", "PySide6.QtPositioning", "PySide6.QtSql", "PySide6.QtTest",
    "PySide6.QtDesigner", "PySide6.QtHelp", "PySide6.QtOpenGL", "PySide6.QtOpenGLWidgets",
    "PySide6.QtNetwork", "PySide6.QtXml", "PySide6.QtConcurrent", "PySide6.QtDBus",
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
)
pyz = PYZ(a.pure)

icon = str(ROOT / "packaging" / "app.ico") if IS_WIN else None
version = str(ROOT / "packaging" / "version_info.txt") if IS_WIN else None

if MODE == "onefile":
    splash_args = []
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
        splash_args = [splash, splash.binaries]
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
        a.binaries,
        a.datas,
        strip=False,
        upx=False,
        name="CLIPassoStudio",
    )
