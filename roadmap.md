# THR Control — Yamaha THR Editor for Linux

## Project Overview

Build an open-source desktop application for controlling Yamaha THR guitar amplifiers on Linux using Python and USB-MIDI SysEx.

The application should provide a modern graphical interface for adjusting amplifier settings, controlling effects, managing presets, and synchronizing state with the physical amplifier.

The initial target is **Yamaha THR5 V2**, including THR5A devices that have been cross-flashed with THR5 V2 firmware.

The application must run natively on **Manjaro Linux (Arch-based)** without Wine or the official Yamaha THR Editor.

The long-term goal is to support other first-generation Yamaha THR amplifiers, including THR10, THR10C, THR10X and THR5A, through device-specific protocol adapters.

## 1. Technical Stack

- Python 3.12+
- PySide6 / Qt 6 for the desktop GUI
- Qt Widgets for the initial version; custom graphics where beneficial
- mido + python-rtmidi for MIDI communication
- ALSA MIDI support on Linux
- Pydantic for validated configuration and preset models
- JSON for preset storage
- pytest for automated tests
- uv for dependency and environment management
- Ruff for linting and formatting
- mypy for optional static type checking

Use type hints throughout the codebase.

Keep the architecture modular, testable and independent from any specific GUI framework wherever practical.

## 2. Device Context

The development amplifier is a Yamaha THR5A that has been successfully flashed with official THR5 V2 firmware.

The device is recognized by Linux through USB:

- USB Vendor ID: `0499` (Yamaha)
- Observed USB Product ID: `1506`
- ALSA device name: `THR5`
- MIDI interface: `THR5 MIDI 1`

MIDI port numbers are dynamic and must be discovered at runtime.

Communication takes place over USB-MIDI, primarily using Yamaha System Exclusive (SysEx) messages.

The normal control protocol must be distinguished from the firmware bootloader protocol.

### Important safety requirement

The application must NEVER send firmware update, erase or bootloader commands during normal operation.

Explicitly prohibit accidental transmission of the previously identified bootloader commands:

- `DTA1ERASE`
- `DTA1MAIN`
- `DTA1ROMR`

Firmware flashing and recovery are outside the scope of this project.

## 3. Core Features

### 3.1 Device Connection

Implement automatic amplifier detection through ALSA MIDI.

Requirements:

- Discover connected MIDI devices.
- Identify supported Yamaha THR devices.
- Display device connection status.
- Allow manual MIDI port selection.
- Handle USB disconnection and reconnection.
- Gracefully handle missing MIDI permissions or unavailable ports.
- Display device identity and firmware version when obtainable through verified protocol messages.

Start by implementing a read-only MIDI diagnostic tool before enabling writes.

### 3.2 Amplifier Modeling

Provide a graphical amplifier model selector.

For THR5 V2, target these models:

- CLEAN
- CRUNCH
- LEAD
- BRIT HI
- MODERN

Controls should include:

- Gain
- Master
- Bass
- Middle
- Treble
- Output Volume (where supported)

Important: Some controls may be available only through software and not as physical knobs on THR5.

Only expose settings that are confirmed to be supported by the active firmware.

Changing a supported parameter should update the actual amplifier with low latency.

### 3.3 Effects

Implement support for the effects available through the THR V2 editor protocol.

Potential effect categories:

- Chorus
- Flanger
- Phaser
- Tremolo
- Delay
- Spring Reverb
- Hall Reverb
- Compressor
- Noise Gate

Each effect should have a dedicated editor with appropriate controls.

For example:

Delay:
- Time
- Feedback
- Mix

Reverb:
- Type
- Decay
- Mix

Compressor:
- Threshold or Sustain
- Level

Do not assume that all parameters or effect combinations are supported. Discover and document the actual parameter mapping before enabling controls.

### 3.4 Real-Time Synchronization

The application should synchronize its state with the amplifier.

Expected behavior:

1. Connect to the amplifier.
2. Request its current settings using verified messages.
3. Parse the response.
4. Update the UI.
5. Allow the user to modify settings.
6. Send supported parameter changes back to the amplifier.
7. Read back the state, where supported, to confirm changes.

Investigate whether physical knob movements generate MIDI notifications or whether periodic polling is required.

Do not assume the hardware emits knob-change events.

Avoid feedback loops between the GUI and incoming MIDI updates.

### 3.5 Preset Manager

Users should be able to save and load their own presets.

Required features:

- Create a preset.
- Save current amplifier settings.
- Load a preset onto the amplifier.
- Rename a preset.
- Duplicate a preset.
- Delete a preset.
- Import/export presets as JSON.
- Search and filter presets.
- Categorize presets by musical style.
- Mark favorites.

Suggested genres:

- Blues
- Jazz
- Bossa Nova
- Indie
- Rock
- Ambient
- Clean

Include a few starter presets such as Warm Jazz, Texas Blues, Indie Clean, Golden Brown and Indie Rock.

Loading a preset should apply supported parameters to the amplifier. Preset storage must work even if the amplifier does not support persistent onboard preset slots.

### 3.6 User Interface

Build a polished, modern desktop interface inspired by physical guitar amplifiers.

The main window should contain:

**Top bar**
- Connected device
- Connection status
- Active preset
- Save button

**Amplifier panel**
- Amp model selector
- Gain
- Master
- Three-band EQ
- Output controls

**Effects panel**
- Effect activation
- Effect type
- Individual effect parameters
- Signal-chain visualization, where supported

**Preset sidebar**
- Preset library
- Categories
- Search
- Favorites

