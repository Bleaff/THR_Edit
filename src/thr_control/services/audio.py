"""Play a sweep and record the amp's USB audio through PipeWire (pw-play / pw-record).

Using the PipeWire command-line tools keeps this free of audio libraries and works while the
desktop session already owns the device. Everything is explicit about which device it plays to
and which channels it records, and plays at a clamped, quiet level (see ``measure.HARD_MAX_DBFS``).
"""

from __future__ import annotations

import re
import subprocess
import tempfile
import time
import wave
from dataclasses import dataclass
from pathlib import Path

import numpy as np

from ..domain import measure

THR_SINK_HINT = "THR"
RECORD_CHANNELS = 4  # the THR5's USB capture exposes four channels


class AudioError(Exception):
    pass


@dataclass(frozen=True)
class Node:
    id: int
    name: str  # node.name, usable with --target
    description: str
    kind: str  # "sink" or "source"


def _run(cmd: list[str], timeout: float = 15) -> str:
    try:
        return subprocess.run(
            cmd, capture_output=True, text=True, timeout=timeout, check=True
        ).stdout
    except FileNotFoundError as exc:
        raise AudioError(f"{cmd[0]} not found; PipeWire tools are required") from exc
    except subprocess.CalledProcessError as exc:
        raise AudioError(f"{' '.join(cmd)} failed: {exc.stderr.strip() or exc.returncode}") from exc
    except subprocess.TimeoutExpired as exc:
        raise AudioError(f"{cmd[0]} timed out") from exc


def parse_nodes(pw_dump_text: str) -> list[Node]:
    """Extract audio sinks and sources from ``pw-dump`` JSON."""
    import json

    nodes: list[Node] = []
    for obj in json.loads(pw_dump_text):
        props = (obj.get("info") or {}).get("props") or {}
        media = props.get("media.class", "")
        if obj.get("type") != "PipeWire:Interface:Node" or media not in (
            "Audio/Sink",
            "Audio/Source",
        ):
            continue
        nodes.append(
            Node(
                int(obj["id"]),
                str(props.get("node.name", "")),
                str(props.get("node.description", props.get("node.name", ""))),
                "sink" if media == "Audio/Sink" else "source",
            )
        )
    return nodes


def list_nodes() -> list[Node]:
    return parse_nodes(_run(["pw-dump"]))


def find_thr(nodes: list[Node]) -> tuple[Node | None, Node | None]:
    """The THR's playback sink and capture source, if present."""
    sink = next((n for n in nodes if n.kind == "sink" and THR_SINK_HINT in n.description), None)
    source = next((n for n in nodes if n.kind == "source" and THR_SINK_HINT in n.description), None)
    return sink, source


def write_wav(path: Path, samples: np.ndarray, fs: int, channels: int = 2) -> None:
    pcm = np.clip(np.round(samples * 2147483648.0), -2147483648, 2147483647).astype("<i4")
    frames = np.repeat(pcm[:, None], channels, axis=1)
    with wave.open(str(path), "wb") as w:
        w.setnchannels(channels)
        w.setsampwidth(4)
        w.setframerate(fs)
        w.writeframes(frames.tobytes())


def write_pcm24(path: Path, samples: np.ndarray, fs: int) -> None:
    """Write [frames, channels] floats (-1..1) as a 24-bit PCM WAV."""
    # Round (not truncate) and use the same scale the reader divides by: error <= half a step.
    pcm = np.clip(np.round(samples * 8388608.0), -8388608, 8388607).astype("<i4")
    raw = pcm.view(np.uint8).reshape(-1, 4)[:, :3]  # keep the low 3 bytes (little endian)
    with wave.open(str(path), "wb") as w:
        w.setnchannels(samples.shape[1])
        w.setsampwidth(3)
        w.setframerate(fs)
        w.writeframes(raw.tobytes())


def read_wav(path: Path) -> tuple[np.ndarray, int]:
    """Return (samples shaped [frames, channels] in -1..1, sample rate); 16/24/32-bit PCM."""
    with wave.open(str(path), "rb") as w:
        width, channels = w.getsampwidth(), w.getnchannels()
        raw = w.readframes(w.getnframes())
        rate = w.getframerate()
    if width == 4:
        data = np.frombuffer(raw, dtype="<i4") / 2147483648.0
    elif width == 3:
        b = np.frombuffer(raw, dtype=np.uint8).reshape(-1, 3).astype(np.int32)
        value = b[:, 0] | (b[:, 1] << 8) | (b[:, 2] << 16)
        data = np.where(value >= 1 << 23, value - (1 << 24), value) / 8388608.0
    elif width == 2:
        data = np.frombuffer(raw, dtype="<i2") / 32768.0
    else:
        raise AudioError(f"unexpected sample width {width}")
    return data.reshape(-1, channels), rate


