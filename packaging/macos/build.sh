#!/usr/bin/env bash
# Build "THR Control.app" and a .dmg on a Mac:  packaging/macos/build.sh
# The result is ad-hoc signed only (no Apple Developer ID), see packaging/macos/README.md.
set -euo pipefail
cd "$(dirname "$0")/../.."

[ "$(uname -s)" = "Darwin" ] || { echo "error: this builds a macOS app and must run on a Mac" >&2; exit 1; }

ARCH="$(uname -m)"   # arm64 or x86_64
VERSION="$(python3 -c "import re; print(re.search(r'__version__ = \"(.+?)\"', open('src/thr_control/__init__.py').read()).group(1))")"

uv sync
uv run --with pyinstaller pyinstaller --noconfirm --clean packaging/macos/thr-control.spec

APP="dist/THR Control.app"
# Apple silicon refuses to start unsigned code, so sign ad hoc (this is not notarization).
codesign --force --deep --sign - "$APP"
codesign --verify --deep "$APP"

DMG="dist/THR-Control-${VERSION}-${ARCH}.dmg"
rm -f "$DMG"
hdiutil create -volname "THR Control" -srcfolder "$APP" -ov -format UDZO "$DMG"

echo
echo "Built: $DMG"
echo "Unsigned for distribution: on first launch right-click the app and choose Open,"
echo "or run:  xattr -dr com.apple.quarantine \"/Applications/THR Control.app\""
