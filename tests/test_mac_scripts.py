"""macos/scripts/make_app.sh puts the Mac app together – checked here with stand-ins for the Mac's own tools (swift,
codesign, ditto, file), so that what the script does with folders and files runs on every system with bash."""
import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]

pytestmark = pytest.mark.skipif(sys.platform == "win32" or shutil.which("bash") is None,
                                reason="the Mac's build scripts are bash scripts")

STUBS = {
    # `swift build …` leaves the app's binary where `swift build --show-bin-path` says it is
    "swift": '#!/bin/bash\nif [[ " $* " == *" --show-bin-path "* ]]; then echo "$STUB_BIN"; exit 0; fi\n'
             'mkdir -p "$STUB_BIN" && printf "binary" > "$STUB_BIN/CLIPassoStudio"\n',
    "ditto": '#!/bin/bash\nmkdir -p "$2" && cp -R "$1/." "$2"\n',
    "codesign": "#!/bin/bash\nexit 0\n",
    "file": "#!/bin/bash\necho data\n",
}


def _blazeface_name() -> str:
    from clipasso_studio.engine import model_store
    return model_store.SPECS["blazeface"].filename


def _stubs(tmp_path: Path) -> Path:
    stubs = tmp_path / "stubs"
    stubs.mkdir()
    for name, text in STUBS.items():
        (stubs / name).write_text(text, encoding="utf-8")
        (stubs / name).chmod(0o755)
    return stubs


def test_blazeface_is_fetched_with_the_apps_own_python(tmp_path):
    """BlazeFace is converted with PyTorch when it is downloaded: make_app.sh fetches it with the app's own Python
    (build_python.sh, which has PyTorch) – the Python that runs the build scripts need not have it (the macOS
    workflow's has not)."""
    stubs = _stubs(tmp_path)
    out = tmp_path / "out"
    own = out / "python" / "bin" / "python3"
    own.parent.mkdir(parents=True)
    # the app's Python as a stand-in: it "fetches" BlazeFace into --dest and notes that it was the one asked
    own.write_text('#!/bin/bash\nwhile [ $# -gt 0 ]; do [ "$1" = --dest ] && dest=$2; shift; done\n'
                   f'mkdir -p "$dest/$(dirname "{_blazeface_name()}")"\n'
                   f'printf "own python" > "$dest/{_blazeface_name()}"\n', encoding="utf-8")
    own.chmod(0o755)
    (out / "engine").mkdir()
    env = {**os.environ, "PATH": f"{stubs}{os.pathsep}{os.environ['PATH']}", "STUB_BIN": str(tmp_path / "bin"),
           "PYTHON": sys.executable, "MODELS": str(tmp_path / "models")}
    run = subprocess.run(["bash", str(ROOT / "macos" / "scripts" / "make_app.sh"), str(out)], cwd=tmp_path, env=env,
                         capture_output=True, text=True, encoding="utf-8", timeout=600)
    assert run.returncode == 0, run.stdout[-3000:] + run.stderr[-3000:]
    assert (tmp_path / "models" / _blazeface_name()).read_text(encoding="utf-8") == "own python"
    app_copy = out / "CLIPasso Studio.app" / "Contents" / "Resources" / "models" / _blazeface_name()
    assert app_copy.read_text(encoding="utf-8") == "own python"


def test_make_app_with_folders_given_relative_to_where_it_is_called(tmp_path):
    """The workflow calls `make_app.sh build/app` from the repository: the app, its schema and the app's own Python
    (build_python.sh put it into build/app) are all taken and put there – also after the script changed into
    macos/ to build. MODELS may be relative as well."""
    stubs = _stubs(tmp_path)
    work = tmp_path / "work"
    out = work / "build" / "app"
    (out / "python" / "bin").mkdir(parents=True)  # as build_python.sh leaves them
    (out / "python" / "bin" / "python3").write_text("python", encoding="utf-8")
    (out / "engine" / "clipasso_studio").mkdir(parents=True)
    blazeface = work / "models" / _blazeface_name()
    blazeface.parent.mkdir(parents=True)
    blazeface.write_bytes(b"blazeface")
    env = {**os.environ, "PATH": f"{stubs}{os.pathsep}{os.environ['PATH']}", "STUB_BIN": str(tmp_path / "bin"),
           "PYTHON": sys.executable, "MODELS": "models"}
    run = subprocess.run(["bash", str(ROOT / "macos" / "scripts" / "make_app.sh"), "build/app"], cwd=work, env=env,
                         capture_output=True, text=True, encoding="utf-8", timeout=600)
    assert run.returncode == 0, run.stdout[-3000:] + run.stderr[-3000:]
    app = out / "CLIPasso Studio.app" / "Contents"
    assert (app / "MacOS" / "CLIPassoStudio").read_text(encoding="utf-8") == "binary"
    resources = app / "Resources"
    assert (resources / "schema.json").stat().st_size > 1000 and (resources / "models.json").is_file()
    assert (resources / "i18n" / "de.json").is_file() and (resources / "i18n" / "en.json").is_file()
    # the prints' fonts (Inter, with its licence), loaded by macOS for the app
    fonts = resources / "fonts"
    assert (fonts / "Inter-SemiBold.ttf").is_file() and (fonts / "LICENSE-Inter-OFL.txt").is_file()
    plist = (app / "Info.plist").read_text(encoding="utf-8")
    assert "<key>ATSApplicationFontsPath</key><string>fonts</string>" in plist
    assert (resources / "python" / "bin" / "python3").read_text(encoding="utf-8") == "python"
    assert (resources / "engine" / "clipasso_studio").is_dir()
    assert (resources / "models" / _blazeface_name()).read_bytes() == b"blazeface"
    import clipasso_studio
    assert f"<string>{clipasso_studio.__version__}</string>" in plist
    assert str(out / "CLIPasso Studio.app") in run.stdout  # (its last line names the app)
