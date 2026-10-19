"""Illustrative 3-band EQ response.

The real filter frequencies and gains of the amp are NOT known; this is a plausible
low-shelf / peaking / high-shelf model (RBJ cookbook biquads) used only to draw a
curve that reacts to the bass, middle and treble values. It is not measured.
"""

from __future__ import annotations

import cmath
import math

SAMPLE_RATE = 48000.0
MAX_BOOST_DB = 12.0
# (kind, centre/corner Hz, Q) for bass, middle, treble.
BANDS = (("low_shelf", 120.0, 0.7), ("peak", 800.0, 0.8), ("high_shelf", 3500.0, 0.7))


def band_gain_db(value: int) -> float:
    """Knob value 0-100 (50 = flat) to dB."""
    return (value - 50) / 50 * MAX_BOOST_DB


def _coefficients(
    kind: str, f0: float, q: float, gain_db: float
) -> tuple[list[float], list[float]]:
    a = 10 ** (gain_db / 40)
    w0 = 2 * math.pi * f0 / SAMPLE_RATE
    cos_w, sin_w = math.cos(w0), math.sin(w0)
    alpha = sin_w / (2 * q)
    if kind == "peak":
        b = [1 + alpha * a, -2 * cos_w, 1 - alpha * a]
        den = [1 + alpha / a, -2 * cos_w, 1 - alpha / a]
    else:
        sign = 1 if kind == "low_shelf" else -1
        beta = 2 * math.sqrt(a) * alpha
        b = [
            a * ((a + 1) - sign * (a - 1) * cos_w + beta),
            sign * 2 * a * ((a - 1) - sign * (a + 1) * cos_w),
            a * ((a + 1) - sign * (a - 1) * cos_w - beta),
        ]
        den = [
            (a + 1) + sign * (a - 1) * cos_w + beta,
            -sign * 2 * ((a - 1) + sign * (a + 1) * cos_w),
            (a + 1) + sign * (a - 1) * cos_w - beta,
        ]
    return b, den


def _magnitude_db(b: list[float], den: list[float], freq: float) -> float:
    z = cmath.exp(-1j * 2 * math.pi * freq / SAMPLE_RATE)
    num = b[0] + b[1] * z + b[2] * z * z
    dd = den[0] + den[1] * z + den[2] * z * z
    return 20 * math.log10(abs(num / dd))


def response_db(freqs: list[float], bass: int, middle: int, treble: int) -> list[float]:
    """Combined response in dB at each frequency for the three knob values."""
    stages = [
        _coefficients(kind, f0, q, band_gain_db(v))
        for (kind, f0, q), v in zip(BANDS, (bass, middle, treble), strict=True)
    ]
    return [sum(_magnitude_db(b, d, f) for b, d in stages) for f in freqs]


def log_frequencies(points: int = 120, low: float = 20.0, high: float = 20000.0) -> list[float]:
    ratio = (high / low) ** (1 / (points - 1))
    return [low * ratio**i for i in range(points)]
