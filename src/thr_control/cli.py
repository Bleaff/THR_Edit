"""Command-line entry point: ``thr-control probe``.

Phase 1 is strictly read-only: the probe lists ports and listens on an input
port. It never opens an output port and never transmits anything.
"""

from __future__ import annotations

import argparse
import json
import math
import sys
import time
from collections.abc import Sequence
from pathlib import Path
from typing import TextIO

import numpy as np
import platformdirs

from . import __version__, paths
from .domain import eq as eq_domain
from .domain import measure
from .domain.presets import Preset
from .domain.tempo import bpm_for, delay_value, parse_division
from .midi.discovery import DetectedDevice, detect_devices, list_input_ports, list_output_ports
from .midi.monitor import CapturedMessage, MidiMonitor, format_hex, format_message
from .midi.transport import RequestTransport
from .protocol import messages, thr_v2
from .protocol.parser import SettingsDump, describe, parse
from .services import audio, desktop, doctor
from .services.capture import diff_payloads, format_changes, run_mapping
from .services.controller import DeviceError, ThrController, apply_preset
from .services.preset_manager import PresetError, PresetManager
from .storage import measurements
from .storage.repository import PresetRepository


def _print_ports(
    out: TextIO, ins: list[str], outs: list[str], devices: list[DetectedDevice]
) -> None:
    print("MIDI input ports:", file=out)
    for i, name in enumerate(ins):
        print(f"  [{i}] {name}", file=out)
    if not ins:
        print("  (none)", file=out)
    print("MIDI output ports:", file=out)
    for i, name in enumerate(outs):
        print(f"  [{i}] {name}", file=out)
    if not outs:
        print("  (none)", file=out)
    print("Detected THR devices:", file=out)
    for d in devices:
        print(f"  {d.model}: in={d.input_port!r} out={d.output_port!r}", file=out)
    if not devices:
        print("  (none)", file=out)


def _select_input(
    args: argparse.Namespace, ins: list[str], devices: list[DetectedDevice]
) -> str | None:
    if args.port:
        matches = [p for p in ins if args.port.lower() in p.lower()]
        return matches[0] if matches else None
    for d in devices:
        if d.input_port:
            return d.input_port
    return None


def cmd_probe(args: argparse.Namespace, out: TextIO | None = None) -> int:
    out = out or sys.stdout
    try:
        ins, outs = list_input_ports(), list_output_ports()
    except Exception as exc:  # backend/ALSA failure
        print(f"error: cannot query MIDI ports: {exc}", file=sys.stderr)
        return 2
    devices = detect_devices(ins, outs)
    _print_ports(out, ins, outs, devices)
    if args.list:
        return 0

    port = _select_input(args, ins, devices)
    if port is None:
        wanted = f"matching {args.port!r}" if args.port else "THR"
        print(f"error: no input port {wanted} found", file=sys.stderr)
        return 1

    log: TextIO | None = None
    if args.log:
        path = Path(args.log)
        path.parent.mkdir(parents=True, exist_ok=True)
        log = path.open("a", encoding="utf-8")
    t0 = time.monotonic()
    count = 0

    def on_message(msg: CapturedMessage) -> None:
        nonlocal count
        count += 1
        line = format_message(msg, t0)
        if msg.kind == "sysex":
            line += f"  <- {describe(parse(msg.data))}"
        print(line, file=out, flush=True)
        if log:
            log.write(f"{time.strftime('%Y-%m-%dT%H:%M:%S')} {line}\n")
            log.flush()

    monitor = MidiMonitor(port, on_message)
    try:
        monitor.open()
    except Exception as exc:
        print(
            f"error: cannot open {port!r}: {exc} (check ALSA permissions / port in use)",
            file=sys.stderr,
        )
        if log:
            log.close()
        return 1

    print(f"Listening on {port!r} (read-only). Ctrl+C to stop.", file=out, flush=True)
    try:
        deadline = t0 + args.duration if args.duration else None
        while deadline is None or time.monotonic() < deadline:
            time.sleep(0.05)
    except KeyboardInterrupt:
        pass
    finally:
        monitor.close()
        if log:
            log.close()
    print(f"Closed. {count} message(s) received.", file=out)
    return 0


