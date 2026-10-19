from thr_control.midi.discovery import detect_devices, identify_model


def test_identify_model():
    assert identify_model("THR5 MIDI 1") == "THR5"
    assert identify_model("THR5:THR5 MIDI 1 24:0") == "THR5"
    assert identify_model("THR10C MIDI 1") == "THR10C"
    assert identify_model("thr10x midi 1") == "THR10X"
    assert identify_model("THR5A MIDI 1") == "THR5A"
    assert identify_model("Midi Through:Midi Through Port-0 14:0") is None


def test_detect_devices_pairs_ports():
    ins = ["Midi Through:Port-0 14:0", "THR5:THR5 MIDI 1 24:0"]
    outs = ["THR5:THR5 MIDI 1 24:0"]
    devs = detect_devices(ins, outs)
    assert len(devs) == 1
    assert devs[0].model == "THR5"
    assert devs[0].input_port == ins[1]
    assert devs[0].output_port == outs[0]


def test_detect_devices_none():
    assert detect_devices(["Other"], []) == []
