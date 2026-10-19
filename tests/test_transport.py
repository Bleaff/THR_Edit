import mido

from thr_control.midi.transport import RequestTransport
from thr_control.protocol import messages as m
from thr_control.protocol.safety import UnsafeMessageError


class PolledIn:
    def __init__(self):
        self.pending = []
        self.closed = False

    def poll(self):
        return self.pending.pop(0) if self.pending else None

    def close(self):
        self.closed = True


class Out:
    def __init__(self):
        self.sent = []
        self.closed = False

    def send(self, msg):
        self.sent.append(msg.bytes())

    def close(self):
        self.closed = True


def make(monkeypatch):
    inp, out = PolledIn(), Out()
    calls = {}

    def open_input(name, **kwargs):
        calls["input_kwargs"] = kwargs
        return inp

    monkeypatch.setattr(mido, "open_input", open_input)
    monkeypatch.setattr(mido, "open_output", lambda name, **kw: out)
    t = RequestTransport("THR5 in", "THR5 out")
    t.open()
    return t, inp, out, calls


def test_input_is_polled_never_opened_with_a_callback(monkeypatch):
    # Regression: a rtmidi callback can deadlock port.close() when a message arrives mid-close.
    _, _, _, calls = make(monkeypatch)
    assert "callback" not in calls["input_kwargs"]


def test_poll_returns_sysex_skips_other_messages_and_times_out(monkeypatch):
    t, inp, _, _ = make(monkeypatch)
    inp.pending += [
        mido.Message("note_on", note=60, velocity=64),
        mido.Message.from_bytes(list(m.build_heartbeat(m.ThrModel.THR5))),
    ]
    assert t.poll(1.0) == m.build_heartbeat(m.ThrModel.THR5)
    assert t.poll(0.02) is None


def test_wait_for_filters_and_close_closes_both_ports(monkeypatch):
    t, inp, out, _ = make(monkeypatch)
    hb = m.build_heartbeat(m.ThrModel.THR5)
    dump = bytes.fromhex("F0 43 7D 00 F7")
    inp.pending += [mido.Message.from_bytes(list(x)) for x in (hb, hb, dump)]
    assert t.wait_for(lambda d: d == dump, 1.0) == dump
    t.close()
    assert inp.closed and out.closed
    assert t.poll(0.01) is None  # safe after close


def test_send_still_goes_through_the_allowlist(monkeypatch):
    t, _, out, _ = make(monkeypatch)
    t.send(m.build_settings_request())
    assert out.sent == [list(m.build_settings_request())]
    try:
        t.send(bytes.fromhex("F0 43 7D 50 44 54 41 31 52 4F 4D 52 02 F7"))
    except UnsafeMessageError:
        pass
    else:
        raise AssertionError("bootloader command must be refused")
    assert len(out.sent) == 1
