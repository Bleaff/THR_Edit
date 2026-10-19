import json
import threading
import time

import numpy as np
import pytest

from thr_control.services import audio, audio_pipewire, audio_portaudio

FS = 48000
THR_SOURCE = audio.Node(72, "alsa_input.thr", "THR5 Analog Surround 4.0", "source", 4)
THR_SINK = audio.Node(80, "alsa_output.thr", "THR5 Analog Stereo", "sink", 2)


# -- PipeWire ----------------------------------------------------------------------------------
class FakeProc:
    def __init__(self, payload: bytes, chunk: int = 4096):
        import io

        self.stdout = io.BytesIO(payload)
        self.terminated = False
        self.stdout.read1 = lambda n: self._read(n)  # type: ignore[method-assign]
        self._buf, self._chunk = io.BytesIO(payload), chunk

    def _read(self, n):
        return self._buf.read(min(n, self._chunk))  # awkward sizes: not a whole number of frames

    def terminate(self):
        self.terminated = True

    def wait(self, timeout=None):
        return 0

    def kill(self):
        self.terminated = True


def raw_frames(frames: np.ndarray) -> bytes:
    return (np.clip(frames, -1, 1) * 2147483647).astype("<i4").tobytes()


def test_pipewire_capture_command_and_byte_parsing_across_odd_chunk_sizes():
    frames = np.random.default_rng(0).uniform(-0.5, 0.5, (3000, 4))
    seen = {}

    def popen(cmd, **kw):
        seen["cmd"] = cmd
        return FakeProc(raw_frames(frames), chunk=4099)  # 4099 is not a multiple of 16 bytes

    cap = audio_pipewire.PipeWireCapture(THR_SOURCE, popen=popen)
    cmd = seen["cmd"]
    assert cmd[:3] == ["pw-record", "--target", "alsa_input.thr"] and cmd[-1] == "-"
    assert "--raw" in cmd and cmd[cmd.index("--channels") + 1] == "4" and "s32" in cmd
    blocks = []
    while (b := cap.read()) is not None:
        blocks.append(b)
    got = np.concatenate(blocks)
    assert (
        got.shape == frames.shape and np.max(np.abs(got - frames)) < 1e-6
    )  # no lost or shifted frames
    cap.close()


def test_pipewire_capture_reports_a_missing_tool():
    def popen(cmd, **kw):
        raise FileNotFoundError("pw-record")

    with pytest.raises(audio.AudioError, match="pw-record"):
        audio_pipewire.PipeWireCapture(THR_SOURCE, popen=popen)


def test_pipewire_nodes_carry_their_channel_counts():
    dump = json.dumps(
        [
            {
                "id": 72,
                "type": "PipeWire:Interface:Node",
                "info": {
                    "props": {
                        "media.class": "Audio/Source",
                        "node.name": "n",
                        "node.description": "THR5",
                        "audio.channels": 4,
                    }
                },
            }
        ]
    )
    (node,) = audio_pipewire.parse_nodes(dump)
    assert node.channels == 4 and node.kind == "source"


# -- PortAudio (with a stand-in for the sounddevice module) ----------------------------------------
class FakeStream:
    """Stands in for sd.InputStream / sd.OutputStream."""

    instances: list = []

    def __init__(self, **kw):
        self.kw = kw
        self.started = self.stopped = self.closed = False
        self.written = []
        FakeStream.instances.append(self)

    def start(self):
        self.started = True
        cb = self.kw.get("callback")
        if cb is not None:  # an input stream: deliver blocks from a "driver" thread
            self.thread = threading.Thread(target=self._drive, args=(cb,), daemon=True)
            self.thread.start()

    def _drive(self, cb):
        for i in range(10_000):
            if self.stopped:
                return
            block = np.full((480, self.kw["channels"]), 0.01 * (i % 5 + 1), dtype=np.float32)
            cb(block, 480, None, None)
            time.sleep(0.001)

    def stop(self):
        self.stopped = True

    def close(self):
        self.closed = True

    def __enter__(self):
        self.start()
        return self

    def __exit__(self, *exc):
        self.stop()
        self.close()

    def write(self, data):
        self.written.append(np.array(data))


