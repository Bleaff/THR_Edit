"""Command-line entry point: ``thr-control probe``.

Phase 1 is strictly read-only: the probe lists ports and listens on an input
port. It never opens an output port and never transmits anything.
"""

from __future__ import annotations

import argparse
import sys
import time
from collections.abc import Sequence
from pathlib import Path
from typing import TextIO

from . import __version__
from .domain.presets import Preset
from .midi.discovery import DetectedDevice, detect_devices, list_input_ports, list_output_ports
from .midi.monitor import CapturedMessage, MidiMonitor, format_hex, format_message
from .midi.transport import RequestTransport
from .protocol import messages, thr_v2
from .protocol.parser import SettingsDump, describe, parse
from .services.capture import diff_payloads, format_changes, run_mapping
from .services.controller import DeviceError, ThrController, apply_preset
from .services.preset_manager import PresetError, PresetManager
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
    sub.add_parser("gui", help="launch the desktop application").set_defaults(func=cmd_gui)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    return int(args.func(args))


if __name__ == "__main__":
    sys.exit(main())