def play_and_record(
    sweep: np.ndarray,
    sink: Node,
    source: Node,
    fs: int = measure.SAMPLE_RATE,
    channels: int = RECORD_CHANNELS,
    lead: float = 0.6,
    tail: float = 1.5,
) -> np.ndarray:
    """Play *sweep* on *sink* while recording *source*; returns [frames, channels].

    Recording starts first and ends after a tail, so the sweep and the amp's response fit
    inside it however large the latency is.
    """
    with tempfile.TemporaryDirectory(prefix="thr-measure-") as tmp:
        play_path, rec_path = Path(tmp) / "sweep.wav", Path(tmp) / "rec.wav"
        write_wav(play_path, sweep, fs)
        rec = subprocess.Popen(
            [
                "pw-record",
                "--target",
                source.name,
                "--rate",
                str(fs),
                "--channels",
                str(channels),
                "--format",
                "s32",
                str(rec_path),
            ],
            stderr=subprocess.PIPE,
        )
        try:
            time.sleep(lead)
            _run(["pw-play", "--target", sink.name, str(play_path)], timeout=len(sweep) / fs + 15)
            time.sleep(tail)
        finally:
            rec.terminate()
            try:
                rec.wait(timeout=5)
            except subprocess.TimeoutExpired:
                rec.kill()
        if not rec_path.exists():
            raise AudioError(
                "recording produced no file: " + (rec.stderr.read().decode() if rec.stderr else "")
            )
        data, rate = read_wav(rec_path)
    if rate != fs:
        raise AudioError(f"recorded at {rate} Hz, expected {fs}")
    return data


@dataclass(frozen=True)
class ChannelReport:
    channel: int
    rms_dbfs: float
    detection_db: float

    @property
    def carries_sweep(self) -> bool:
        return self.detection_db > measure.DETECTION_THRESHOLD_DB


def analyse_channels(
    recorded: np.ndarray, sweep: np.ndarray, fs: int = measure.SAMPLE_RATE
) -> list[ChannelReport]:
    out = []
    for ch in range(recorded.shape[1]):
        x = recorded[:, ch]
        rms = float(np.sqrt(np.mean(x**2))) or 1e-12
        ir = measure.impulse_response(x, sweep, fs)
        out.append(ChannelReport(ch + 1, 20 * np.log10(rms), ir.peak_to_noise_db))
    return out


def sanitize_name(text: str) -> str:
    return re.sub(r"[^A-Za-z0-9_.-]+", "-", text).strip("-")[:60]


def record(
    source: Node,
    seconds: float,
    path: Path,
    fs: int = measure.SAMPLE_RATE,
    channels: int = RECORD_CHANNELS,
) -> None:
    """Record *seconds* from *source* into *path* (s32 WAV); Ctrl+C keeps what was recorded."""
    rec = subprocess.Popen(
        [
            "pw-record",
            "--target",
            source.name,
            "--rate",
            str(fs),
            "--channels",
            str(channels),
            "--format",
            "s32",
            str(path),
        ],
        stderr=subprocess.PIPE,
    )
    try:
        time.sleep(seconds)
    except KeyboardInterrupt:
        pass
    finally:
        rec.terminate()
        try:
            rec.wait(timeout=5)
        except subprocess.TimeoutExpired:
            rec.kill()
    if not path.exists() or path.stat().st_size < 100:
        raise AudioError(
            "recording produced no file: " + (rec.stderr.read().decode() if rec.stderr else "")
        )


ACTIVE_DBFS = -60.0  # a channel quieter than this is treated as silent
CLIP_DBFS = -0.2


@dataclass(frozen=True)
class ChannelLevel:
    channel: int
    rms_dbfs: float
    peak_dbfs: float

    @property
    def active(self) -> bool:
        return self.peak_dbfs > ACTIVE_DBFS

    @property
    def clipping(self) -> bool:
        return self.peak_dbfs >= CLIP_DBFS


def level_report(data: np.ndarray) -> list[ChannelLevel]:
    out = []
    for ch in range(data.shape[1]):
        x = data[:, ch]
        rms = float(np.sqrt(np.mean(x**2))) or 1e-12
        peak = float(np.max(np.abs(x))) or 1e-12
        out.append(ChannelLevel(ch + 1, 20 * np.log10(rms), 20 * np.log10(peak)))
    return out


def correlation(a: np.ndarray, b: np.ndarray) -> float:
    """Normalised correlation of two equal-length signals (1 = identical, 0 = unrelated)."""
    na, nb = float(np.linalg.norm(a)), float(np.linalg.norm(b))
    return float(np.dot(a, b) / (na * nb)) if na > 0 and nb > 0 else 0.0


def spectral_centroid(x: np.ndarray, fs: int = measure.SAMPLE_RATE) -> float:
    """Brightness: the spectrum's centre of mass in Hz (0 for silence)."""
    mag = np.abs(np.fft.rfft(x * np.hanning(len(x))))
    total = float(mag.sum())
    return float((np.fft.rfftfreq(len(x), 1 / fs) * mag).sum() / total) if total > 0 else 0.0


def pair_relation(
    first: np.ndarray, second: np.ndarray, fs: int = measure.SAMPLE_RATE, max_ms: float = 20.0
) -> tuple[int, float]:
    """Strongest cross-correlation of two signals within +-*max_ms*.

    Returns (lag in samples, normalised correlation). A positive lag means *first* is later than
    *second*; the correlation is signed (negative: the signals are polarity-inverted).
    """
    n = 1 << (len(first) + len(second) - 1).bit_length()
    corr = np.fft.irfft(np.fft.rfft(first, n) * np.conj(np.fft.rfft(second, n)), n)
    reach = int(max_ms / 1000 * fs)
    lags = np.concatenate([np.arange(0, reach), np.arange(-reach, 0)])
    values = np.concatenate([corr[:reach], corr[n - reach :]])
    k = int(np.argmax(np.abs(values)))
    norm = float(np.linalg.norm(first) * np.linalg.norm(second))
    return int(lags[k]), float(values[k] / norm) if norm > 0 else 0.0


def is_dual_mono(left: np.ndarray, right: np.ndarray) -> bool:
    return bool(np.allclose(left, right, atol=1e-6))
