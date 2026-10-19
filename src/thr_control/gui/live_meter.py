"""Connects the live audio stream to the EQ curve and a status label."""

from __future__ import annotations

from collections.abc import Callable

from PySide6.QtCore import QObject, QTimer
from PySide6.QtWidgets import QLabel

from ..services import audio
from ..services.live import LiveSnapshot, LiveStream
from .eq_curve import EqCurve

MIN_VALID_BANDS = 8  # fewer trusted bands than this is not drawn as a curve


def default_stream_factory() -> LiveStream:
    sink, source = audio.find_thr(audio.list_nodes())
    if source is None:
        raise audio.AudioError("the THR's USB audio is not available")
    return LiveStream(source)


class LiveMeter(QObject):
    def __init__(
        self,
        curve: EqCurve,
        label: QLabel,
        factory: Callable[[], LiveStream] = default_stream_factory,
    ) -> None:
        super().__init__()
        self.curve = curve
        self.label = label
        self._factory = factory
        self._stream: LiveStream | None = None
        self._timer = QTimer(self)
        self._timer.setInterval(100)
        self._timer.timeout.connect(self.update_now)

    @property
    def running(self) -> bool:
        return self._stream is not None

    def start(self) -> bool:
        if self._stream is not None:
            return True
        try:
            stream = self._factory()
            stream.start()
        except (audio.AudioError, OSError) as exc:
            self.label.setText(f"Live measurement unavailable: {exc}")
            return False
        self._stream = stream
        self.label.setText("Starting…")
        self._timer.start()
        return True

    def stop(self) -> None:
        self._timer.stop()
        if self._stream is not None:
            self._stream.stop()
            self._stream = None
        self.curve.clear_measured()
        self.label.setText("")

    def update_now(self) -> None:
        if self._stream is None:
            return
        self._show(self._stream.snapshot())

    def _show(self, snap: LiveSnapshot) -> None:
        if snap.status == "error":
            self.label.setText(f"Live measurement failed: {snap.error}")
            self.curve.clear_measured()
            return
        if snap.status == "waiting for signal":
            self.label.setText("Play your guitar: no signal on the amp's input yet")
            self.curve.clear_measured()
            return
        if snap.status == "calibrating":
            self.label.setText("Keep playing: finding the amp's latency…")
            return
        if snap.status == "ended":
            self.label.setText("The audio stream ended")
            self.curve.clear_measured()
            return
        result = snap.result
        trusted = sum(result.valid) if result else 0
        if result is None or trusted < MIN_VALID_BANDS:
            self.label.setText(
                "Play more notes across the neck: not enough signal to trust a curve yet"
            )
            self.curve.clear_measured()
            return
        self.curve.set_measured(result.freqs, result.normalised(), result.valid, result.coherence)
        lag = f", latency {snap.lag_samples / 48:.1f} ms" if snap.lag_samples is not None else ""
        self.label.setText(
            f"Measured live (blue): shape relative to 1 kHz, "
            f"{trusted} of {len(result.valid)} bands trusted{lag}"
        )
