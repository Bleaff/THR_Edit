# Building THR Control for macOS

Status: **untested on a Mac.** The configuration was checked by running the same PyInstaller spec on Linux (see below), but a
macOS `.app` can only be built on macOS.

## Build

```sh
packaging/macos/build.sh
```

This produces `dist/THR Control.app` and `dist/THR-Control-<version>-<arch>.dmg` (`arm64` or `x86_64`; build once on each kind
of Mac, or let the `macos-app` workflow do it). Requirements: Xcode command-line tools (`xcode-select --install`) and `uv`.

## What is and is not done

- The app is **ad-hoc signed** (`codesign -s -`) so that it starts on Apple silicon. It is **not notarized**, so macOS
  Gatekeeper will warn about a downloaded copy. Users open it with right-click, Open, or `xattr -dr com.apple.quarantine`.
- Proper distribution needs an Apple Developer ID (99 USD a year): sign with it (`codesign --options runtime`), then notarize
  with `xcrun notarytool` and staple. Not set up yet.
- The Mac App Store is not an option: it conflicts with AGPL licensing.
- `Info.plist` contains the microphone usage text. Without it macOS would deliver silence when the app records the amp.
- `ThrControl.icns` is generated from the SVG icon by `make_icns.py`; regenerate it after changing the icon.

Please follow `docs/macos-testing.md` after building to check that the app really talks to an amp.
