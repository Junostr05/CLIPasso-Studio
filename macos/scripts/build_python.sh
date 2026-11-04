#!/bin/bash
# The Mac app's own Python with the engine: CPython for Apple Silicon from python-build-standalone (pinned with its
# SHA-256), the engine's packages from requirements/lock-macos.txt (every file hash-pinned, made with
# tools/lock_macos.py), made smaller and compiled – and the engine itself without the Qt studio.
#
#   macos/scripts/build_python.sh [OUT_DIR]      (default: macos/build)  →  OUT_DIR/python, OUT_DIR/engine
#
# make_app.sh puts both into the .app. The download is kept in OUT_DIR/.cache (or $PBS_CACHE).
set -euo pipefail
PBS_RELEASE="20261021"
PBS_PYTHON="3.12.15"
PBS_SHA256="7b8d00b751db21cea87dc551a8f8165147c5fbc5251d5537d7e5497dde00a219"
PBS_FILE="cpython-${PBS_PYTHON}+${PBS_RELEASE}-aarch64-apple-darwin-install_only_stripped.tar.gz"
PBS_URL="https://github.com/astral-sh/python-build-standalone/releases/download/${PBS_RELEASE}/${PBS_FILE/+/%2B}"

ROOT=$(cd "$(dirname "$0")/../.." && pwd)
OUT=${1:-$ROOT/macos/build}
CACHE=${PBS_CACHE:-$OUT/.cache}
[ "$(uname -s)-$(uname -m)" = "Darwin-arm64" ] || { echo "build_python.sh builds for a Mac with Apple Silicon" >&2; exit 2; }

checked() { [ -f "$1" ] && [ "$(shasum -a 256 "$1" | cut -d' ' -f1)" = "$PBS_SHA256" ]; }
mkdir -p "$CACHE"
TAR="$CACHE/$PBS_FILE"
if ! checked "$TAR"; then
    curl -fL --retry 3 --retry-delay 5 -o "$TAR.part" "$PBS_URL"
    mv "$TAR.part" "$TAR"
fi
checked "$TAR" || { echo "wrong SHA-256 of $PBS_FILE – not used" >&2; rm -f "$TAR"; exit 1; }

rm -rf "$OUT/python" "$OUT/engine"
tar -xzf "$TAR" -C "$OUT"  # → OUT/python
PY="$OUT/python/bin/python3"
"$PY" -c "import sys; assert sys.version.startswith('$PBS_PYTHON'), sys.version"

# the engine's packages: exactly those of the lock file, as wheels only (nothing is compiled on the build machine)
"$PY" -m pip install --no-cache-dir --disable-pip-version-check --no-warn-script-location --only-binary :all: \
    --require-hashes -r "$ROOT/requirements/lock-macos.txt"

# smaller: what the engine never uses at run time (torch/testing/_internal stays: torch/utils/checkpoint.py imports
# torch.testing._internal.logging_tensor when torch is imported – the check at the end of this script found it)
SITE=$("$PY" -c "import sysconfig; print(sysconfig.get_paths()['purelib'])")
STDLIB=$("$PY" -c "import sysconfig; print(sysconfig.get_paths()['stdlib'])")
rm -rf "$SITE/torch/include" "$SITE/torch/share" \
       "$STDLIB/test" "$STDLIB/idlelib" "$STDLIB/turtledemo" "$STDLIB/tkinter" "$STDLIB/ensurepip" \
       "$STDLIB"/lib-dynload/_tkinter* "$OUT/python/lib"/tcl* "$OUT/python/lib"/tk* \
       "$OUT/python/include" "$OUT/python/share"
# torch/bin: only the shared-memory manager (tensors between processes); the rest are build tools
find "$SITE/torch/bin" -type f ! -name torch_shm_manager -delete 2>/dev/null || true
"$PY" -m pip uninstall -y -q pip  # (setuptools stays: torch asks for it)
find "$OUT/python" -name "__pycache__" -type d -prune -exec rm -rf {} +
# bin/: only Python itself (the scripts pip wrote name this build machine's path)
find "$OUT/python/bin" -mindepth 1 ! -name "python3" ! -name "python3.*" ! -name "python" -exec rm -f {} +

# the engine: the package without the Qt studio (gui/ only methods_ui.py – names and icons of the methods)
# (the phone remote's page is not in the first Mac release)
"$PY" -I - "$ROOT/clipasso_studio" "$OUT/engine/clipasso_studio" <<'PY'
import os, shutil, sys
src, dst = (os.path.abspath(p) for p in sys.argv[1:3])
def ignore(folder, names):
    skip = {n for n in names if n == "__pycache__" or n.endswith(".pyc")}
    if os.path.abspath(folder) == os.path.join(src, "gui"):
        skip |= {n for n in names if n != "methods_ui.py"}
    if os.path.abspath(folder) == os.path.join(src, "resources"):
        skip |= {"phone"}
    return skip
shutil.copytree(src, dst, ignore=ignore)
PY

# compiled once here: the signed app is never written to, and the check against the sources' times is not needed;
# the engine must compile, a library file that does not (e.g. one for another Python) is compiled when used
"$PY" -m compileall -q -j 0 --invalidation-mode unchecked-hash "$OUT/engine" >/dev/null
"$PY" -m compileall -q -j 0 --invalidation-mode unchecked-hash "$OUT/python/lib" >/dev/null \
    || echo "note: some library files did not compile ahead (they are compiled when imported)"
# the engine starts – without the user's Python settings, as the app starts it
env -i PATH=/usr/bin:/bin HOME="$HOME" PYTHONPATH="$OUT/engine" PYTHONNOUSERSITE=1 PYTHONDONTWRITEBYTECODE=1 \
    "$PY" -s -c "import torch, clipasso_studio.headless.server, clipasso_studio.engine.pipeline; \
print('torch', torch.__version__, '· MPS', torch.backends.mps.is_available())"
du -sh "$OUT/python" "$OUT/engine"
