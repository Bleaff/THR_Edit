# AGENTS.md

Guidance for AI coding agents working on **THR Control**, a Linux desktop editor for Yamaha THR amplifiers (initial target: THR5 V2 / cross-flashed THR5A) over USB-MIDI SysEx. The full spec is in `roadmap.md`; this file is the short operational version. If they conflict, `roadmap.md` wins.

## Safety rules (non-negotiable)

- NEVER send firmware update, erase or bootloader commands. The strings/commands `DTA1ERASE`, `DTA1MAIN` and `DTA1ROMR` must never be transmitted. Firmware flashing and recovery are out of scope.
- `protocol/safety.py` must block these (and any SysEx not on an allowlist) at the lowest send layer. Every device write goes through the safety-aware controller (`services/controller.py`); nothing else touches the transport for writing.
- Never send experimental or guessed SysEx to real hardware. Only send messages that are verified (from reference sources or captured traffic) and documented in `docs/protocol.md`.
- Hardware tests run only when the user explicitly asks. All default tests must pass with no amplifier attached.
- Start read-only: no write support until the diagnostic/probe tooling (Phase 1) and verified protocol reads (Phase 2) exist.

## Stack

- Python 3.12+, type hints everywhere
- PySide6 (Qt 6, Qt Widgets) for the GUI
- mido + python-rtmidi (ALSA) for MIDI
- Pydantic for config/preset models; presets stored as JSON
- pytest, Ruff (lint + format), mypy (optional)
- uv for environment and dependencies

## Commands

Assuming the layout in `roadmap.md` §5 (adjust once `pyproject.toml` exists):

```sh
uv sync                      # install deps
uv run pytest                # tests (no hardware needed)
uv run ruff check .          # lint
uv run ruff format .         # format
uv run mypy src              # type check (optional)
uv run thr-control probe     # Phase 1 read-only MIDI diagnostic
```

Target platform: Manjaro Linux (Arch-based), native, no Wine. Document system packages needed (e.g. ALSA/rtmidi build deps) in `README.md`.

## Architecture

Layered, modular, GUI-independent:

```
src/thr_control/
  domain/     models, presets (pure data, no I/O)
  midi/       transport, discovery, monitor (ALSA via mido/rtmidi)
  protocol/   messages, parser, safety, thr_v2 (serialization only, no I/O)
  devices/    base adapter + thr5 (per-model parameter maps)
  services/   controller (safety-aware writes), preset_manager
  gui/        main_window, amplifier_panel, effects_panel, preset_browser
  storage/    repository (JSON presets)
docs/protocol.md   verified protocol findings
presets/           starter presets
tests/             pytest + captured-traffic fixtures
```

Principles:

- Transport is separate from protocol serialization; protocol is independent of the GUI.
- Device adapters isolate model differences (THR5 now; THR10/10C/10X/5A later).
- Provide a fake transport/amplifier backend for tests.
- Never block the Qt UI thread on MIDI I/O (use worker threads/signals).
- Handle timeouts, errors and unexpected responses explicitly; no silent failures.
- Avoid feedback loops between GUI changes and incoming MIDI updates.
- Do not assume the hardware emits knob-change events; investigate before choosing push vs. polling.
- MIDI port numbers are dynamic: discover at runtime (device: USB `0499:1506`, ALSA name `THR5`, port `THR5 MIDI 1`).
- Log MIDI interactions, with an optional verbose mode.

## Working style

- Work incrementally, one roadmap phase at a time (1 Discovery/Diagnostics, 2 Protocol Research, 3 Parameter Control, 4 GUI, 5 Presets, 6 Improvements). Do not implement everything in one pass. The current phase is **Phase 1** unless told otherwise.
- Prioritize correctness, maintainability and real hardware compatibility over speculative features.
- Only expose controls confirmed supported by the firmware. Mark unsupported or unknown features explicitly in code and docs; do not invent parameter mappings.
- Inspect the reference repos instead of assuming they cover everything: `michaelforney/thr10`, `SysExTones/sysex_tones`, `MathisRosenhauer/THR_Footswitch`. Record what is verified vs. unverified in `docs/protocol.md`.
- State protocol assumptions in the code/docs and in your summary.
- Match existing code style; keep changes small and focused; no unrelated refactors.

## Testing expectations

Cover: message encode/decode, protocol parsing, discovery logic, parameter validation, preset serialization, fake-transport integration, error handling, and write-command safety (including a test that the forbidden bootloader commands cannot be sent through the controller). Keep captured MIDI fixtures with a description of how each was obtained.

## Definition of done (per change)

- `ruff check`, `ruff format --check` and `pytest` pass; mypy clean where enabled.
- New behavior has tests that need no hardware.
- Docs updated (`README.md` for install/verify steps on Manjaro, `docs/protocol.md` for protocol facts).
- Summary states what was verified, what was assumed, and what remains unsupported.

## Pitfalls learned on hardware

- Never open a MIDI input port with a Python callback (`mido.open_input(..., callback=...)`). Closing such a port while a
  message arrives deadlocked python-rtmidi about once in 14 runs (the native thread waits for the GIL that the closing
  thread holds); the amp sends a heartbeat twice a second, so it will happen. Poll the port instead
  (`RequestTransport.poll`, `MidiMonitor`). `tests/test_transport.py` guards this.
- The amp pauses its heartbeat while its tuner is on; heartbeat silence alone is not a disconnect.
- Some command ids mean different things per effect type (reverb id `41`); use `thr_v2.applies` / `filter_applicable`
  and never write a value for a type other than the active one.
- Hardware test scripts: print with `flush=True`, arm `faulthandler.dump_traceback_later`, and never use `pkill -f` with a
  pattern that appears in your own command line.

