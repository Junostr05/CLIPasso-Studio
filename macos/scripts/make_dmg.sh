#!/bin/bash
# The disk image to hand out: CLIPasso Studio.app, a link to the Applications folder and the "read me first" about
# the first start of an app Apple did not sign (German and English, from the app's texts: dmg_readme.py).
#
#   macos/scripts/make_dmg.sh [OUT_DIR]     (default: macos/build; needs OUT_DIR/CLIPasso Studio.app from make_app.sh)
set -euo pipefail
ROOT=$(cd "$(dirname "$0")/../.." && pwd)
OUT=${1:-$ROOT/macos/build}
PYTHON=${PYTHON:-python3}
APP="$OUT/CLIPasso Studio.app"
[ -d "$APP" ] || { echo "no $APP – run make_app.sh first" >&2; exit 2; }
VERSION=$(/usr/libexec/PlistBuddy -c "Print :CFBundleShortVersionString" "$APP/Contents/Info.plist")
DMG="$OUT/CLIPasso-Studio-$VERSION-mac.dmg"

STAGE=$(mktemp -d "$OUT/dmg.XXXXXX")
trap 'rm -rf "$STAGE"' EXIT
ditto "$APP" "$STAGE/CLIPasso Studio.app"
ln -s /Applications "$STAGE/Applications"
"$PYTHON" "$ROOT/macos/scripts/dmg_readme.py" "$ROOT/clipasso_studio/resources/i18n" "$STAGE" >/dev/null
rm -f "$DMG"
hdiutil create -volname "CLIPasso Studio" -srcfolder "$STAGE" -fs APFS -format ULMO -ov "$DMG" >/dev/null
hdiutil verify "$DMG" >/dev/null
du -h "$DMG" | cut -f1
echo "$DMG"