def cmd_decode(args: argparse.Namespace, out: TextIO | None = None) -> int:
    """Offline: parse hex SysEx from a file (lines starting with # are ignored)."""
    out = out or sys.stdout
    text = Path(args.file).read_text(encoding="utf-8")
    hex_text = " ".join(ln for ln in text.splitlines() if not ln.lstrip().startswith("#"))
    try:
        raw = bytes.fromhex(hex_text)
    except ValueError as exc:
        print(f"error: invalid hex in {args.file}: {exc}", file=sys.stderr)
        return 1
    for chunk in raw.split(b"\xf7"):
        if chunk:
            data = chunk + b"\xf7"
            print(f"{format_hex(data)}\n  -> {describe(parse(data))}", file=out)
    return 0


def cmd_read(args: argparse.Namespace, out: TextIO | None = None) -> int:
    """Request the current settings dump from the amp (first write to hardware)."""
    out = out or sys.stdout
    try:
        ins, outs = list_input_ports(), list_output_ports()
    except Exception as exc:
        print(f"error: cannot query MIDI ports: {exc}", file=sys.stderr)
        return 2
    devices = [d for d in detect_devices(ins, outs) if d.input_port and d.output_port]
    if args.port:
        devices = [d for d in devices if args.port.lower() in (d.input_port or "").lower()]
    if not devices:
        print("error: no THR device with both input and output ports found", file=sys.stderr)
        return 1
    dev = devices[0]
    assert dev.input_port and dev.output_port
    request = messages.build_settings_request()
    print(f"Device: {dev.model}\nRequest: {format_hex(request)}", file=out)
    if not args.yes:
        print("Dry run: nothing sent. Re-run with --yes to transmit this request.", file=out)
        return 0
    try:
        transport = RequestTransport(dev.input_port, dev.output_port)
        transport.open()
    except Exception as exc:
        print(f"error: cannot open ports: {exc}", file=sys.stderr)
        return 1
    try:
        transport.send(request)
        data = transport.wait_for(lambda d: isinstance(parse(d), SettingsDump), args.timeout)
    finally:
        transport.close()
    if data is None:
        print(f"No settings dump received within {args.timeout:g}s.", file=sys.stderr)
        return 1
    print(f"Received: {format_hex(data)}\n  -> {describe(parse(data))}", file=out)
    if args.save:
        Path(args.save).write_text(
            "# THR settings dump captured by `thr-control read`\n" + format_hex(data) + "\n",
            encoding="utf-8",
        )
        print(f"Saved to {args.save}", file=out)
    return 0


def _load_dump(path: str) -> SettingsDump:
    text = Path(path).read_text(encoding="utf-8")
    raw = bytes.fromhex(" ".join(ln for ln in text.splitlines() if not ln.startswith("#")))
    msg = parse(raw)
    if not isinstance(msg, SettingsDump):
        raise ValueError(f"{path}: not a settings dump ({describe(msg)})")
    return msg


