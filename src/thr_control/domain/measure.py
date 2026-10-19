"""Frequency-response measurement with an exponential sine sweep (Farina method).

Pure numpy: generating the sweep and turning a recording into a magnitude response. All
audio I/O lives in ``services/audio.py``.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

import numpy as np

SAMPLE_RATE = 48000
F_START = 20.0
F_END = 20000.0
DETECTION_THRESHOLD_DB = 30.0  # peak_to_noise_db above this means "the sweep is in the recording"
HARD_MAX_DBFS = -12.0  # never play louder than this, whatever the caller asks for


def db_to_amplitude(dbfs: float) -> float:
    if dbfs > HARD_MAX_DBFS:
        raise ValueError(f"level {dbfs:g} dBFS is above the safety limit of {HARD_MAX_DBFS:g} dBFS")
    return 10 ** (dbfs / 20)


def log_sweep(
    duration: float = 4.0,
    f1: float = F_START,
    f2: float = F_END,
    fs: int = SAMPLE_RATE,
    dbfs: float = -30.0,
    fade: float = 0.05,
) -> np.ndarray:
    """Exponential sine sweep from *f1* to *f2* with short fades (no clicks)."""
    amp = db_to_amplitude(dbfs)
    t = np.arange(int(duration * fs)) / fs
    k = math.log(f2 / f1)
    phase = 2 * math.pi * f1 * duration / k * (np.exp(t * k / duration) - 1)
    x = amp * np.sin(phase)
    n = int(fade * fs)
    ramp = 0.5 - 0.5 * np.cos(np.linspace(0, math.pi, n))
    x[:n] *= ramp
    x[-n:] *= ramp[::-1]
    return x


@dataclass(frozen=True)
class ImpulseResponse:
    samples: np.ndarray
    fs: int
    peak_index: int
    peak_to_noise_db: (
        float  # main peak vs. noise spread; pure noise scores ~13 dB, a real signal 40+
    )

    @property
    def latency_ms(self) -> float:
        return self.peak_index / self.fs * 1000


def impulse_response(
    recorded: np.ndarray, sweep: np.ndarray, fs: int = SAMPLE_RATE
) -> ImpulseResponse:
    """Deconvolve *recorded* by *sweep* (regularised frequency-domain division).

    *recorded* must start before the sweep is played and run long enough to contain the whole
    response; the delay between playing and recording is found automatically.
    """
    n = 1 << (len(recorded) + len(sweep) - 1).bit_length()
    y = np.fft.rfft(recorded, n)
    x = np.fft.rfft(sweep, n)
    power = np.abs(x) ** 2
    eps = 1e-4 * power.max()
    ir = np.fft.irfft(y * np.conj(x) / (power + eps), n)
    usable = ir[: len(recorded)]
    peak = int(np.argmax(np.abs(usable)))
    return ImpulseResponse(usable, fs, peak, detection_db(y, x, n, len(recorded), fs))


def detection_db(y: np.ndarray, x: np.ndarray, n: int, length: int, fs: int) -> float:
    """How clearly the sweep is present in the recording (matched-filter peak vs noise spread).

    Uses plain cross-correlation, whose noise is stationary: pure noise scores about 13 dB,
    a recording that really contains the sweep scores far higher. (The deconvolved impulse
    response is *not* suitable: its noise is coloured and has large random peaks.)
    """
    corr = np.fft.irfft(y * np.conj(x), n)[:length]
    peak = int(np.argmax(np.abs(corr)))
    if abs(corr[peak]) == 0:
        return 0.0  # digital silence: nothing there
    keep = np.ones(length, dtype=bool)
    guard = int(0.05 * fs)
    keep[max(peak - guard, 0) : peak + guard] = False
    sigma = float(np.median(np.abs(corr[keep]))) / 0.6745 or 1e-12
    return 20 * math.log10(abs(corr[peak]) / sigma)


def magnitude_response(
    ir: ImpulseResponse,
    freqs: list[float],
    window_ms: float = 40.0,
    pre_ms: float = 2.0,
    smoothing_octaves: float = 1 / 6,
) -> list[float]:
    """Smoothed magnitude (dB) at *freqs*: window the main peak, FFT, fractional-octave average."""
    pre = int(pre_ms / 1000 * ir.fs)
    length = int(window_ms / 1000 * ir.fs)
    start = max(ir.peak_index - pre, 0)
    seg = ir.samples[start : start + length].copy()
    taper = int(0.2 * len(seg))
    seg[-taper:] *= 0.5 + 0.5 * np.cos(np.linspace(0, math.pi, taper))  # fade the tail out
    n = 1 << 16
    spec = np.abs(np.fft.rfft(seg, n))
    axis = np.fft.rfftfreq(n, 1 / ir.fs)
    out: list[float] = []
    for f in freqs:
        lo, hi = f * 2 ** (-smoothing_octaves / 2), f * 2 ** (smoothing_octaves / 2)
        band = (axis >= lo) & (axis <= hi)
        power = (
            float(np.mean(spec[band] ** 2)) if band.any() else float(np.interp(f, axis, spec) ** 2)
        )
        out.append(10 * math.log10(max(power, 1e-30)))
    return out


def normalise(freqs: list[float], db: list[float], at: float = 1000.0) -> list[float]:
    """Shift so the response is 0 dB at *at* Hz."""
    ref = float(np.interp(math.log(at), np.log(freqs), db))
    return [v - ref for v in db]