**Diagnostics view**
- MIDI ports
- Raw MIDI message monitor
- Connection history
- Protocol log
- Export diagnostic logs

Use responsive layouts, clear controls, dark-mode support, and realistic rotary knobs.

The interface should remain usable when no amplifier is connected.

## 4. MIDI Protocol Research

Before implementing full control, research the existing first-generation Yamaha THR protocol.

Useful reference projects:

- https://github.com/michaelforney/thr10
- https://github.com/SysExTones/sysex_tones
- https://github.com/MathisRosenhauer/THR_Footswitch

Inspect relevant source code and documentation rather than assuming these projects support every required feature.

Investigate:

- SysEx message framing
- Device identification
- Session initialization
- Parameter identifiers
- Parameter encoding
- Request/response sequences
- Preset serialization
- Checksums, if applicable
- MIDI message timing
- Firmware-specific behavior

Create a documented protocol implementation based on verified findings.

Never send experimental messages that could invoke firmware update or memory erase behavior.

## 5. Proposed Architecture

Use a layered architecture.

```text
thr-control/
├── pyproject.toml
├── README.md
├── src/
│   └── thr_control/
│       ├── main.py
│       ├── domain/
│       │   ├── models.py
│       │   └── presets.py
│       ├── midi/
│       │   ├── transport.py
│       │   ├── discovery.py
│       │   └── monitor.py
│       ├── protocol/
│       │   ├── messages.py
│       │   ├── parser.py
│       │   ├── safety.py
│       │   └── thr_v2.py
│       ├── devices/
│       │   ├── base.py
│       │   └── thr5.py
│       ├── services/
│       │   ├── controller.py
│       │   └── preset_manager.py
│       ├── gui/
│       │   ├── main_window.py
│       │   ├── amplifier_panel.py
│       │   ├── effects_panel.py
│       │   └── preset_browser.py
│       └── storage/
│           └── repository.py
├── presets/
├── docs/
│   └── protocol.md
└── tests/
```

Architectural principles:

- Separate MIDI transport from protocol serialization.
- Keep protocol logic independent from the graphical interface.
- Use device adapters to support different amplifier models.
- Create a fake amplifier backend for automated testing.
- Never block the Qt UI thread during MIDI communication.
- Centralize all device writes through a safety-aware controller.
- Handle timeouts, errors and unexpected responses explicitly.
- Log important MIDI interactions with an optional verbose mode.

## 6. Development Roadmap

### Phase 1 — Device Discovery and MIDI Diagnostics

Create a working CLI tool that:

1. Lists MIDI ports.
2. Detects the connected THR5.
3. Opens the MIDI interface.
4. Receives MIDI messages.
5. Displays timestamped SysEx data.
6. Logs messages to a file.
7. Closes the connection cleanly.

Deliverable: `thr-control probe`

Do not implement amplifier state changes yet.

### Phase 2 — Protocol Research

Determine how the amplifier reports its current settings.

Implement:

- Message parser
- Device identification
- Known message definitions
- Read-only parameter requests
- Captured-message tests
- Protocol documentation

Deliverable: CLI displaying verified amplifier parameters.

### Phase 3 — Parameter Control

Implement verified write operations for:

- Amplifier model
- Gain
- Master
- EQ
- Supported effects

Provide readback or other confirmation where possible.

Deliverable: command-line amplifier control.

### Phase 4 — Desktop GUI

Build the PySide6 interface.

Requirements:

- Connection management
- Real-time parameter controls
- Amplifier model selector
- Effect editors
- MIDI diagnostics

Deliverable: usable Linux desktop application.

### Phase 5 — Preset Management

Implement full preset storage, import/export, categories, favorites, and preset switching.

Deliverable: complete preset editor.

### Phase 6 — Improvements

Potential future features:

- Keyboard shortcuts for switching presets
- MIDI footswitch support
- External MIDI controller mapping
- A/B preset comparison
- Parameter automation
- Preset sharing
- Recording interface integration
- Packaging for Arch Linux / AUR
- AppImage or Flatpak distribution

## 7. Testing and Quality

Use pytest.

Required test categories:

- MIDI message encoding/decoding
- Protocol parsing
- Device discovery logic
- Parameter validation
- Preset serialization
- Fake transport integration
- Error handling
- Write-command safety checks

Hardware-independent tests must not require a physical amplifier.

Maintain fixtures of captured MIDI traffic with clear descriptions.

Use real hardware tests only when explicitly requested.

## 8. Acceptance Criteria

The MVP is complete when:

- The application runs on Manjaro Linux.
- The connected Yamaha THR5 is detected automatically.
- Device connection and disconnection work reliably.
- Current amplifier parameters can be read where supported.
- At least one verified amplifier parameter can be changed from the application.
- The actual amplifier responds correctly.
- A preset can be saved locally and loaded.
- The interface remains responsive during MIDI operations.
- Dangerous firmware commands cannot be transmitted through the normal controller.
- Automated tests pass without hardware.

## 9. Instructions for Codex

Implement this project incrementally.

Start by:

1. Inspecting the three reference repositories.
2. Identifying which protocol features are already documented and verified.
3. Creating the Python project structure.
4. Implementing MIDI device discovery.
5. Implementing a read-only SysEx monitor.
6. Writing initial automated tests.
7. Documenting unknown protocol behavior.

Do not implement all planned features in one pass.

Prioritize correctness, maintainability, and actual hardware compatibility over speculative functionality.

Explain protocol assumptions and mark unsupported features explicitly.

**Begin with Phase 1 and provide a runnable implementation, installation instructions and a clear verification procedure for Manjaro Linux.**

