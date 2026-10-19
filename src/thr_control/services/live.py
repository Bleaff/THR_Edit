"""Live stream from the amp's USB audio into a transfer-function estimate.

Reads the 4-channel capture (through whichever audio backend is active) on a background
thread. Channels 3+4 are the dry input and 1+2 the processed output (observed on a THR5A,
see docs/protocol.md). The amp's latency between them is found automatically from the first
seconds of playing, then the running estimate is published through
:meth:`LiveStream.snapshot`.
"""

from __future__ import annotations

import threading
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

import numpy as np

from ..domain import eq, measure
from ..domain.live import LiveEstimator, LiveResult
from . import audio

CHANNELS = audio.RECORD_CHANNELS
WET = (0, 1)  # channels 1+2: processed
DRY = (2, 3)  # channels 3+4: unprocessed input
CALIBRATION_SECONDS = 3.0
ACTIVE_DBFS = -55.0  # dry level that counts as "playing" when calibrating
MAX_LAG = 2400  # samples (50 ms)


@dataclass(frozen=True)
class LiveSnapshot:
    status: (
        str  # "starting" | "waiting for signal" | "calibrating" | "measuring" | "ended" | "error"
    )
    error: str | None
    result: LiveResult | None
    dry_dbfs: float
    wet_dbfs: float
    lag_samples: int | None


def _dbfs(x: np.ndarray) -> float:
    rms = float(np.sqrt(np.mean(x**2))) if len(x) else 0.0
    return 20 * np.log10(rms) if rms > 0 else -240.0


class LiveStream:
    def __init__(
        self,
        source: audio.Node,
        freqs: list[float] | None = None,
        opener: Callable[[audio.Node], audio.BlockSource] | None = None,
        fs: int = measure.SAMPLE_RATE,
    ) -> None:
        self.source = source
        self.freqs = freqs or eq.log_frequencies(120)
        self._opener = opener or (lambda node: audio.open_capture(node, fs, CHANNELS))
        self._fs = fs
        self._est = LiveEstimator(fs)
        self._lock = threading.Lock()
        self._status = "starting"
        self._error: str | None = None
        self._dry_db = self._wet_db = -240.0
        self._lag: int | None = None
        self._src: audio.BlockSource | None = None
        self._thread: threading.Thread | None = None
        self._stop = threading.Event()

    # -- control -----------------------------------------------------------
    def start(self) -> None:
        try:
            self._src = self._opener(self.source)
        except (audio.AudioError, OSError) as exc:
            self._set(status="error", error=str(exc))
            return
        self._thread = threading.Thread(target=self._run, name="thr-live", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        if self._src is not None:
            self._src.close()  # also unblocks a read() that is waiting for data
        if self._thread is not None:
            self._thread.join(timeout=3)

    def join(self, timeout: float | None = None) -> None:
        if self._thread is not None:
            self._thread.join(timeout)

    def snapshot(self) -> LiveSnapshot:
        with self._lock:
            result = self._est.result(self.freqs) if self._est.frames else None
            return LiveSnapshot(
                self._status, self._error, result, self._dry_db, self._wet_db, self._lag
            )

    # -- worker ------------------------------------------------------------
    def _set(self, **kw: Any) -> None:
        with self._lock:
            if "status" in kw:
                self._status = kw["status"]
            if "error" in kw:
                self._error = kw["error"]

    def _run(self) -> None:
        assert self._src is not None
        calib_x: list[np.ndarray] = []
        calib_y: list[np.ndarray] = []
        calib_len = 0
        calibrated = False
        self._set(status="waiting for signal")
        while not self._stop.is_set():
            try:
                frames = self._src.read()
            except Exception as exc:
                if not self._stop.is_set():
                    self._set(status="error", error=str(exc))
                return
            if frames is None:
                break
            x = frames[:, list(DRY)].mean(axis=1)
            y = frames[:, list(WET)].mean(axis=1)
            with self._lock:
                self._dry_db, self._wet_db = _dbfs(x), _dbfs(y)
            if calibrated:
                with self._lock:
                    self._est.push(x, y)
                continue
            if self._dry_db > ACTIVE_DBFS:
                calib_x.append(x)
                calib_y.append(y)
                calib_len += len(x)
                self._set(status="calibrating")
            if calib_len >= CALIBRATION_SECONDS * self._fs:
                cx, cy = np.concatenate(calib_x), np.concatenate(calib_y)
                lag, corr = audio.pair_relation(cy, cx, self._fs, max_ms=MAX_LAG / self._fs * 1000)
                with self._lock:
                    if abs(corr) >= 0.4 and 0 <= lag <= MAX_LAG:
                        self._lag = lag
                        self._est.set_lag(lag)
                    else:
                        self._lag = None  # alignment unknown: measure unaligned
                    self._est.push(cx, cy)
                calibrated = True
                self._set(status="measuring")
        if self._stop.is_set():
            return
        self._set(status="ended")
