# -*- mode: python ; coding: utf-8 -*-
# PyInstaller spec for THR Control. Build on the platform you target (a macOS .app can only be
# built on a Mac):  uv run --with pyinstaller pyinstaller --noconfirm packaging/macos/thr-control.spec
import sys
from pathlib import Path

ROOT = Path(SPECPATH).resolve().parent.parent  # noqa: F821  (SPECPATH is provided by PyInstaller)
sys.path.insert(0, str(ROOT / "src"))
from thr_control import __version__  # noqa: E402

APP_ID = "io.github.bleaff.ThrControl"

a = Analysis(  # noqa: F821
    [str(ROOT / "packaging/macos/launcher.py")],
    pathex=[str(ROOT / "src")],
    datas=[(str(ROOT / "src/thr_control/data"), "thr_control/data")],
    # mido picks its MIDI backend by name at runtime, so PyInstaller cannot see these imports
    hiddenimports=["mido.backends.rtmidi", "rtmidi", "sounddevice"],
    excludes=["tkinter", "matplotlib", "scipy", "pandas", "IPython", "pytest"],
)
pyz = PYZ(a.pure)  # noqa: F821
exe = EXE(  # noqa: F821
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="thr-control-gui",
    console=False,
)
coll = COLLECT(exe, a.binaries, a.datas, name="THR Control")  # noqa: F821

if sys.platform == "darwin":
    app = BUNDLE(  # noqa: F821
        coll,
        name="THR Control.app",
        icon=str(ROOT / "packaging/macos/ThrControl.icns"),
        bundle_identifier=APP_ID,
        version=__version__,
        info_plist={
            "CFBundleName": "THR Control",
            "CFBundleDisplayName": "THR Control",
            "CFBundleShortVersionString": __version__,
            "NSHighResolutionCapable": True,
            "LSMinimumSystemVersion": "11.0",
            "LSApplicationCategoryType": "public.app-category.music",
            "NSHumanReadableCopyright": "Copyright 2026 Bleaff. AGPL-3.0-or-later.",
            # Without this, macOS silently delivers silence when the app records the amp's USB audio.
            "NSMicrophoneUsageDescription": (
                "THR Control records the USB audio of your amplifier (your guitar) for the "
                "recorder and the live response plot. It never records anything else."
            ),
        },
    )
