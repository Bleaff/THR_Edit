"""Environment self-check with plain-language fixes (``thr-control doctor``).

Every probe is injectable, so the logic is tested without hardware; the defaults inspect the
real system and never send anything to the amp (the heartbeat check only listens).
"""

from __future__ import annotations

import os
import shutil
import sys
import tempfile
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path

from .. import __version__, paths
from ..midi.discovery import detect_devices, list_input_ports, list_output_ports
from ..protocol.parser import Heartbeat, parse

OK, WARN, FAIL = "ok", "warn", "fail"
AUDIO_TOOLS = ("pw-record", "pw-play", "pw-dump")


@dataclass(frozen=True)
class Check:
    name: str
    status: str  # ok | warn | fail
    detail: str
    hint: str = ""


def _heartbeat_seen(port: str, timeout: float) -> bool:
    """Listen (read-only, polled) for the amp's heartbeat on *port*."""
    import mido

    inp = mido.open_input(port)
    try:
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            msg = inp.poll()
            if msg is None:
                time.sleep(0.01)
            elif msg.type == "sysex" and isinstance(parse(bytes(msg.bytes())), Heartbeat):
                return True
        return False
    finally:
        inp.close()


def _writable(directory: Path) -> bool:
    try:
        directory.mkdir(parents=True, exist_ok=True)
        with tempfile.NamedTemporaryFile(dir=directory):
            return True
    except OSError:
        return False


def _thr_audio_present() -> bool:
    from . import audio

    sink, source = audio.find_thr(audio.list_nodes())
    return sink is not None and source is not None


def _portaudio_ok() -> bool:
    try:
        import sounddevice  # noqa: F401

        return True
    except (ImportError, OSError):
        return False


def _midi_backend_ok() -> bool:
    try:
        import mido

        mido.set_backend("mido.backends.rtmidi")
        mido.get_input_names()
        return True
    except Exception:
        return False


def _gui_ok() -> bool:
    try:
        from PySide6 import QtWidgets  # noqa: F401

        return True
    except Exception:
        return False


@dataclass
class Probes:
    platform: str = field(default_factory=lambda: sys.platform)
    python: tuple[int, int] = field(default_factory=lambda: sys.version_info[:2])
    midi_backend_ok: Callable[[], bool] = _midi_backend_ok
    seq_access: Callable[[], bool] = lambda: os.access("/dev/snd/seq", os.R_OK | os.W_OK)
    inputs: Callable[[], list[str]] = list_input_ports
    outputs: Callable[[], list[str]] = list_output_ports
    heartbeat: Callable[[str, float], bool] = _heartbeat_seen
    which: Callable[[str], str | None] = shutil.which
    portaudio_ok: Callable[[], bool] = _portaudio_ok
    audio_present: Callable[[], bool] = _thr_audio_present
    writable: Callable[[Path], bool] = _writable
    presets_dir: Callable[[], Path] = paths.presets_dir
    gui_ok: Callable[[], bool] = _gui_ok


