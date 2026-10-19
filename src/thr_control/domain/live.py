"""Live transfer-function estimate: output spectrum over input spectrum, from a running stream.

Feed it time-aligned blocks of the amp's *dry* input (x) and *processed* output (y) while the
guitar plays. It keeps exponentially averaged power spectra and estimates, per band, the gain of
the path x -> y and how coherent the two signals are. Where the path is strongly non-linear
(distortion) or the guitar does not excite a band, coherence drops and the band is not reported.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

import numpy as np

COHERENCE_MIN = 0.6  # bands below this are not trusted
SIGNAL_RANGE_DB = 60.0  # a band this far below the strongest input band is not trusted
MIN_FRAMES = 20  # about two seconds of playing: fewer averages bias coherence upwards


@dataclass(frozen=True)
class LiveResult:
    freqs: list[float]
    db: list[float]  # gain of the path in dB (absolute, not normalised)
    coherence: list[float]
    valid: list[bool]
    frames: int

    def normalised(self, at: float = 1000.0) -> list[float]:
        """Gain shifted so it is 0 dB at *at* Hz (shape only), interpolating over valid bands."""
        pts = [
            (math.log(f), d) for f, d, ok in zip(self.freqs, self.db, self.valid, strict=True) if ok
        ]
        if not pts:
            return list(self.db)
        xs, ys = zip(*pts, strict=True)
        ref = float(np.interp(math.log(at), xs, ys))
        return [d - ref for d in self.db]


class LiveEstimator:
    def __init__(
        self, fs: int = 48000, nfft: int = 8192, seconds: float = 3.0, lag: int = 0
    ) -> None:
        """*lag*: how many samples y is later than x (the amp's latency); y is advanced by it."""
        self.fs = fs
        self.lag = lag
        self._skip = lag
        self.nfft = nfft
        self.hop = nfft // 2
        self._weight = min(1.0, self.hop / (fs * seconds))
        self._window = np.hanning(nfft)
        bins = nfft // 2 + 1
        self._sxx = np.zeros(bins)
        self._syy = np.zeros(bins)
        self._sxy = np.zeros(bins, dtype=complex)
        self._axis = np.fft.rfftfreq(nfft, 1 / fs)
        self._x = np.zeros(0)
        self._y = np.zeros(0)
        self.frames = 0

    def set_lag(self, lag: int) -> None:
        """Change the alignment; clears everything averaged so far."""
        self.lag = lag
        self.reset()

    def reset(self) -> None:
        self._sxx[:] = 0
        self._syy[:] = 0
        self._sxy[:] = 0
        self._x = np.zeros(0)
        self._y = np.zeros(0)
        self._skip = self.lag
        self.frames = 0

    def push(self, x: np.ndarray, y: np.ndarray) -> None:
        if len(x) != len(y):
            raise ValueError("x and y must have the same length")
        if self._skip:
            # y is *lag* samples later than x. Dropping the first *lag* samples of y pairs x[n]
            # with y[n + lag]; from then on x's buffer is simply that far ahead of y's.
            drop = min(self._skip, len(y))
            y = y[drop:]
            self._skip -= drop
        self._x = np.concatenate([self._x, x])
        self._y = np.concatenate([self._y, y])
        while len(self._x) >= self.nfft and len(self._y) >= self.nfft:
            fx = np.fft.rfft(self._x[: self.nfft] * self._window)
            fy = np.fft.rfft(self._y[: self.nfft] * self._window)
            w = max(self._weight, 1.0 / (self.frames + 1))
            self._sxx += w * (np.abs(fx) ** 2 - self._sxx)
            self._syy += w * (np.abs(fy) ** 2 - self._syy)
            self._sxy += w * (np.conj(fx) * fy - self._sxy)
            self.frames += 1
            self._x = self._x[self.hop :]
            self._y = self._y[self.hop :]

    def result(self, freqs: list[float], octaves: float = 1 / 6) -> LiveResult:
        """Per-band gain and coherence at *freqs*, averaged over fractional-octave bands.

        Everything is combined from per-bin *powers*, so a time delay between x and y (the
        amp's roughly 1 ms of latency) does not affect the result.
        """
        n = len(freqs)
        if self.frames < 2:
            return LiveResult(freqs, [0.0] * n, [0.0] * n, [False] * n, self.frames)
        sxx, syy, sxy = self._sxx, self._syy, self._sxy
        floor = 1e-30
        gain_num = np.abs(sxy) ** 2 / np.maximum(sxx, floor)  # |Sxy|^2 / Sxx  (= Sxx |H|^2)
        coh_bin = np.abs(sxy) ** 2 / np.maximum(sxx * syy, floor)
        db: list[float] = []
        coh: list[float] = []
        band_power: list[float] = []
        for f in freqs:
            lo, hi = f * 2 ** (-octaves / 2), f * 2 ** (octaves / 2)
            sel = (self._axis >= lo) & (self._axis <= hi)
            if not sel.any():
                db.append(0.0)
                coh.append(0.0)
                band_power.append(0.0)
                continue
            px = float(sxx[sel].sum())
            band_power.append(px)
            db.append(10 * math.log10(max(float(gain_num[sel].sum()) / max(px, floor), floor)))
            coh.append(float((coh_bin[sel] * sxx[sel]).sum() / max(px, floor)))
        top = max(band_power) or 1.0
        enough = self.frames >= MIN_FRAMES
        valid = [
            enough and c >= COHERENCE_MIN and p > top * 10 ** (-SIGNAL_RANGE_DB / 10)
            for c, p in zip(coh, band_power, strict=True)
        ]
        return LiveResult(freqs, db, coh, valid, self.frames)
