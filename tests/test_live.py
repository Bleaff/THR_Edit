import numpy as np
import pytest

from thr_control.domain import eq, live

FS = 48000
FREQS = eq.log_frequencies(60)


def guitarish(seconds: float, seed: int = 1) -> np.ndarray:
    """Broadband, uneven noise standing in for playing (pinkish: more energy at low frequencies)."""
    rng = np.random.default_rng(seed)
    white = rng.normal(0, 0.1, int(seconds * FS))
    spec = np.fft.rfft(white)
    f = np.fft.rfftfreq(len(white), 1 / FS)
    spec /= np.sqrt(np.maximum(f, 20) / 100)
    return np.fft.irfft(spec, len(white))


def fir(shape_db, length: int = 128, delay: int = 0) -> np.ndarray:
    f = np.fft.rfftfreq(length, 1 / FS)
    mag = 10 ** (np.array([shape_db(x) for x in f]) / 20)
    ir = np.fft.fftshift(np.fft.irfft(mag, length))
    return np.concatenate([np.zeros(delay), ir])


def true_response_db(h: np.ndarray, freqs) -> list[float]:
    """The FIR's actual magnitude response (what the estimator should find), not the ideal shape."""
    n = 1 << 16
    spec = np.abs(np.fft.rfft(h, n))
    axis = np.fft.rfftfreq(n, 1 / FS)
    return [float(20 * np.log10(np.interp(f, axis, spec))) for f in freqs]


def run(est, x, y, block=2048):
    for i in range(0, len(x) - block + 1, block):
        est.push(x[i : i + block], y[i : i + block])


def shape(f):
    return 9 / (1 + (f / 250) ** 4) - 7 / (1 + (4500 / max(f, 1)) ** 4)


def test_recovers_a_known_response_with_latency_and_reports_high_coherence():
    x = guitarish(20)
    h = fir(shape, length=1024, delay=57)  # long enough to realise the shelves faithfully
    y = np.convolve(x, h)[: len(x)] + np.random.default_rng(2).normal(0, 1e-4, len(x))
    est = live.LiveEstimator(lag=57 + 512)  # 57 samples of latency plus the FIR's 512 centre delay
    run(est, x, y)
    res = est.result(FREQS)
    inside = [i for i, f in enumerate(FREQS) if 60 <= f <= 12000]
    assert all(res.valid[i] for i in inside)
    want = true_response_db(h, FREQS)
    ref = want[min(range(len(FREQS)), key=lambda i: abs(FREQS[i] - 1000))]
    got = res.normalised()
    assert max(abs(got[i] - (want[i] - ref)) for i in inside) < 1.0
    assert min(res.coherence[i] for i in inside) > 0.95


def test_long_latency_is_compensated_with_the_lag_setting():
    x = guitarish(25)
    delay = 3000  # a latency large enough to bias the estimate if it is not aligned out
    y = np.convolve(x, fir(lambda f: 6.0, delay=delay))[: len(x)]
    k = min(range(len(FREQS)), key=lambda i: abs(FREQS[i] - 1000))
    plain = live.LiveEstimator()
    run(plain, x, y)
    aligned = live.LiveEstimator(lag=delay + 64)  # fir() adds a 64-sample centre delay
    run(aligned, x, y)
    assert abs(plain.result(FREQS).db[k] - 6.0) > 0.8  # unaligned: visibly biased
    assert aligned.result(FREQS).db[k] == pytest.approx(6.0, abs=0.3)
    assert aligned.result(FREQS).coherence[k] > 0.97
    aligned.set_lag(0)
    assert aligned.frames == 0  # changing the alignment clears the averages


def test_delay_does_not_change_the_estimate():
    x = guitarish(15)
    results = []
    for delay in (0, 57, 400):
        y = np.convolve(x, fir(shape, delay=delay))[: len(x)]
        est = live.LiveEstimator()
        run(est, x, y)
        results.append(est.result(FREQS).normalised())
    for r in results[1:]:
        assert max(abs(a - b) for a, b in zip(r, results[0], strict=True)) < 0.3