def cmd_diff(args: argparse.Namespace, out: TextIO | None = None) -> int:
    """Offline: show which payload offsets differ between two saved dumps."""
    out = out or sys.stdout
    try:
        a, b = _load_dump(args.a), _load_dump(args.b)
    except (OSError, ValueError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    print(format_changes(diff_payloads(a.payload, b.payload)), file=out)
    return 0


def cmd_map(args: argparse.Namespace, out: TextIO | None = None) -> int:
    """Interactive: map each physical knob to the dump bytes it changes (read-only requests)."""
    out = out or sys.stdout
    try:
        ins, outs = list_input_ports(), list_output_ports()
    except Exception as exc:
        print(f"error: cannot query MIDI ports: {exc}", file=sys.stderr)
        return 2
    devices = [d for d in detect_devices(ins, outs) if d.input_port and d.output_port]
    if not devices:
        print("error: no THR device with both input and output ports found", file=sys.stderr)
        return 1
    dev = devices[0]
    assert dev.input_port and dev.output_port
    request = messages.build_settings_request()
    try:
        transport = RequestTransport(dev.input_port, dev.output_port)
        transport.open()
    except Exception as exc:
        print(f"error: cannot open ports: {exc}", file=sys.stderr)
        return 1

    def fetch() -> SettingsDump | None:
        transport.send(request)
        data = transport.wait_for(lambda d: isinstance(parse(d), SettingsDump), args.timeout)
        msg = parse(data) if data else None
        return msg if isinstance(msg, SettingsDump) else None

    try:
        results = run_mapping(fetch, input, out)
    except (KeyboardInterrupt, EOFError):
        print("\nAborted.", file=out)
        return 1
    finally:
        transport.close()
    if args.save:
        import json

        Path(args.save).write_text(
            json.dumps({k: {w: c for w, c in v.items()} for k, v in results.items()}, indent=1),
            encoding="utf-8",
        )
        print(f"Saved to {args.save}", file=out)
    return 0


def _open_controller() -> tuple[RequestTransport, ThrController] | None:
    try:
        ins, outs = list_input_ports(), list_output_ports()
    except Exception as exc:
        print(f"error: cannot query MIDI ports: {exc}", file=sys.stderr)
        return None
    devices = [d for d in detect_devices(ins, outs) if d.input_port and d.output_port]
    if not devices:
        print("error: no THR device with both input and output ports found", file=sys.stderr)
        return None
    dev = devices[0]
    assert dev.input_port and dev.output_port
    try:
        transport = RequestTransport(dev.input_port, dev.output_port)
        transport.open()
    except Exception as exc:
        print(f"error: cannot open ports: {exc}", file=sys.stderr)
        return None
    return transport, ThrController(transport)


def cmd_params(args: argparse.Namespace, out: TextIO | None = None) -> int:
    out = out or sys.stdout
    for p in thr_v2.PARAMETERS.values():
        rng = "0/1" if p.kind is thr_v2.Kind.SWITCH else f"0..{p.maximum}"
        print(f"{p.name:<16} {rng:<7} {p.note}", file=out)
    return 0


def cmd_show(args: argparse.Namespace, out: TextIO | None = None) -> int:
    out = out or sys.stdout
    opened = _open_controller()
    if opened is None:
        return 1
    transport, ctl = opened
    try:
        settings = ctl.read_settings()
    except DeviceError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    finally:
        transport.close()
    for name, value in settings.items():
        print(f"{name:<16} {value}", file=out)
    return 0


def _parse_value(name: str, text: str) -> int:
    if text.lower().endswith("ms") and name == "delay_time":
        return round(float(text[:-2]) * 10)
    if name == "amp" and text.lower() in thr_v2.AMP_NAMES:
        return thr_v2.AMP_NAMES.index(text.lower())
    if text.lower() in ("on", "off") and thr_v2.PARAMETERS[name].kind is thr_v2.Kind.SWITCH:
        return int(text.lower() == "on")
    return int(text)


def cmd_set(args: argparse.Namespace, out: TextIO | None = None) -> int:
    """Set one parameter (dry run unless --yes), then read it back."""
    out = out or sys.stdout
    if args.name not in thr_v2.PARAMETERS:
        print(f"error: unknown parameter {args.name!r}; see `thr-control params`", file=sys.stderr)
        return 1
    try:
        value = _parse_value(args.name, args.value)
        command = thr_v2.build_set_command(args.name, value)
    except ValueError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    print(f"Command: {format_hex(command)}", file=out)
    if not args.yes:
        print("Dry run: nothing sent. Re-run with --yes to transmit.", file=out)
        return 0
    opened = _open_controller()
    if opened is None:
        return 1
    transport, ctl = opened
    try:
        result = ctl.set_parameter(args.name, value)
    except DeviceError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    finally:
        transport.close()
    status = "confirmed by readback" if result.ok else f"MISMATCH (amp reports {result.confirmed})"
    print(f"{args.name} = {value}: {status}", file=out)
    return 0 if result.ok else 1


def _manager(args: argparse.Namespace) -> PresetManager:
    manager = PresetManager(PresetRepository(Path(args.library) if args.library else None))
    manager.seed_starters()
    return manager


def _find_preset(manager: PresetManager, key: str) -> Preset | None:
    matches = [p for p in manager.all() if p.id == key or p.name.casefold() == key.casefold()]
    return matches[0] if matches else None


def cmd_presets(args: argparse.Namespace, out: TextIO | None = None) -> int:
    out = out or sys.stdout
    if args.action != "list" and not args.target:
        print(f"error: `presets {args.action}` needs a target", file=sys.stderr)
        return 1
    manager = _manager(args)
    if args.action == "list":
        for p in manager.search(args.query or "", None, args.favorites):
            star = "*" if p.favorite else " "
            print(f"{star} {p.name:<24} {p.genre_label:<14} {p.id}", file=out)
        return 0
    if args.action == "export":
        ids = [p.id for p in manager.all()]
        n = manager.export_presets(ids, args.target)
        print(f"Exported {n} preset(s) to {args.target}", file=out)
        return 0
    if args.action == "import":
        result = manager.import_presets(args.target)
        print(f"Imported {len(result.added)}, skipped {result.skipped} duplicate(s)", file=out)
        for err in result.errors:
            print(f"error: {err}", file=sys.stderr)
        return 1 if result.errors and not result.added else 0
    if args.action == "save":
        opened = _open_controller()
        if opened is None:
            return 1
        transport, ctl = opened
        try:
            settings = ctl.read_settings()
        except DeviceError as exc:
            print(f"error: {exc}", file=sys.stderr)
            return 1
        finally:
            transport.close()
        try:
            created = manager.create(args.target, settings)
        except PresetError as exc:
            print(f"error: {exc}", file=sys.stderr)
            return 1
        print(f"Saved {created.name!r} ({created.id})", file=out)
        return 0
    # apply
    preset = _find_preset(manager, args.target)
    if preset is None:
        print(f"error: no preset {args.target!r}", file=sys.stderr)
        return 1
    print(f"Preset {preset.name!r}: {preset.settings}", file=out)
    if not args.yes:
        print("Dry run: nothing sent. Re-run with --yes to apply to the amp.", file=out)
        return 0
    opened = _open_controller()
    if opened is None:
        return 1
    transport, ctl = opened
    try:
        bad = apply_preset(ctl, preset)
    except DeviceError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    finally:
        transport.close()
    for r in bad:
        print(f"MISMATCH {r.name}: wanted {r.requested}, amp reports {r.confirmed}", file=out)
    print("Applied and confirmed by readback." if not bad else "Applied with mismatches.", file=out)
    return 1 if bad else 0


def cmd_delay_sync(args: argparse.Namespace, out: TextIO | None = None) -> int:
    """Set the delay time to a note length at a tempo (dry run unless --yes)."""
    out = out or sys.stdout
    try:
        division = parse_division(args.division)
        value = delay_value(args.bpm, division)
    except ValueError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    command = thr_v2.build_set_command("delay_time", value)
    print(f"{division} at {args.bpm:g} BPM = {value / 10:.1f} ms (delay_time {value})", file=out)
    print(f"Command: {format_hex(command)}", file=out)
    if not args.yes:
        print("Dry run: nothing sent. Re-run with --yes to transmit.", file=out)
        return 0
    opened = _open_controller()
    if opened is None:
        return 1
    transport, ctl = opened
    try:
        result = ctl.set_parameter("delay_time", value)
    except DeviceError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    finally:
        transport.close()
    if not result.ok:
        print(f"MISMATCH (amp reports {result.confirmed})", file=out)
        return 1
    note = "" if result.confirmed is None else f" ({bpm_for(result.confirmed, division):.1f} BPM)"
    print(f"Confirmed by readback{note}.", file=out)
    return 0


def cmd_audio(args: argparse.Namespace, out: TextIO | None = None) -> int:
    """USB-audio tools: list the amp's audio nodes, or probe the capture channels."""
    out = out or sys.stdout
    try:
        audio.use_backend(args.audio_backend)
        nodes = audio.list_nodes()
    except audio.AudioError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    sink, source = audio.find_thr(nodes)
    if args.action == "show":
        return _show_measurement(args, out)

    def pick(node_id: int | None, kind: str, current: audio.Node | None) -> audio.Node | None:
        if node_id is None:
            return current
        # a duplex device appears twice (as sink and as source), so match the kind too
        return next((n for n in nodes if n.id == node_id and n.kind == kind), None)

    if args.sink is not None and (sink := pick(args.sink, "sink", sink)) is None:
        print(f"error: no output device with id {args.sink}", file=sys.stderr)
        return 1
    if args.source is not None and (source := pick(args.source, "source", source)) is None:
        print(f"error: no input device with id {args.source}", file=sys.stderr)
        return 1
    if args.action == "record":
        return _record(args, source, out)
    if args.action == "live":
        return _live(args, source, out)
    if args.action == "devices":
        for n in nodes:
            mark = "  <- THR" if n in (sink, source) else ""
            print(f"[{n.id:>3}] {n.kind:<6} {n.description} ({n.name}){mark}", file=out)
        return 0
    if sink is None or source is None:
        print(
            "error: the THR's USB audio is not available (is the amp connected?)", file=sys.stderr
        )
        return 1
    try:
        sweep = measure.log_sweep(args.duration, dbfs=args.level)
    except ValueError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    print(
        f"Play a {args.duration:g} s sweep at {args.level:g} dBFS to: {sink.description}", file=out
    )
    print(f"Record {audio.RECORD_CHANNELS} channels from:      {source.description}", file=out)
    print("This is audible from the amp's speaker/headphones (keep it quiet).", file=out)
    if not args.yes:
        print("Dry run: nothing played. Re-run with --yes.", file=out)
        return 0
    try:
        recorded = audio.play_and_record(sweep, sink, source)
    except audio.AudioError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    print(
        f"Recorded {recorded.shape[0] / measure.SAMPLE_RATE:.1f} s, {recorded.shape[1]} channels.",
        file=out,
    )
    if args.action == "measure":
        return _finish_measurement(args, recorded, sweep, sink, source, out)
    for r in audio.analyse_channels(recorded, sweep):
        verdict = "CARRIES THE SWEEP" if r.carries_sweep else "no sweep (noise only / silence)"
        print(
            f"  channel {r.channel}: level {r.rms_dbfs:7.1f} dBFS | "
            f"match {r.detection_db:5.1f} dB | {verdict}",
            file=out,
        )
    return 0


def _record(args: argparse.Namespace, source: audio.Node | None, out: TextIO) -> int:
    """Record the amp's USB capture, report each channel, and save every pair as a 24-bit WAV."""
    if source is None:
        print(
            "error: the THR's USB audio is not available (is the amp connected?)", file=sys.stderr
        )
        return 1
    if not 0 < args.seconds <= 3600:
        print("error: --seconds must be between 0 and 3600", file=sys.stderr)
        return 1
    directory = Path(args.take_dir) if args.take_dir else paths.takes_dir()
    directory.mkdir(parents=True, exist_ok=True)
    base = directory / f"{time.strftime('%Y%m%d-%H%M%S')}-{audio.sanitize_name(args.name)}"
    raw_path = base.with_name(base.name + "-raw.wav")
    print(
        f"Recording {args.seconds:g} s from {source.description}. Play now (Ctrl+C stops early).",
        file=out,
    )
    try:
        audio.record(source, args.seconds, raw_path)
        data, rate = audio.read_wav(raw_path)
    except audio.AudioError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    print(
        f"Recorded {data.shape[0] / rate:.1f} s at {rate} Hz, {data.shape[1]} channels.", file=out
    )
    levels = audio.level_report(data)
    for lv in levels:
        note = (
            "CLIPPING: turn the amp's volume down"
            if lv.clipping
            else ("" if lv.active else "silent")
        )
        print(
            f"  channel {lv.channel}: rms {lv.rms_dbfs:7.1f} dBFS | "
            f"peak {lv.peak_dbfs:7.1f} dBFS  {note}",
            file=out,
        )
    if not any(lv.active for lv in levels):
        print(
            "All channels are silent: nothing was played, or the guitar is not reaching the amp.",
            file=sys.stderr,
        )
        return 1
    saved = []
    for first in range(0, data.shape[1] - 1, 2):
        pair = data[:, first : first + 2]
        if not any(lv.active for lv in levels[first : first + 2]):
            continue
        path = base.with_name(f"{base.name}-ch{first + 1}-{first + 2}.wav")
        audio.write_pcm24(path, pair, rate)
        centroid = audio.spectral_centroid(pair.mean(axis=1), rate)
        print(
            f"  channels {first + 1}+{first + 2}: brightness {centroid:6.0f} Hz -> {path.name}",
            file=out,
        )
        saved.append(path)
    if data.shape[1] >= 4:
        _describe_pairs(data, rate, out, levels)
    settings: dict[str, int] = {}
    opened = _open_controller()
    if opened is not None:
        transport, ctl = opened
        try:
            settings = ctl.read_settings()
        except DeviceError:
            pass
        finally:
            transport.close()
    sidecar = base.with_name(base.name + "-amp-settings.json")
    sidecar.write_text(
        json.dumps({"seconds": args.seconds, "settings": settings}, indent=1) + "\n",
        encoding="utf-8",
    )
    print(f"Amp settings saved to {sidecar.name}", file=out)
    return 0


def _live(args: argparse.Namespace, source: audio.Node | None, out: TextIO) -> int:
    """Print the live amp response once a second while you play (text version of the GUI curve)."""
    from .services.live import LiveStream

    if source is None:
        print(
            "error: the THR's USB audio is not available (is the amp connected?)", file=sys.stderr
        )
        return 1
    stream = LiveStream(source)
    stream.start()
    print(
        f"Listening to {source.description} for {args.seconds:g} s. Play your guitar "
        "(Ctrl+C stops). Gains are relative to 1 kHz; '--' means not trusted.",
        file=out,
    )
    header = " ".join(f"{f / 1000:>4g}k" if f >= 1000 else f"{f:>5g}" for f in FREQ_TABLE)
    print(f"  {'status':<19} dry/wet dBFS   lag  | {header} Hz", file=out)
    deadline = time.monotonic() + args.seconds
    try:
        while time.monotonic() < deadline:
            time.sleep(1.0)
            snap = stream.snapshot()
            if snap.status == "error":
                print(f"error: {snap.error}", file=sys.stderr)
                return 1
            cells = []
            if (res := snap.result) is not None:
                norm = res.normalised()
                for f in FREQ_TABLE:
                    k = min(range(len(res.freqs)), key=lambda i: abs(res.freqs[i] - f))
                    cells.append(f"{norm[k]:+5.1f}" if res.valid[k] else "   --")
            lag = f"{snap.lag_samples / 48:.1f}ms" if snap.lag_samples is not None else "  n/a"
            print(
                f"  {snap.status:<19} {snap.dry_dbfs:6.1f}/{snap.wet_dbfs:6.1f} {lag:>6} | "
                + " ".join(cells or ["   --"] * len(FREQ_TABLE)),
                file=out,
                flush=True,
            )
            if snap.status == "ended":
                break
    except KeyboardInterrupt:
        pass
    finally:
        stream.stop()
    return 0


def _describe_pairs(
    data: np.ndarray, rate: int, out: TextIO, levels: list[audio.ChannelLevel]
) -> None:
    """Say which channel pair looks like the amp's input and which like its output, and why.

    Silent pairs are not described, and no verdict is given unless both pairs carry signal.
    """
    a, b = data[:, 0:2], data[:, 2:4]
    active = {
        "1+2": levels[0].active or levels[1].active,
        "3+4": levels[2].active or levels[3].active,
    }
    for name, pair in (("1+2", a), ("3+4", b)):
        if not active[name]:
            continue
        kind = (
            "identical (mono)"
            if audio.is_dual_mono(pair[:, 0], pair[:, 1])
            else "different (stereo)"
        )
        print(f"  channels {name}: left and right are {kind}", file=out)
    if not all(active.values()):
        return
    lag, corr = audio.pair_relation(a.mean(axis=1), b.mean(axis=1), rate)
    if abs(corr) < 0.4:
        print(
            f"  the two pairs are only weakly related (correlation {corr:+.2f}); no verdict",
            file=out,
        )
        return
    first, second = ("3+4", "1+2") if lag > 0 else ("1+2", "3+4")
    print(
        f"  pair {first} arrives {abs(lag) / rate * 1000:.2f} ms before pair {second} "
        f"(correlation {abs(corr):.2f}): {first} looks like the input, "
        f"{second} the processed output",
        file=out,
    )


FREQ_TABLE = (50, 100, 200, 500, 1000, 2000, 5000, 10000)


def _print_channels(m: measurements.Measurement, out: TextIO) -> None:
    print(
        "  channel | "
        + " ".join(f"{f / 1000:>4g}k" if f >= 1000 else f"{f:>5g}" for f in FREQ_TABLE)
        + " Hz",
        file=out,
    )
    for c in m.channels:
        row = " ".join(
            f"{float(np.interp(math.log(f), np.log(c.freqs), c.db)):+5.1f}" for f in FREQ_TABLE
        )
        print(f"  {c.channel:>7} | {row}  (latency {c.latency_ms:.1f} ms)", file=out)


def _finish_measurement(
    args: argparse.Namespace,
    recorded: np.ndarray,
    sweep: np.ndarray,
    sink: audio.Node,
    source: audio.Node,
    out: TextIO,
) -> int:
    reports = audio.analyse_channels(recorded, sweep)
    carrying = [r for r in reports if r.carries_sweep]
    if not carrying:
        print("No channel contains the sweep, so there is nothing to measure.", file=sys.stderr)
        print(
            "The amp's USB playback bypasses its amp model. Feed the sweep into the amp's guitar "
            "input instead, e.g. from the computer's audio output with a cable, using --sink for "
            "that output (see `thr-control audio devices`) and a low --level.",
            file=sys.stderr,
        )
        return 1
    settings: dict[str, int] = {}
    opened = _open_controller()
    if opened is not None:
        transport, ctl = opened
        try:
            settings = ctl.read_settings()
        except DeviceError:
            pass
        finally:
            transport.close()
    freqs = eq_domain.log_frequencies(120)
    result = measurements.Measurement(
        time.strftime("%Y-%m-%dT%H:%M:%S"), settings, sink.name, source.name, args.level
    )
    for r in carrying:
        ir = measure.impulse_response(recorded[:, r.channel - 1], sweep)
        db = measure.normalise(freqs, measure.magnitude_response(ir, freqs))
        result.channels.append(
            measurements.ChannelResult(r.channel, freqs, db, ir.latency_ms, r.detection_db)
        )
    path = measurements.save(result, Path(args.dir) if args.dir else None)
    print(f"Channels with the sweep: {[r.channel for r in carrying]}", file=out)
    _print_channels(result, out)
    print(f"Saved {path}", file=out)
    return 0


def _show_measurement(args: argparse.Namespace, out: TextIO) -> int:
    directory = Path(args.dir) if args.dir else None
    paths = [Path(args.file)] if args.file else measurements.list_saved(directory)[-1:]
    if not paths:
        print("No saved measurements.", file=out)
        return 0
    try:
        m = measurements.load(paths[0])
    except (OSError, ValueError, KeyError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    print(f"{paths[0].name}  amp settings: {m.settings or 'unknown'}", file=out)
    _print_channels(m, out)
    return 0


def cmd_doctor(args: argparse.Namespace, out: TextIO | None = None) -> int:
    """Check the environment and explain, in plain words, what to fix."""
    out = out or sys.stdout
    marks = {doctor.OK: "OK  ", doctor.WARN: "WARN", doctor.FAIL: "FAIL"}
    checks = doctor.run_checks()
    for c in checks:
        print(f"[{marks[c.status]}] {c.name}: {c.detail}", file=out)
        if c.hint and c.status != doctor.OK:
            print(f"       -> {c.hint}", file=out)
    failures, warnings = doctor.summarise(checks)
    print(
        "\nEverything needed is in place."
        if not failures and not warnings
        else f"\n{failures} problem(s), {warnings} warning(s).",
        file=out,
    )
    return 1 if failures else 0


def cmd_install_desktop(args: argparse.Namespace, out: TextIO | None = None) -> int:
    """Add (or remove) THR Control in the application menu of the current user (Linux)."""
    out = out or sys.stdout
    if not sys.platform.startswith("linux"):
        print(
            "error: this command creates a Linux menu entry; on macOS use the .app bundle.",
            file=sys.stderr,
        )
        return 1
    data_home = Path(platformdirs.user_data_dir())  # ~/.local/share (honours $XDG_DATA_HOME)
    if args.remove:
        removed = desktop.remove(data_home)
        print(
            "Removed: " + (", ".join(str(p) for p in removed) or "nothing was installed"), file=out
        )
        desktop.refresh_caches(data_home)
        return 0
    try:
        created = desktop.install(data_home, desktop.launcher_command())
    except desktop.DesktopError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    desktop.refresh_caches(data_home)
    for path in created:
        print(f"Wrote {path}", file=out)
    print("THR Control now appears in your application menu.", file=out)
    return 0


def cmd_gui(args: argparse.Namespace, out: TextIO | None = None) -> int:
    from .gui.app import run

    return run([sys.argv[0]])


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="thr-control", description="Yamaha THR controller")
    parser.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    sub = parser.add_subparsers(dest="command", required=True)
    probe = sub.add_parser("probe", help="read-only MIDI diagnostic: list ports and monitor input")
    probe.add_argument("--list", action="store_true", help="list ports and exit")
    probe.add_argument("--port", help="input port name substring (default: auto-detect THR)")
    probe.add_argument(
        "--duration", type=float, default=0, help="stop after N seconds (default: until Ctrl+C)"
    )
    probe.add_argument("--log", metavar="FILE", help="append received messages to FILE")
    probe.set_defaults(func=cmd_probe)
    decode = sub.add_parser("decode", help="offline: parse hex SysEx from a file")
    decode.add_argument("file")
    decode.set_defaults(func=cmd_decode)
    read = sub.add_parser("read", help="request the current settings dump (dry run unless --yes)")
    read.add_argument("--port", help="input port name substring")
    read.add_argument("--yes", action="store_true", help="actually transmit the request")
    read.add_argument("--timeout", type=float, default=3.0, help="seconds to wait for the reply")
    read.add_argument("--save", metavar="FILE", help="save the received dump (hex) to FILE")
    read.set_defaults(func=cmd_read)
    diff = sub.add_parser("diff", help="offline: diff the payloads of two saved dumps")
    diff.add_argument("a")
    diff.add_argument("b")
    diff.set_defaults(func=cmd_diff)
    mapc = sub.add_parser(
        "map", help="interactive: map knobs to dump bytes (sends read-only settings requests)"
    )
    mapc.add_argument("--timeout", type=float, default=3.0)
    mapc.add_argument("--save", metavar="FILE", help="save the result as JSON")
    mapc.set_defaults(func=cmd_map)
    sub.add_parser("params", help="list settable parameters").set_defaults(func=cmd_params)
    sub.add_parser("show", help="read and show current parameter values").set_defaults(
        func=cmd_show
    )
    setc = sub.add_parser("set", help="set one parameter (dry run unless --yes), with readback")
    setc.add_argument("name")
    setc.add_argument(
        "value",
        help="number, on/off for switches, an amp name for `amp`, or e.g. 400ms for delay_time",
    )
    setc.add_argument("--yes", action="store_true", help="actually transmit")
    setc.set_defaults(func=cmd_set)
    presets = sub.add_parser("presets", help="manage the local preset library")
    presets.add_argument("action", choices=["list", "apply", "save", "export", "import"])
    presets.add_argument("target", nargs="?", help="preset name/id, new name, or file path")
    presets.add_argument("--library", help="preset directory (default: ~/.local/share/thr-control)")
    presets.add_argument("--query", help="list: search text")
    presets.add_argument("--favorites", action="store_true", help="list: favorites only")
    presets.add_argument("--yes", action="store_true", help="apply: actually transmit")
    presets.set_defaults(func=cmd_presets)
    sync = sub.add_parser(
        "delay-sync", help="set the delay time from a tempo (dry run unless --yes)"
    )
    sync.add_argument("bpm", type=float)
    sync.add_argument("division", nargs="?", default="1/4", help="e.g. 1/4, dotted-1/8, 1/8T, 1/16")
    sync.add_argument("--yes", action="store_true", help="actually transmit")
    sync.set_defaults(func=cmd_delay_sync)
    aud = sub.add_parser("audio", help="USB-audio tools for measuring the amp")
    aud.add_argument("action", choices=["devices", "probe", "measure", "show", "record", "live"])
    aud.add_argument("--seconds", type=float, default=10.0, help="record: take length")
    aud.add_argument("--name", default="take", help="record: file name prefix")
    aud.add_argument("--take-dir", help="record: where to save (default: ~/Music/thr-control)")
    aud.add_argument("file", nargs="?", help="show: measurement file")
    aud.add_argument(
        "--audio-backend",
        choices=["auto", "pipewire", "portaudio"],
        default="auto",
        help="auto: PipeWire tools on Linux, PortAudio elsewhere",
    )
    aud.add_argument("--sink", type=int, help="PipeWire id of the output to play on (default: THR)")
    aud.add_argument("--source", type=int, help="PipeWire id of the input to record (default: THR)")
    aud.add_argument("--dir", help="measurement directory (default: ~/.local/share/thr-control)")
    aud.add_argument("--level", type=float, default=-40.0, help="sweep level in dBFS (max -12)")
    aud.add_argument("--duration", type=float, default=3.0, help="sweep length in seconds")
    aud.add_argument("--yes", action="store_true", help="probe: actually play the sweep")
    aud.set_defaults(func=cmd_audio)
    sub.add_parser("doctor", help="check the environment and explain what to fix").set_defaults(
        func=cmd_doctor
    )
    inst = sub.add_parser("install-desktop", help="add THR Control to the application menu (Linux)")
    inst.add_argument("--remove", action="store_true", help="remove it again")
    inst.set_defaults(func=cmd_install_desktop)
    sub.add_parser("gui", help="launch the desktop application").set_defaults(func=cmd_gui)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    return int(args.func(args))


if __name__ == "__main__":
    sys.exit(main())
