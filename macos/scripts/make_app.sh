#!/bin/bash
# Put the Mac app together: CLIPasso Studio.app from the Swift package (macos/), the texts, the fonts of the prints
# (Inter, as the studio prints), the exported parameter schema and model list, BlazeFace (the one model that comes
# with the app) – and, when built
# (macos/scripts/build_python.sh OUT_DIR), the app's own Python with the engine.
#
#   macos/scripts/make_app.sh [OUT_DIR]          (default: macos/build)
#
# BlazeFace is taken from $MODELS (default: models/ of the repository) or downloaded there (tools/fetch_models.py,
# with the app's own Python when it is built: the download is converted with PyTorch).
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
cp -R "$ROOT/clipasso_studio/resources/fonts" "$APP/Contents/Resources/fonts"  # (ATSApplicationFontsPath)
# the phone page as the studio serves it (gui/remote.py): its files, the studio's icons, the app's icon
cp -R "$ROOT/clipasso_studio/resources/phone" "$APP/Contents/Resources/phone"
cp -R "$ROOT/clipasso_studio/resources/icons" "$APP/Contents/Resources/icons"
cp "$ROOT/clipasso_studio/resources/app_icon.png" "$APP/Contents/Resources/app_icon.png"
cp -R "$ROOT/clipasso_studio/resources/samples" "$APP/Contents/Resources/samples"  # (the phone's sample pictures)
(cd "$ROOT" && PYTHONPATH="$ROOT" "$PYTHON" -m clipasso_studio.headless \
    --export-schema "$APP/Contents/Resources/schema.json" --export-models "$APP/Contents/Resources/models.json")
if [ -d "$OUT/python" ]; then  # the app's own Python and the engine (build_python.sh)
    ditto "$OUT/python" "$APP/Contents/Resources/python"
    ditto "$OUT/engine" "$APP/Contents/Resources/engine"
    # the engine's build (the Analysis page and the MCP tool get_status name it: which code a Mac really runs)
    BUILD_ID=$(git -C "$ROOT" rev-parse --short HEAD 2>/dev/null || echo dev)
    echo "$BUILD_ID $(date -u +%Y-%m-%dT%H:%MZ)" > "$APP/Contents/Resources/engine/clipasso_studio/BUILD"
fi
BLAZEFACE=$(cd "$ROOT" && PYTHONPATH="$ROOT" "$PYTHON" -c \
    "from clipasso_studio.engine import model_store; print(model_store.SPECS['blazeface'].filename)")
if [ ! -f "$MODELS/$BLAZEFACE" ]; then
    # (converted with PyTorch: the app's own Python has it, the Python running this script need not)
    FETCH_PYTHON=$PYTHON
    if [ -x "$OUT/python/bin/python3" ]; then FETCH_PYTHON="$OUT/python/bin/python3"; fi
    (cd "$ROOT" && PYTHONPATH="$ROOT" "$FETCH_PYTHON" tools/fetch_models.py --only blazeface --dest "$MODELS")
fi
mkdir -p "$APP/Contents/Resources/models/$(dirname "$BLAZEFACE")"
cp "$MODELS/$BLAZEFACE" "$APP/Contents/Resources/models/$BLAZEFACE"

# the app's icon: Liquid Glass – Icon Composer's AppIcon.icon (its layers: the paper, the sketch, the eye), compiled
# by actool into Assets.car (the system draws the glass, light, dark and tinted) and AppIcon.icns; where actool cannot,
# the studio's flat icon as AppIcon.icns
ICON_TMP=$(mktemp -d)
if xcrun --find actool >/dev/null 2>&1 && xcrun actool "$ROOT/macos/App/AppIcon.icon" \
        --compile "$APP/Contents/Resources" --output-format human-readable-text --notices --warnings --errors \
        --output-partial-info-plist "$ICON_TMP/icon.plist" --app-icon AppIcon --include-all-app-icons \
        --enable-on-demand-resources NO --development-region en --target-device mac \
        --minimum-deployment-target 26.0 --platform macosx \
    && [ -f "$APP/Contents/Resources/Assets.car" ]; then
    echo "app icon: Liquid Glass (AppIcon.icon by actool)"
else
    echo "app icon: actool could not compile AppIcon.icon – the flat icon instead" >&2
    mkdir -p "$ICON_TMP/AppIcon.iconset"
    for size in 16 32 128 256 512; do
        sips -z "$size" "$size" "$ROOT/clipasso_studio/resources/app_icon.png" \
            --out "$ICON_TMP/AppIcon.iconset/icon_${size}x${size}.png" >/dev/null
        sips -z $((size * 2)) $((size * 2)) "$ROOT/clipasso_studio/resources/app_icon.png" \
            --out "$ICON_TMP/AppIcon.iconset/icon_${size}x${size}@2x.png" >/dev/null
    done
    iconutil -c icns "$ICON_TMP/AppIcon.iconset" -o "$APP/Contents/Resources/AppIcon.icns"
fi
rm -rf "$ICON_TMP"
ls -l "$APP/Contents/Resources" | grep -E "Assets.car|AppIcon" || true

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
    <key>CFBundleIconFile</key><string>AppIcon</string>
    <key>CFBundleIconName</key><string>AppIcon</string>
    <key>CFBundleShortVersionString</key><string>$VERSION</string>
    <key>CFBundleVersion</key><string>$VERSION</string>
    <key>CFBundleDevelopmentRegion</key><string>en</string>
    <key>CFBundleLocalizations</key><array><string>de</string><string>en</string></array>
    <key>LSMinimumSystemVersion</key><string>26.0</string>
    <key>LSApplicationCategoryType</key><string>public.app-category.graphics-design</string>
    <key>NSHighResolutionCapable</key><true/>
    <key>ATSApplicationFontsPath</key><string>fonts</string>
    <key>NSPrincipalClass</key><string>NSApplication</string>
    <key>NSCameraUsageDescription</key><string>CLIPasso Studio takes the photo to sketch with the camera (only when you ask for it) / nimmt das Foto zum Skizzieren mit der Kamera auf (nur wenn du es möchtest).</string>
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