def test_nothing_is_reported_before_enough_averaging_or_for_silence():
    x = guitarish(1.5)
    est = live.LiveEstimator()
    run(est, x, x)
    assert 2 <= est.frames < live.MIN_FRAMES and not any(est.result(FREQS).valid)
    longer = live.LiveEstimator()
    run(longer, guitarish(6), guitarish(6))
    run(longer, guitarish(6, seed=3), guitarish(6, seed=3))
    assert longer.frames >= live.MIN_FRAMES and any(longer.result(FREQS).valid)
    quiet = live.LiveEstimator()
    run(quiet, np.zeros(10 * FS), np.zeros(10 * FS))
    assert not any(quiet.result(FREQS).valid)
    assert not any(live.LiveEstimator().result(FREQS).valid)  # no data at all


def test_unrelated_signals_are_not_trusted():
    est = live.LiveEstimator()
    run(est, guitarish(15, seed=1), guitarish(15, seed=7))
    res = est.result(FREQS)
    assert sum(res.valid) <= 2  # coherence of independent noise stays low


def test_strong_distortion_lowers_coherence_but_a_gentle_amp_stays_trusted():
    x = guitarish(20) * 3
    hard = np.tanh(40 * x)  # heavy clipping
    gentle = np.tanh(0.8 * x)
    ch, cg = live.LiveEstimator(), live.LiveEstimator()
    run(ch, x, hard)
    run(cg, x, gentle)
    hard_res, gentle_res = ch.result(FREQS), cg.result(FREQS)
    mid = [i for i, f in enumerate(FREQS) if 300 <= f <= 3000]
    assert (
        np.mean([gentle_res.coherence[i] for i in mid])
        > np.mean([hard_res.coherence[i] for i in mid]) + 0.1
    )


def test_the_estimate_follows_a_change_of_settings():
    est = live.LiveEstimator(seconds=2.0)
    x = guitarish(40)
    first, second = (
        np.convolve(x[: 20 * FS], fir(lambda f: 6.0))[: 20 * FS],
        np.convolve(x[20 * FS :], fir(lambda f: -6.0))[: 20 * FS],
    )
    run(est, x[: 20 * FS], first)
    before = est.result(FREQS).db
    run(est, x[20 * FS :], second)
    after = est.result(FREQS).db
    k = min(range(len(FREQS)), key=lambda i: abs(FREQS[i] - 1000))
    assert before[k] == pytest.approx(6.0, abs=0.5) and after[k] == pytest.approx(-6.0, abs=0.7)


def test_push_validates_lengths_and_reset_clears():
    est = live.LiveEstimator()
    with pytest.raises(ValueError):
        est.push(np.zeros(10), np.zeros(11))
    run(est, guitarish(3), guitarish(3))
    assert est.frames > 0
    est.reset()
    assert est.frames == 0


# -- the streaming service, with a fake capture source -----------------------------------------
from thr_control.services import audio  # noqa: E402
from thr_control.services import live as live_service  # noqa: E402


class ArraySource:
    """A BlockSource that replays a recording in blocks, then ends (like a finished stream)."""

    def __init__(self, frames: np.ndarray, block: int = 4096):
        self._frames, self._pos, self._block = frames, 0, block
        self.closed = False

    def read(self):
        if self.closed or self._pos >= len(self._frames):
            return None
        chunk = self._frames[self._pos : self._pos + self._block]
        self._pos += self._block
        return chunk

    def close(self):
        self.closed = True


def stream_frames(dry: np.ndarray, wet: np.ndarray) -> np.ndarray:
    """4-channel frames: channels 1+2 = wet, 3+4 = dry (as on the amp)."""
    return np.stack([wet, wet, dry, dry], axis=1)


def make_stream(frames: np.ndarray, freqs=None):
    node = audio.Node(72, "alsa_input.thr", "THR5 Analog Surround 4.0", "source")
    opened = []

    def opener(n):
        opened.append((n, ArraySource(frames)))
        return opened[-1][1]

    return live_service.LiveStream(node, freqs or FREQS, opener=opener), opened


