import numpy as np
import pytest

from thr_control.domain import eq, measure

FS = measure.SAMPLE_RATE
FREQS = eq.log_frequencies(80)


def through(
    system_fir: np.ndarray, sweep: np.ndarray, lead: int = 4800, noise: float = 0.0
) -> np.ndarray:
    """What a recorder would capture: silence, then the sweep through a system, plus a tail."""
    out = np.convolve(sweep, system_fir)
    rec = np.concatenate([np.zeros(lead), out, np.zeros(FS // 2)])
    if noise:
        rec = rec + np.random.default_rng(1).normal(0, noise, len(rec))
    return rec


def fir_from_db(shape_db, delay: int = 0, length: int = 4096) -> np.ndarray:
    """Zero-phase FIR whose magnitude (dB) is shape_db(freq), optionally delayed."""
    f = np.fft.rfftfreq(length, 1 / FS)
    mag = 10 ** (np.array([shape_db(x) for x in f]) / 20)
    ir = np.fft.fftshift(np.fft.irfft(mag, length))
    return np.concatenate([np.zeros(delay), ir])


def test_sweep_levels_and_safety_limit():
    s = measure.log_sweep(1.0, dbfs=-30)
    assert len(s) == FS and abs(s).max() == pytest.approx(10 ** (-30 / 20), rel=0.02)
    assert s[0] == 0 and abs(s[-1]) < 1e-6  # faded in and out
    with pytest.raises(ValueError, match="safety limit"):
        measure.log_sweep(1.0, dbfs=-3)
    assert measure.db_to_amplitude(-12) == pytest.approx(0.2512, abs=1e-3)


def test_recovers_a_known_response_and_latency():
    sweep = measure.log_sweep(3.0, dbfs=-20)

    # +9 dB low shelf (below ~200 Hz), -6 dB high shelf (above ~5 kHz), 25 ms of latency
    def shape(f):
        low = 9 / (1 + (f / 200) ** 4)
        high = -6 / (1 + (5000 / max(f, 1)) ** 4)
        return low + high

    fir = fir_from_db(shape, delay=int(0.025 * FS))
    ir = measure.impulse_response(through(fir, sweep), sweep)
    assert ir.latency_ms == pytest.approx(25 + 4800 / FS * 1000 + 2048 / FS * 1000, abs=1.5)
    got = measure.magnitude_response(ir, FREQS)
    want = [shape(f) for f in FREQS]
    got_n = measure.normalise(FREQS, got)
    want_n = measure.normalise(FREQS, want)
    inside = [i for i, f in enumerate(FREQS) if 40 <= f <= 15000]
    worst = max(abs(got_n[i] - want_n[i]) for i in inside)
    assert worst < 1.0, f"worst error {worst:.2f} dB"


def test_flat_system_measures_flat_and_gain_is_preserved():
    sweep = measure.log_sweep(3.0, dbfs=-20)
    half = np.zeros(8)
    half[0] = 0.5  # -6.02 dB, no colouration
    ir = measure.impulse_response(through(half, sweep), sweep)
    got = measure.magnitude_response(ir, FREQS)
    inside = [g for g, f in zip(got, FREQS, strict=True) if 40 <= f <= 15000]
    assert max(inside) - min(inside) < 0.6
    assert np.mean(inside) == pytest.approx(-6.02, abs=0.8)


def test_noise_floor_estimate_and_detection_of_absent_signal():
    sweep = measure.log_sweep(3.0, dbfs=-20)
    h = np.zeros(4)
    h[0] = 1.0
    loud = measure.impulse_response(through(h, sweep, noise=1e-4), sweep)
    quiet = measure.impulse_response(through(h, sweep, noise=3e-2), sweep)
    assert loud.peak_to_noise_db > quiet.peak_to_noise_db + 20
    only_noise = np.random.default_rng(2).normal(0, 1e-3, 5 * FS)
    absent = measure.impulse_response(only_noise, sweep)
    assert absent.peak_to_noise_db < 20  # noise alone looks like noise
    assert loud.peak_to_noise_db > 40  # a real signal stands out clearly
    assert loud.peak_to_noise_db > measure.DETECTION_THRESHOLD_DB


def test_normalise_pins_one_kilohertz_to_zero():
    db = [3.0 + 0.001 * f for f in FREQS]
    n = measure.normalise(FREQS, db)
    k = min(range(len(FREQS)), key=lambda i: abs(FREQS[i] - 1000))
    assert abs(n[k]) < 0.05


# -- audio orchestration (no sound is played in tests) -----------------------------------------
def test_parse_pw_dump_nodes_and_find_thr():
    import json

    from thr_control.services import audio

    dump = json.dumps(
        [
            {
                "id": 35,
                "type": "PipeWire:Interface:Node",
                "info": {
                    "props": {
                        "media.class": "Audio/Sink",
                        "node.name": "alsa_output.pci.analog",
                        "node.description": "Starship Analog",
                    }
                },
            },
            {
                "id": 80,
                "type": "PipeWire:Interface:Node",
                "info": {
                    "props": {
                        "media.class": "Audio/Sink",
                        "node.name": "alsa_output.usb-Yamaha_THR5.analog-stereo",
                        "node.description": "THR5 Analog Stereo",
                    }
                },
            },
            {
                "id": 72,
                "type": "PipeWire:Interface:Node",
                "info": {
                    "props": {
                        "media.class": "Audio/Source",
                        "node.name": "alsa_input.usb-Yamaha_THR5.analog-surround-40",
                        "node.description": "THR5 Analog Surround 4.0",
                    }
                },
            },
            {"id": 5, "type": "PipeWire:Interface:Client", "info": {"props": {}}},
            {
                "id": 6,
                "type": "PipeWire:Interface:Node",
                "info": {"props": {"media.class": "Video/Source"}},
            },
        ]
    )
    nodes = audio.parse_nodes(dump)
    assert [n.id for n in nodes] == [35, 80, 72]
    sink, source = audio.find_thr(nodes)
    assert sink and sink.name.endswith("analog-stereo") and source and source.id == 72
    assert audio.find_thr([nodes[0]]) == (None, None)


def test_wav_roundtrip_and_channel_analysis(tmp_path):
    from thr_control.services import audio

    sweep = measure.log_sweep(2.0, dbfs=-20)
    audio.write_wav(tmp_path / "s.wav", sweep, FS, channels=2)
    data, rate = audio.read_wav(tmp_path / "s.wav")
    assert rate == FS and data.shape == (len(sweep), 2)
    assert np.max(np.abs(data[:, 0] - sweep)) < 1e-6
    # a 4-channel recording where only channel 3 carries the sweep (delayed, -6 dB)
    rec = np.zeros((len(sweep) + FS, 4))
    rec[:, 0] = np.random.default_rng(0).normal(0, 1e-4, len(rec))
    rec[:, 1] = rec[:, 0]
    rec[2400 : 2400 + len(sweep), 2] = 0.5 * sweep
    reports = audio.analyse_channels(rec, sweep)
    assert [r.carries_sweep for r in reports] == [False, False, True, False]
    assert reports[2].detection_db > 60 and reports[0].detection_db < 25


def test_digital_silence_is_reported_as_no_signal():
    sweep = measure.log_sweep(2.0, dbfs=-20)
    ir = measure.impulse_response(np.zeros(3 * FS), sweep)
    assert ir.peak_to_noise_db == 0.0


def test_cli_audio_dry_run_plays_nothing_and_enforces_level(monkeypatch, capsys):
    from thr_control import cli
    from thr_control.services import audio

    nodes = [
        audio.Node(80, "alsa_output.thr", "THR5 Analog Stereo", "sink"),
        audio.Node(72, "alsa_input.thr", "THR5 Analog Surround 4.0", "source"),
    ]
    monkeypatch.setattr(audio, "list_nodes", lambda: nodes)

    def boom(*a, **k):
        raise AssertionError("must not play in a dry run")

    monkeypatch.setattr(audio, "play_and_record", boom)
    assert cli.main(["audio", "devices"]) == 0
    assert "<- THR" in capsys.readouterr().out
    assert cli.main(["audio", "probe"]) == 0
    assert "Dry run" in capsys.readouterr().out
    assert cli.main(["audio", "probe", "--level", "-3", "--yes"]) == 1  # above the safety limit
    assert "safety limit" in capsys.readouterr().err
    monkeypatch.setattr(audio, "list_nodes", lambda: [])
    assert cli.main(["audio", "probe", "--yes"]) == 1  # no THR audio


# -- the whole `audio measure` path, with a simulated amp and no sound ---------------------------
def _simulated_recording(sweep, shape_db):
    """4 channels: 1 and 2 carry the sweep through the given response; 3 and 4 are silent."""
    f = np.fft.rfftfreq(4096, 1 / FS)
    mag = 10 ** (np.array([shape_db(x) for x in f]) / 20)
    fir = np.fft.fftshift(np.fft.irfft(mag, 4096))
    wet = np.convolve(sweep, fir)
    rec = np.zeros((len(wet) + 4800 + FS, 4))
    rec[4800 : 4800 + len(wet), 0] = wet
    rec[4800 : 4800 + len(wet), 1] = wet
    return rec


def test_audio_measure_saves_channels_with_amp_settings(monkeypatch, tmp_path, capsys):
    import json

    from tests.fake_amp import FakeAmp, real_payload
    from thr_control import cli
    from thr_control.services import audio
    from thr_control.services.controller import ThrController
    from thr_control.storage import measurements

    nodes = [
        audio.Node(35, "alsa_output.pc", "PC Analog Stereo", "sink"),
        audio.Node(80, "alsa_output.thr", "THR5 Analog Stereo", "sink"),
        audio.Node(72, "alsa_input.thr", "THR5 Analog Surround 4.0", "source"),
    ]
    monkeypatch.setattr(audio, "list_nodes", lambda: nodes)
    shape = lambda f: 8 / (1 + (f / 300) ** 4) - 10 / (1 + (4000 / max(f, 1)) ** 4)  # noqa: E731
    played = {}

    def fake_play(sweep, sink, source, **kw):
        played["sink"] = sink.id
        return _simulated_recording(sweep, shape)

    monkeypatch.setattr(audio, "play_and_record", fake_play)

    class T:
        def close(self):
            pass

    monkeypatch.setattr(
        cli, "_open_controller", lambda: (T(), ThrController(FakeAmp(real_payload()), settle=0))
    )
    args = [
        "audio",
        "measure",
        "--sink",
        "35",
        "--level",
        "-50",
        "--duration",
        "3",
        "--dir",
        str(tmp_path),
        "--yes",
    ]
    assert cli.main(args) == 0
    out = capsys.readouterr().out
    assert played["sink"] == 35  # played to the PC's output, not the amp's USB
    assert "Channels with the sweep: [1, 2]" in out
    files = measurements.list_saved(tmp_path)
    assert len(files) == 1 and files[0].name.endswith("-amp2.json")  # real fixture dump has amp=2
    m = measurements.load(files[0])
    assert (
        m.settings["amp"] == 2 and m.level_dbfs == -50 and [c.channel for c in m.channels] == [1, 2]
    )
    freqs = m.channels[0].freqs
    want = [shape(f) for f in freqs]
    want = [w - float(np.interp(np.log(1000), np.log(freqs), want)) for w in want]
    inside = [i for i, f in enumerate(freqs) if 50 <= f <= 12000]
    assert max(abs(m.channels[0].db[i] - want[i]) for i in inside) < 1.2
    assert json.loads(files[0].read_text())["format"] == "thr-control-measurement"
    # showing it again prints the same table
    assert cli.main(["audio", "show", str(files[0])]) == 0
    assert "channel |" in capsys.readouterr().out
    # unknown node ids are rejected
    assert cli.main(["audio", "measure", "--sink", "999", "--yes"]) == 1


def test_audio_measure_explains_when_nothing_is_recorded(monkeypatch, tmp_path, capsys):
    from thr_control import cli
    from thr_control.services import audio

    nodes = [
        audio.Node(80, "alsa_output.thr", "THR5 Analog Stereo", "sink"),
        audio.Node(72, "alsa_input.thr", "THR5 Analog Surround 4.0", "source"),
    ]
    monkeypatch.setattr(audio, "list_nodes", lambda: nodes)
    monkeypatch.setattr(
        audio, "play_and_record", lambda sweep, sink, source, **kw: np.zeros((6 * FS, 4))
    )
    assert cli.main(["audio", "measure", "--dir", str(tmp_path), "--yes"]) == 1
    err = capsys.readouterr().err
    assert "guitar input" in err and "--sink" in err
    assert not list(tmp_path.glob("*.json"))


# -- recording takes ---------------------------------------------------------------------------
def test_pcm24_roundtrip_is_exact_to_24_bits(tmp_path):
    from thr_control.services import audio

    x = np.random.default_rng(3).uniform(-0.9, 0.9, (5000, 2))
    audio.write_pcm24(tmp_path / "a.wav", x, FS)
    y, rate = audio.read_wav(tmp_path / "a.wav")
    assert rate == FS and y.shape == x.shape
    assert np.max(np.abs(x - y)) <= 0.51 / 8388608  # rounding error: at most half a 24-bit step
    audio.write_pcm24(tmp_path / "n.wav", np.array([[-1.0, 1.0], [0.0, -0.5]]), FS)
    z, _ = audio.read_wav(tmp_path / "n.wav")
    assert z[0, 0] == pytest.approx(-1.0, abs=2e-7) and z[0, 1] == pytest.approx(1.0, abs=2e-7)


def test_level_report_correlation_and_brightness():
    from thr_control.services import audio

    t = np.arange(FS) / FS
    quiet, loud = 0.003 * np.sin(2 * np.pi * 440 * t), 1.0 * np.sin(2 * np.pi * 440 * t)
    lv = audio.level_report(np.stack([quiet, loud, np.zeros(FS)], axis=1))
    assert [x.active for x in lv] == [True, True, False]
    assert not lv[0].clipping and lv[1].clipping
    assert lv[1].peak_dbfs == pytest.approx(0.0, abs=0.05)
    assert audio.correlation(loud, loud) == pytest.approx(1.0)
    assert audio.correlation(loud, np.sin(2 * np.pi * 1234 * t)) < 0.05
    assert audio.correlation(np.zeros(10), np.ones(10)) == 0.0
    low = audio.spectral_centroid(np.sin(2 * np.pi * 300 * t))
    high = audio.spectral_centroid(np.sin(2 * np.pi * 3000 * t))
    assert 250 < low < 350 and 2800 < high < 3200 and audio.spectral_centroid(np.zeros(1000)) == 0.0


def _fake_take(monkeypatch, make):
    """Make audio.record write a synthetic 4-channel recording produced by make(t)."""
    from thr_control.services import audio

    nodes = [audio.Node(72, "alsa_input.thr", "THR5 Analog Surround 4.0", "source")]
    monkeypatch.setattr(audio, "list_nodes", lambda: nodes)

    def fake_record(source, seconds, path, **kw):
        t = np.arange(int(seconds * FS)) / FS
        audio.write_wav_multichannel(path, make(t), FS) if hasattr(
            audio, "write_wav_multichannel"
        ) else None
        pcm = (np.clip(make(t), -1, 1) * 2147483647).astype("<i4")
        import wave

        with wave.open(str(path), "wb") as w:
            w.setnchannels(pcm.shape[1])
            w.setsampwidth(4)
            w.setframerate(FS)
            w.writeframes(pcm.tobytes())

    monkeypatch.setattr(audio, "record", fake_record)


def test_cli_record_saves_active_pairs_and_amp_settings(monkeypatch, tmp_path, capsys):
    import json

    from tests.fake_amp import FakeAmp, real_payload
    from thr_control import cli
    from thr_control.services import audio
    from thr_control.services.controller import ThrController

    def make(t):
        guitar = 0.3 * np.sin(2 * np.pi * 220 * t) + 0.1 * np.sin(2 * np.pi * 3300 * t)
        dry = 0.3 * np.sin(2 * np.pi * 220 * t)
        return np.stack([guitar, guitar, dry, dry], axis=1)

    _fake_take(monkeypatch, make)

    class T:
        def close(self):
            pass

    monkeypatch.setattr(
        cli, "_open_controller", lambda: (T(), ThrController(FakeAmp(real_payload()), settle=0))
    )
    rc = cli.main(
        ["audio", "record", "--seconds", "1", "--name", "riff", "--take-dir", str(tmp_path)]
    )
    out = capsys.readouterr().out
    assert rc == 0 and "channels 1+2" in out and "channels 3+4" in out
    assert "weakly related" in out or "looks like the input" in out
    names = sorted(p.name for p in tmp_path.iterdir())
    assert any(n.endswith("-riff-raw.wav") for n in names)
    assert any(n.endswith("-ch1-2.wav") for n in names) and any(
        n.endswith("-ch3-4.wav") for n in names
    )
    side = json.loads(
        next(p for p in tmp_path.iterdir() if p.name.endswith("amp-settings.json")).read_text()
    )
    assert side["settings"]["amp"] == 2 and side["seconds"] == 1
    pair = next(p for p in tmp_path.iterdir() if p.name.endswith("-ch1-2.wav"))
    data, rate = audio.read_wav(pair)
    assert rate == FS and data.shape == (FS, 2)


def test_cli_record_skips_silent_pairs_warns_on_clipping_and_fails_on_silence(
    monkeypatch, tmp_path, capsys
):
    from thr_control import cli

    monkeypatch.setattr(cli, "_open_controller", lambda: None)
    _fake_take(
        monkeypatch,
        lambda t: np.stack([np.sin(2 * np.pi * 220 * t)] * 2 + [np.zeros_like(t)] * 2, axis=1),
    )
    assert cli.main(["audio", "record", "--seconds", "1", "--take-dir", str(tmp_path)]) == 0
    out = capsys.readouterr().out
    assert (
        "CLIPPING" in out
        and "silent" in out
        and "channels 1+2" in out
        and "channels 3+4" not in out
    )
    assert not any(p.name.endswith("-ch3-4.wav") for p in tmp_path.iterdir())
    _fake_take(monkeypatch, lambda t: np.zeros((len(t), 4)))
    assert cli.main(["audio", "record", "--seconds", "1", "--take-dir", str(tmp_path)]) == 1
    assert "silent" in capsys.readouterr().err
    assert cli.main(["audio", "record", "--seconds", "0", "--take-dir", str(tmp_path)]) == 1


def test_pair_relation_finds_lag_polarity_and_direction():
    from thr_control.services import audio

    rng = np.random.default_rng(5)
    dry = np.convolve(rng.normal(0, 0.1, 3 * FS), np.ones(8) / 8)[: 3 * FS]  # a guitar-ish signal
    wet = np.concatenate([np.zeros(57), np.tanh(4 * dry)])[
        : len(dry)
    ]  # later by 57 samples, distorted
    lag, corr = audio.pair_relation(wet, dry)
    assert lag == 57 and corr > 0.7  # first (wet) is later than second (dry)
    lag2, _ = audio.pair_relation(dry, wet)
    assert lag2 == -57
    lag3, corr3 = audio.pair_relation(-wet, dry)
    assert lag3 == 57 and corr3 < -0.7  # polarity inversion is reported, not hidden
    assert abs(audio.pair_relation(rng.normal(0, 1, FS), rng.normal(0, 1, FS))[1]) < 0.1
    assert audio.is_dual_mono(dry, dry.copy()) and not audio.is_dual_mono(dry, wet)


def test_cli_record_names_the_input_and_output_pairs(monkeypatch, tmp_path, capsys):
    from thr_control import cli

    rng = np.random.default_rng(6)
    base = np.convolve(rng.normal(0, 0.1, 4 * FS), np.ones(6) / 6)[: 4 * FS]

    def make(t):
        dry = base[: len(t)]
        wet = np.concatenate([np.zeros(57), np.tanh(3 * dry)])[: len(t)]
        wet_r = np.concatenate([np.zeros(60), np.tanh(3 * dry)])[
            : len(t)
        ]  # a stereo reverb-ish difference
        return np.stack([wet, wet_r, dry, dry], axis=1) * 0.5

    monkeypatch.setattr(cli, "_open_controller", lambda: None)
    _fake_take(monkeypatch, make)
    assert cli.main(["audio", "record", "--seconds", "4", "--take-dir", str(tmp_path)]) == 0
    out = capsys.readouterr().out
    assert "channels 1+2: left and right are different (stereo)" in out
    assert "channels 3+4: left and right are identical (mono)" in out
    import re

    match = re.search(r"pair 3\+4 arrives ([0-9.]+) ms before pair 1\+2", out)
    assert match and 1.0 <= float(match.group(1)) <= 1.6  # ~57 samples of simulated latency
    assert "3+4 looks like the input, 1+2 the processed output" in out
