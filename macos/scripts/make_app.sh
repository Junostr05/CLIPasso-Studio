#!/bin/bash
# Put the Mac app together: CLIPasso Studio.app from the Swift package (macos/), the texts, the exported parameter
# schema and model list, BlazeFace (the one model that comes with the app) – and, when built
# (macos/scripts/build_python.sh OUT_DIR), the app's own Python with the engine.
#
#   macos/scripts/make_app.sh [OUT_DIR]          (default: macos/build)
#
# BlazeFace is taken from $MODELS (default: models/ of the repository) or downloaded there (tools/fetch_models.py).
# Signed ad hoc (no Apple Developer account): Gatekeeper asks before the first start (see the README).
set -euo pipefail
ROOT=$(cd "$(dirname "$0")/../.." && pwd)
OUT=${1:-$ROOT/macos/build}
CONFIG=${CONFIG:-release}
PYTHON=${PYTHON:-python3}
MODELS=${MODELS:-$ROOT/models}
# (folders given relative to where the script is called – it changes into macos/ to build)
mkdir -p "$OUT" "$MODELS"
OUT=$(cd "$OUT" && pwd)
MODELS=$(cd "$MODELS" && pwd)
APP="$OUT/CLIPasso Studio.app"

cd "$ROOT/macos"
swift build -c "$CONFIG" --product CLIPassoStudio
BIN="$(swift build -c "$CONFIG" --show-bin-path)/CLIPassoStudio"

rm -rf "$APP"
mkdir -p "$APP/Contents/MacOS" "$APP/Contents/Resources"
cp "$BIN" "$APP/Contents/MacOS/CLIPassoStudio"
cp -R "$ROOT/clipasso_studio/resources/i18n" "$APP/Contents/Resources/i18n"
(cd "$ROOT" && PYTHONPATH="$ROOT" "$PYTHON" -m clipasso_studio.headless \
    --export-schema "$APP/Contents/Resources/schema.json" --export-models "$APP/Contents/Resources/models.json")
if [ -d "$OUT/python" ]; then  # the app's own Python and the engine (build_python.sh)
    ditto "$OUT/python" "$APP/Contents/Resources/python"
    ditto "$OUT/engine" "$APP/Contents/Resources/engine"
fi
BLAZEFACE=$(cd "$ROOT" && PYTHONPATH="$ROOT" "$PYTHON" -c \
    "from clipasso_studio.engine import model_store; print(model_store.SPECS['blazeface'].filename)")
if [ ! -f "$MODELS/$BLAZEFACE" ]; then
    (cd "$ROOT" && "$PYTHON" tools/fetch_models.py --only blazeface --dest "$MODELS")
fi
mkdir -p "$APP/Contents/Resources/models/$(dirname "$BLAZEFACE")"
cp "$MODELS/$BLAZEFACE" "$APP/Contents/Resources/models/$BLAZEFACE"

VERSION=$(cd "$ROOT" && "$PYTHON" -c "import clipasso_studio; print(clipasso_studio.__version__)")
cat > "$APP/Contents/Info.plist" <<PLIST
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>CFBundleName</key><string>CLIPasso Studio</string>
    <key>CFBundleDisplayName</key><string>CLIPasso Studio</string>
    <key>CFBundleIdentifier</key><string>de.junostr05.clipasso-studio</string>
    <key>CFBundleExecutable</key><string>CLIPassoStudio</string>
    <key>CFBundlePackageType</key><string>APPL</string>
    <key>CFBundleShortVersionString</key><string>$VERSION</string>
    <key>CFBundleVersion</key><string>$VERSION</string>
    <key>CFBundleDevelopmentRegion</key><string>en</string>
    <key>CFBundleLocalizations</key><array><string>de</string><string>en</string></array>
    <key>LSMinimumSystemVersion</key><string>26.0</string>
    <key>LSApplicationCategoryType</key><string>public.app-category.graphics-design</string>
    <key>NSHighResolutionCapable</key><true/>
    <key>NSPrincipalClass</key><string>NSApplication</string>
</dict>
</plist>
PLIST

# ad hoc signature, inside out: every Mach-O file of the bundled Python and its libraries, then the app
find "$APP/Contents/Resources" -type f \( -name "*.dylib" -o -name "*.so" -o -perm -u+x \) -print0 |
    while IFS= read -r -d "" f; do
        if file -b "$f" | grep -q "Mach-O"; then printf '%s\0' "$f"; fi
    done | xargs -0 -r -n 200 codesign --force --sign - --timestamp=none
codesign --force --sign - --timestamp=none "$APP"
codesign --verify --strict "$APP"
du -sh "$APP"
echo "$APP"