def test_stream_finds_the_latency_and_publishes_the_response():
    dry = guitarish(25) * 0.5
    h = fir(shape, length=1024, delay=57)
    wet = np.convolve(dry, h)[: len(dry)]
    stream, opened = make_stream(stream_frames(dry, wet))
    stream.start()
    stream.join(20)
    snap = stream.snapshot()
    assert opened[0][0].id == 72  # opened the source it was given
    assert snap.status == "ended" and snap.error is None
    assert snap.lag_samples is not None and abs(snap.lag_samples - (57 + 512)) <= 2
    inside = [i for i, f in enumerate(FREQS) if 60 <= f <= 12000]
    want = true_response_db(h, FREQS)
    ref = want[min(range(len(FREQS)), key=lambda i: abs(FREQS[i] - 1000))]
    got = snap.result.normalised()
    assert all(snap.result.valid[i] for i in inside)
    assert max(abs(got[i] - (want[i] - ref)) for i in inside) < 1.0
    assert -50 < snap.dry_dbfs < -30  # the level of the simulated playing


def test_stream_waits_while_the_input_is_silent():
    stream, _ = make_stream(stream_frames(np.zeros(5 * FS), np.zeros(5 * FS)))
    stream.start()
    stream.join(10)
    snap = stream.snapshot()
    assert snap.result is None and snap.lag_samples is None
    assert snap.dry_dbfs < -100


def test_stream_reports_unrelated_channels_as_unaligned_and_untrusted():
    frames = stream_frames(guitarish(20, seed=1) * 0.5, guitarish(20, seed=9) * 0.5)
    stream, _ = make_stream(frames)
    stream.start()
    stream.join(20)
    snap = stream.snapshot()
    assert snap.lag_samples is None and sum(snap.result.valid) <= 2


def test_stream_reports_a_failure_to_start_and_stops_cleanly():
    node = audio.Node(72, "alsa_input.thr", "THR5", "source")

    def broken(n):
        raise audio.AudioError("cannot start pw-record: not found")

    s = live_service.LiveStream(node, FREQS, opener=broken)
    s.start()
    snap = s.snapshot()
    assert snap.status == "error" and "pw-record" in snap.error
    s.stop()  # safe even though nothing ran
    ok, opened = make_stream(stream_frames(guitarish(2), guitarish(2)))
    ok.start()
    ok.stop()
    assert opened[0][1].closed  # stopping closes the capture so a blocked read is released


def test_stream_turns_a_read_failure_into_an_error_status():
    class Broken(ArraySource):
        def read(self):
            raise OSError("device unplugged")

    node = audio.Node(72, "alsa_input.thr", "THR5", "source")
    s = live_service.LiveStream(node, FREQS, opener=lambda n: Broken(np.zeros((10, 4))))
    s.start()
    s.join(5)
    snap = s.snapshot()
    assert snap.status == "error" and "unplugged" in snap.error


def test_cli_audio_live_prints_a_table_from_the_stream(monkeypatch, capsys):
    from thr_control import cli

    dry = guitarish(25) * 0.5
    wet = np.convolve(dry, fir(lambda f: 6.0 if f < 400 else 0.0, length=1024, delay=57))[
        : len(dry)
    ]
    nodes = [audio.Node(72, "alsa_input.thr", "THR5 Analog Surround 4.0", "source")]
    monkeypatch.setattr(audio, "list_nodes", lambda: nodes)
    frames = stream_frames(dry, wet)

    class Fast(live_service.LiveStream):
        def __init__(self, source, *a, **k):
            super().__init__(source, opener=lambda n: ArraySource(frames))

    monkeypatch.setattr(live_service, "LiveStream", Fast)
    import time as _time

    real_sleep = _time.sleep
    monkeypatch.setattr(cli.time, "sleep", lambda s: real_sleep(0.3))
    assert cli.main(["audio", "live", "--seconds", "4"]) == 0
    out = capsys.readouterr().out
    assert "Play your guitar" in out and "relative to 1 kHz" in out
    rows = [ln for ln in out.splitlines() if "|" in ln and "status" not in ln]
    assert rows and any("measuring" in r or "ended" in r for r in rows)
    last = rows[-1].split("|")[1].split()
    assert last[0] != "--" or len(last) == 8  # row has one cell per table frequency
