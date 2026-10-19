import threading
import time

from tests.fake_amp import FakeAmp, real_payload
from thr_control.services.session import DeviceSession, SessionEvents


class FakeBackend:
    def __init__(self, amp: FakeAmp | None) -> None:
        self.amp = amp
        self.connects = 0

    def connect(self):
        self.connects += 1
        if self.amp is None:
            raise ConnectionError("no THR amplifier found")
        return self.amp, "THR5 (fake)"


class Recorder:
    def __init__(self) -> None:
        self.status: list[tuple[str, str]] = []
        self.settings: list[dict[str, int]] = []
        self.params: list[tuple[str, int]] = []
        self.raw: list[tuple[str, bytes]] = []
        self.logs: list[str] = []
        self.got_settings = threading.Event()

    def events(self) -> SessionEvents:
        return SessionEvents(
            on_status=lambda s, d: self.status.append((s, d)),
            on_settings=self._settings,
            on_param=lambda n, v: self.params.append((n, v)),
            on_raw=lambda d, b: self.raw.append((d, b)),
            on_log=self.logs.append,
        )

    def _settings(self, s):
        self.settings.append(s)
        self.got_settings.set()


def wait_until(cond, timeout=3.0):
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        if cond():
            return True
        time.sleep(0.005)
    return False


def start(amp):
    rec = Recorder()
    sess = DeviceSession(FakeBackend(amp), rec.events())
    sess.start()
    return sess, rec


def test_connects_and_reads_initial_state():
    amp = FakeAmp(real_payload())
    amp.heartbeat_interval = 0.1
    sess, rec = start(amp)
    try:
        assert rec.got_settings.wait(3)
        assert rec.status[0] == ("connected", "THR5 (fake)")
        assert rec.settings[0]["master"] == 0x33
    finally:
        sess.stop()
    assert amp.closed


def test_writes_are_coalesced_and_verified():
    amp = FakeAmp(real_payload())
    amp.heartbeat_interval = 0.1
    sess, rec = start(amp)
    try:
        assert rec.got_settings.wait(3)
        for v in range(10, 60):  # a fast knob drag
            sess.set_parameter("master", v)
        assert wait_until(lambda: amp.sets and amp.sets[-1] == ("master", 59))
        assert len(amp.sets) < 50  # coalesced
        assert wait_until(lambda: rec.settings[-1]["master"] == 59 and len(rec.settings) >= 2)
        assert not rec.logs
    finally:
        sess.stop()


def test_mismatch_is_logged():
    amp = FakeAmp(real_payload())
    amp.heartbeat_interval = 0.1
    amp.ignore_sets = True
    sess, rec = start(amp)
    try:
        assert rec.got_settings.wait(3)
        sess.set_parameter("gain", 5)
        assert wait_until(lambda: any("gain" in line for line in rec.logs))
    finally:
        sess.stop()


def test_amp_events_reach_listener_without_echo_writes():
    amp = FakeAmp(real_payload())
    amp.heartbeat_interval = 0.1
    sess, rec = start(amp)
    try:
        assert rec.got_settings.wait(3)
        amp.inject_event("treble", 12)
        assert wait_until(lambda: ("treble", 12) in rec.params)
        time.sleep(0.1)
        assert amp.sets == []  # receiving an event must never cause a write
    finally:
        sess.stop()


def test_invalid_parameter_rejected_on_caller_thread():
    sess = DeviceSession(FakeBackend(None))
    for bad in (("master", 101), ("cab", 1)):
        try:
            sess.set_parameter(*bad)
        except (ValueError, KeyError):
            continue
        raise AssertionError(bad)


def test_no_device_reports_disconnected_and_keeps_retrying(monkeypatch):
    monkeypatch.setattr("thr_control.services.session.RECONNECT_DELAY", 0.02)
    backend = FakeBackend(None)
    rec = Recorder()
    sess = DeviceSession(backend, rec.events())
    sess.start()
    try:
        assert wait_until(lambda: backend.connects >= 3)
        assert rec.status == [("disconnected", "no THR amplifier found")]  # reported once
    finally:
        sess.stop()


def test_reconnect_request():
    amp = FakeAmp(real_payload())
    amp.heartbeat_interval = 0.05
    backend = FakeBackend(amp)
    sess = DeviceSession(backend, Recorder().events())
    sess.start()
    try:
        assert wait_until(lambda: backend.connects == 1)
        time.sleep(0.1)
        sess.request_reconnect()
        assert wait_until(lambda: backend.connects >= 2, timeout=4)
    finally:
        sess.stop()


def test_heartbeat_pause_with_port_present_is_busy_not_disconnect(monkeypatch):
    monkeypatch.setattr("thr_control.services.session.HEARTBEAT_TIMEOUT", 0.15)
    amp = FakeAmp(real_payload())
    amp.heartbeat_interval = 0.05
    busy = []
    rec = Recorder()
    events = rec.events()
    events.on_busy = busy.append
    backend = FakeBackend(amp)
    sess = DeviceSession(backend, events)
    sess.start()
    try:
        assert rec.got_settings.wait(3)
        amp.heartbeat_interval = None  # the tuner is on: heartbeats stop
        assert wait_until(lambda: busy == [True])
        sess.set_parameter("master", 33)  # held while the amp is busy
        time.sleep(0.3)
        assert amp.sets == [] and backend.connects == 1
        assert [s for s, _ in rec.status] == ["connected"]  # never dropped
        amp.heartbeat_interval = 0.05  # tuner off
        assert wait_until(lambda: busy == [True, False])
        assert wait_until(lambda: ("master", 33) in amp.sets)  # held write is delivered
        assert backend.connects == 1
    finally:
        sess.stop()


def test_heartbeat_pause_with_port_gone_disconnects(monkeypatch):
    monkeypatch.setattr("thr_control.services.session.HEARTBEAT_TIMEOUT", 0.15)
    monkeypatch.setattr("thr_control.services.session.RECONNECT_DELAY", 0.02)
    amp = FakeAmp(real_payload())
    amp.heartbeat_interval = 0.05
    rec = Recorder()
    sess = DeviceSession(FakeBackend(amp), rec.events())
    sess.start()
    try:
        assert rec.got_settings.wait(3)
        amp.heartbeat_interval = None
        amp.alive = False  # USB unplugged
        assert wait_until(lambda: ("disconnected", "amp disconnected") in rec.status)
    finally:
        sess.stop()
