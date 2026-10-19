"""Render the SVG app icon into a macOS ``.icns`` file (run on any platform with PySide6).

uv run python packaging/macos/make_icns.py
"""

from __future__ import annotations

import os
import struct
import sys
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QBuffer, QByteArray, QIODevice, Qt  # noqa: E402
from PySide6.QtGui import QGuiApplication, QImage, QPainter  # noqa: E402
from PySide6.QtSvg import QSvgRenderer  # noqa: E402

ROOT = Path(__file__).resolve().parents[2]
SVG = ROOT / "src/thr_control/data/icons/io.github.bleaff.ThrControl.svg"
OUT = Path(__file__).with_name("ThrControl.icns")

# (icns type, pixel size). The *@2x* types are the same PNG sizes as the next type up.
TYPES = [
    ("icp4", 16),
    ("icp5", 32),
    ("ic07", 128),
    ("ic08", 256),
    ("ic09", 512),
    ("ic10", 1024),
    ("ic11", 32),
    ("ic12", 64),
    ("ic13", 256),
    ("ic14", 512),
]


def render_png(renderer: QSvgRenderer, size: int) -> bytes:
    image = QImage(size, size, QImage.Format.Format_ARGB32)
    image.fill(Qt.GlobalColor.transparent)
    painter = QPainter(image)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    renderer.render(painter)
    painter.end()
    data = QByteArray()
    buf = QBuffer(data)
    buf.open(QIODevice.OpenModeFlag.WriteOnly)
    image.save(buf, "PNG")
    return bytes(data)


def build(svg: Path = SVG) -> bytes:
    QGuiApplication.instance() or QGuiApplication(sys.argv[:1])
    renderer = QSvgRenderer(str(svg))
    if not renderer.isValid():
        raise SystemExit(f"cannot read {svg}")
    cache: dict[int, bytes] = {}
    chunks = b""
    for ostype, size in TYPES:
        png = cache.setdefault(size, render_png(renderer, size))
        chunks += ostype.encode("ascii") + struct.pack(">I", len(png) + 8) + png
    return b"icns" + struct.pack(">I", len(chunks) + 8) + chunks


if __name__ == "__main__":
    OUT.write_bytes(build())
    print(f"wrote {OUT} ({OUT.stat().st_size} bytes)")
