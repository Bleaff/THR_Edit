import mido

from thr_control import cli
from thr_control.midi.monitor import CapturedMessage, MidiMonitor, format_message


class FakeInput:
    def __init__(self, name, callback):
        self.name = name
        self.callback = callback
        self.closed = False

    def close(self):
        self.closed = True


def test_monitor_captures_sysex_and_closes(monkeypatch):
    holder = {}

    def fake_open_input(name, callback=None):
        holder["port"] = FakeInput(name, callback)
        return holder["port"]

    monkeypatch.setattr(mido, "open_input", fake_open_input)
    got: list[CapturedMessage] = []
    mon = MidiMonitor("THR5 MIDI 1", got.append)
    mon.open()
    holder["port"].callback(mido.Message("sysex", data=[0x43, 0x7D, 0x10]))
    holder["port"].callback(mido.Message("note_on", note=60, velocity=64))
    mon.close()
    assert holder["port"].closed and not mon.is_open
    assert got[0].kind == "sysex"
    assert got[0].data == bytes([0xF0, 0x43, 0x7D, 0x10, 0xF7])
    assert got[1].kind == "note_on"


def test_format_message():
    line = format_message(CapturedMessage(1.5, "sysex", b"\xf0\x43\xf7"), 1.0)
    assert "F0 43 F7" in line and "SYSEX" in line and "0.500" in line


def test_probe_list(monkeypatch, capsys):
    monkeypatch.setattr(cli, "list_input_ports", lambda: ["THR5:THR5 MIDI 1 24:0"])
    monkeypatch.setattr(cli, "list_output_ports", lambda: ["THR5:THR5 MIDI 1 24:0"])
    assert cli.main(["probe", "--list"]) == 0
    assert "THR5" in capsys.readouterr().out


def test_probe_no_device(monkeypatch, capsys):
    monkeypatch.setattr(cli, "list_input_ports", lambda: [])
    monkeypatch.setattr(cli, "list_output_ports", lambda: [])
    assert cli.main(["probe", "--duration", "0.1"]) == 1
    assert "no input port" in capsys.readouterr().err


def test_probe_logs_and_never_opens_output(monkeypatch, tmp_path, capsys):
    port_name = "THR5:THR5 MIDI 1 24:0"
    monkeypatch.setattr(cli, "list_input_ports", lambda: [port_name])
    monkeypatch.setattr(cli, "list_output_ports", lambda: [port_name])
    holder = {}

    def fake_open_input(name, callback=None):
        holder["port"] = FakeInput(name, callback)
        holder["port"].callback(mido.Message("sysex", data=[1, 2, 3]))
        return holder["port"]

    def forbidden(*a, **k):
        raise AssertionError("probe must not open an output port")

    monkeypatch.setattr(mido, "open_input", fake_open_input)
    monkeypatch.setattr(mido, "open_output", forbidden)
    log = tmp_path / "sub" / "probe.log"
    assert cli.main(["probe", "--duration", "0.1", "--log", str(log)]) == 0
    assert holder["port"].closed
    assert "F0 01 02 03 F7" in log.read_text()


def _fake_ports(monkeypatch):
    name = "THR5:THR5 MIDI 1 24:0"
    monkeypatch.setattr(cli, "list_input_ports", lambda: [name])
    monkeypatch.setattr(cli, "list_output_ports", lambda: [name])
    return name


def test_read_dry_run_sends_nothing(monkeypatch, capsys):
    _fake_ports(monkeypatch)

    def forbidden(*a, **k):
        raise AssertionError("dry run must not open ports")

    monkeypatch.setattr(mido, "open_output", forbidden)
    monkeypatch.setattr(mido, "open_input", forbidden)
    assert cli.main(["read"]) == 0
    out = capsys.readouterr().out
    assert "F0 43 7D 20 44 54 41 31 41 6C 6C 50 F7" in out and "Dry run" in out


def test_read_with_yes_sends_request_and_parses_reply(monkeypatch, capsys, tmp_path):
    from tests.test_protocol import synthetic_dump

    _fake_ports(monkeypatch)
    sent = []

    class FakeOut:
        def send(self, msg):
            sent.append(msg.bytes())

        def close(self):
            pass

    def fake_open_input(name, callback=None):
        port = FakeInput(name, callback)
        # amp replies with a dump as soon as it is asked: emulate by pre-queuing
        callback(mido.Message.from_bytes(list(synthetic_dump())))
        return port

    monkeypatch.setattr(mido, "open_input", fake_open_input)
    monkeypatch.setattr(mido, "open_output", lambda name: FakeOut())
    save = tmp_path / "d.txt"
    assert cli.main(["read", "--yes", "--save", str(save)]) == 0
    assert sent == [list(bytes.fromhex("F0 43 7D 20 44 54 41 31 41 6C 6C 50 F7"))]
    assert "settings dump" in capsys.readouterr().out
    assert cli.main(["decode", str(save)]) == 0