def run_checks(probes: Probes | None = None, heartbeat_timeout: float = 2.5) -> list[Check]:
    p = probes or Probes()
    out: list[Check] = []
    linux = p.platform.startswith("linux")

    py = f"{p.python[0]}.{p.python[1]}"
    out.append(
        Check("Python", OK, f"{py}, THR Control {__version__}")
        if p.python >= (3, 12)
        else Check("Python", FAIL, f"{py} is too old", "THR Control needs Python 3.12 or newer.")
    )
    out.append(
        Check("Desktop app (Qt)", OK, "PySide6 is available")
        if p.gui_ok()
        else Check(
            "Desktop app (Qt)",
            FAIL,
            "PySide6 cannot be imported",
            "Reinstall THR Control (for example `pipx reinstall thr-control`).",
        )
    )

    if not p.midi_backend_ok():
        hint = (
            "Install the ALSA library (Arch: `sudo pacman -S alsa-lib`, Debian/Ubuntu: "
            "`sudo apt install libasound2`)."
            if linux
            else "Reinstall THR Control so that python-rtmidi is rebuilt for your system."
        )
        out.append(Check("MIDI backend", FAIL, "python-rtmidi cannot be loaded", hint))
        return out + _tail(p, out, linux)
    out.append(Check("MIDI backend", OK, "python-rtmidi works"))

    if linux:
        if p.seq_access():
            out.append(Check("MIDI permissions", OK, "/dev/snd/seq is accessible"))
        else:
            out.append(
                Check(
                    "MIDI permissions",
                    FAIL,
                    "cannot open /dev/snd/seq",
                    "Add yourself to the audio group: `sudo usermod -aG audio $USER`, "
                    "then log out and in again.",
                )
            )

    ins, outs = p.inputs(), p.outputs()
    devices = [d for d in detect_devices(ins, outs) if d.input_port and d.output_port]
    if not devices:
        found = f"{len(ins)} MIDI input(s) found, none is a THR" if ins else "no MIDI ports"
        out.append(
            Check(
                "Amplifier",
                FAIL,
                found,
                "Connect the amp with a USB cable and switch it on, then run this again. "
                "(Linux: `aconnect -l` should list a client named THR.)",
            )
        )
    else:
        d = devices[0]
        out.append(Check("Amplifier", OK, f"{d.model} found ({d.input_port})"))
        try:
            alive = p.heartbeat(d.input_port or "", heartbeat_timeout)
        except Exception as exc:
            alive = False
            out.append(
                Check(
                    "Amp port",
                    FAIL,
                    f"cannot open the input port: {exc}",
                    "Close other MIDI programs that may be using the amp, then retry.",
                )
            )
        else:
            out.append(
                Check("Amp responding", OK, "heartbeat received")
                if alive
                else Check(
                    "Amp responding",
                    WARN,
                    f"no heartbeat within {heartbeat_timeout:g} s",
                    "The amp may be busy (tuner mode?). Leave tuner mode and retry.",
                )
            )
    return out + _tail(p, out, linux)


def _tail(p: Probes, so_far: list[Check], linux: bool) -> list[Check]:
    out: list[Check] = []
    pa = p.portaudio_ok()
    if linux:
        missing = [t for t in AUDIO_TOOLS if p.which(t) is None]
        if not missing:
            out.append(Check("Audio backend", OK, "PipeWire tools found"))
        elif pa:
            out.append(
                Check(
                    "Audio backend",
                    OK,
                    f"PipeWire tools missing ({', '.join(missing)}); PortAudio will be used",
                )
            )
        else:
            out.append(
                Check(
                    "Audio backend",
                    WARN,
                    f"missing: {', '.join(missing)}",
                    "Recording and live measurement need the PipeWire tools (Arch: `pipewire`, "
                    "Debian/Ubuntu: `pipewire-bin`, Fedora: `pipewire-utils`) or "
                    "`pip install sounddevice`. Everything else works without.",
                )
            )
    else:
        out.append(
            Check("Audio backend", OK, "PortAudio (sounddevice) is available")
            if pa
            else Check(
                "Audio backend",
                WARN,
                "sounddevice cannot be loaded",
                "Recording and live measurement need it: `pip install sounddevice`. "
                "Everything else works without.",
            )
        )
    if not any(c.name == "Amplifier" and c.status == OK for c in so_far):
        pass  # no amp: the audio check below would only repeat that message
    else:
        try:
            present = p.audio_present()
        except Exception:
            present = False
        out.append(
            Check("Amp USB audio", OK, "playback and capture devices found")
            if present
            else Check(
                "Amp USB audio",
                WARN,
                "no USB audio device for the amp",
                "Recording and live measurement will be unavailable.",
            )
        )
    directory = p.presets_dir()
    out.append(
        Check("Preset library", OK, f"{directory} is writable")
        if p.writable(directory)
        else Check(
            "Preset library",
            FAIL,
            f"cannot write to {directory}",
            "Check the folder's permissions.",
        )
    )
    return out


def summarise(checks: list[Check]) -> tuple[int, int]:
    """(failures, warnings)."""
    return (sum(c.status == FAIL for c in checks), sum(c.status == WARN for c in checks))