class FakeSD:
    class PortAudioError(Exception):
        pass

    def __init__(self, devices):
        self._devices = devices
        FakeStream.instances = []
        self.InputStream = FakeStream
        self.OutputStream = FakeStream

    def query_devices(self):
        return self._devices


DEVICES = [
    {"name": "MacBook Pro Microphone", "max_input_channels": 1, "max_output_channels": 0},
    {"name": "THR5", "max_input_channels": 4, "max_output_channels": 2},  # duplex USB device
    {"name": "MacBook Pro Speakers", "max_input_channels": 0, "max_output_channels": 2},
]


def test_portaudio_lists_duplex_devices_once_per_direction():
    nodes = audio_portaudio.PortAudioBackend(FakeSD(DEVICES)).list_nodes()
    assert [(n.id, n.kind, n.channels) for n in nodes] == [
        (0, "source", 1),
        (1, "source", 4),
        (1, "sink", 2),
        (2, "sink", 2),
    ]
    sink, source = audio.find_thr(nodes)
    assert (sink.id, sink.kind, source.id, source.kind) == (
        1,
        "sink",
        1,
        "source",
    )  # same id, told apart by kind


def test_portaudio_play_and_record_uses_the_right_devices_and_returns_the_recording():
    backend = audio_portaudio.PortAudioBackend(FakeSD(DEVICES))
    sweep = np.sin(2 * np.pi * 440 * np.arange(FS // 2) / FS) * 0.1
    nodes = backend.list_nodes()
    sink, source = audio.find_thr(nodes)
    data = backend.play_and_record(sweep, sink, source, fs=FS, channels=4, lead=0.05, tail=0.05)
    inp = next(s for s in FakeStream.instances if "callback" in s.kw)
    out = next(s for s in FakeStream.instances if "callback" not in s.kw)
    assert inp.kw["device"] == 1 and inp.kw["channels"] == 4 and inp.kw["samplerate"] == FS
    assert out.kw["device"] == 1 and out.kw["channels"] == 2
    assert out.written[0].shape == (len(sweep), 2) and np.allclose(
        out.written[0][:, 0], sweep, atol=1e-6
    )
    assert data.ndim == 2 and data.shape[1] == 4 and data.shape[0] > 0 and np.all(data > 0)
    assert data.shape[0] <= int((len(sweep) / FS + 0.1) * FS)  # never more than was asked for
    assert inp.stopped and out.closed  # streams are always released


def test_portaudio_play_and_record_wraps_driver_errors():
    class Broken(FakeSD):
        def __init__(self):
            super().__init__(DEVICES)

            def boom(**kw):
                raise self.PortAudioError("Invalid number of channels")

            self.InputStream = boom

    with pytest.raises(audio.AudioError, match="Invalid number of channels"):
        audio_portaudio.PortAudioBackend(Broken()).play_and_record(
            np.zeros(100), THR_SINK, THR_SOURCE, lead=0.0, tail=0.0
        )


def test_portaudio_record_writes_a_32_bit_wav(tmp_path):
    backend = audio_portaudio.PortAudioBackend(FakeSD(DEVICES))
    path = tmp_path / "take.wav"
    backend.record(THR_SOURCE, 0.2, path, fs=FS, channels=4)
    data, rate = audio.read_wav(path)
    assert rate == FS and data.shape[1] == 4 and data.shape[0] >= 480
    assert np.all(data > 0.005)  # the driver's blocks arrived intact


def test_portaudio_capture_streams_blocks_and_close_releases_a_waiting_reader():
    cap = audio_portaudio.PortAudioBackend(FakeSD(DEVICES)).open_capture(THR_SOURCE, FS, 4)
    first = cap.read()
    assert first.shape == (480, 4) and first.dtype == np.float64
    results = []
    reader = threading.Thread(target=lambda: results.append(cap.read()))
    reader.start()
    time.sleep(0.05)
    cap.close()
    reader.join(2)
    assert not reader.is_alive()  # closing never leaves a read() hanging
    assert cap.read() is None


def test_portaudio_capture_drops_blocks_instead_of_blocking_the_audio_thread():
    sd = FakeSD(DEVICES)
    cap = audio_portaudio.PortAudioCapture(sd, 1, FS, 4)
    cap.close()
    for _ in range(600):  # more than the queue holds, with nobody reading
        cap._callback(np.zeros((480, 4), dtype=np.float32), 480, None, None)
    assert cap.dropped > 0


def test_missing_sounddevice_is_a_clear_error(monkeypatch):
    import builtins

    real_import = builtins.__import__

    def fake(name, *a, **k):
        if name == "sounddevice":
            raise ImportError("no module")
        return real_import(name, *a, **k)

    monkeypatch.setattr(builtins, "__import__", fake)
    with pytest.raises(audio.AudioError, match="pip install sounddevice"):
        audio_portaudio.PortAudioBackend()


# -- backend selection --------------------------------------------------------------------------
def have_all(_):
    return "/usr/bin/x"


def test_backend_choice_by_platform_and_override(monkeypatch):
    monkeypatch.delenv("THR_AUDIO_BACKEND", raising=False)
    assert audio.choose_backend(platform="linux", which=have_all).name == "pipewire"
    monkeypatch.setattr(audio_portaudio, "_import_sounddevice", lambda: FakeSD(DEVICES))
    # Linux without the PipeWire tools falls back to PortAudio; macOS always uses it
    assert audio.choose_backend(platform="linux", which=lambda n: None).name == "portaudio"
    assert audio.choose_backend(platform="darwin", which=have_all).name == "portaudio"
    assert audio.choose_backend("pipewire", platform="darwin").name == "pipewire"
    monkeypatch.setenv("THR_AUDIO_BACKEND", "portaudio")
    assert audio.choose_backend(platform="linux", which=have_all).name == "portaudio"
    monkeypatch.setenv("THR_AUDIO_BACKEND", "nonsense")
    with pytest.raises(audio.AudioError, match="unknown audio backend"):
        audio.choose_backend()


def test_facade_delegates_to_the_chosen_backend(monkeypatch, tmp_path):
    calls = []

    class Recording:
        name = "fake"

        def list_nodes(self):
            calls.append("list")
            return [THR_SINK, THR_SOURCE]

        def play_and_record(self, *a, **k):
            calls.append("play")
            return np.zeros((10, 4))

        def record(self, source, seconds, path, fs, channels):
            calls.append(("record", seconds, channels))

        def open_capture(self, source, fs, channels):
            calls.append(("capture", fs, channels))
            return "source"

    monkeypatch.setattr(audio, "_backend", Recording())
    assert audio.list_nodes() == [THR_SINK, THR_SOURCE]
    assert audio.play_and_record(np.zeros(3), THR_SINK, THR_SOURCE).shape == (10, 4)
    audio.record(THR_SOURCE, 2.0, tmp_path / "x.wav")
    assert audio.open_capture(THR_SOURCE) == "source"
    assert calls == ["list", "play", ("record", 2.0, 4), ("capture", FS, 4)]
    audio.use_backend("auto")  # resets to automatic choice


def test_cli_audio_backend_option_and_duplex_ids(monkeypatch, capsys):
    from thr_control import cli

    nodes = audio_portaudio.PortAudioBackend(FakeSD(DEVICES)).list_nodes()
    monkeypatch.setattr(audio, "list_nodes", lambda: nodes)
    monkeypatch.setattr(
        audio, "play_and_record", lambda *a, **k: (_ for _ in ()).throw(AssertionError("no"))
    )
    # the amp is device 1 for both directions: --sink 1 and --source 1 must both resolve (dry run)
    assert cli.main(["audio", "probe", "--sink", "1", "--source", "1"]) == 0
    assert "Dry run" in capsys.readouterr().out
    assert cli.main(["audio", "probe", "--sink", "0"]) == 1  # device 0 is an input only
    assert "no output device with id 0" in capsys.readouterr().err
    assert cli.main(["audio", "probe", "--source", "2"]) == 1  # device 2 is an output only
    monkeypatch.setattr(
        audio,
        "use_backend",
        lambda name: (_ for _ in ()).throw(audio.AudioError("unknown backend")),
    )
    assert cli.main(["audio", "devices", "--audio-backend", "portaudio"]) == 1
    assert "unknown backend" in capsys.readouterr().err
