# THR Control

Open-source Linux controller for Yamaha THR amplifiers over USB-MIDI (target: THR5 V2 / cross-flashed THR5A). See `roadmap.md` and `AGENTS.md`.

**Status: Phase 5 (preset management) plus tempo-synced delay, EQ curve and preset notes; delay (time, cuts), reverb (all types), noise gate, compressor, cabinet and modulation parameters are mapped.** `probe`, `decode`, `diff` are receive-only; `read`, `map`, `show` send only the settings request; `set` sends one validated parameter command and only with `--yes`. The transport allowlist permits nothing else, and firmware/bootloader commands (`DTA1ERASE`, `DTA1MAIN`, `DTA1ROMR`) are blocked by `protocol/safety.py`.

## Install (Manjaro / Arch)

```sh
sudo pacman -S --needed alsa-lib alsa-utils uv base-devel
uv sync
```

`python-rtmidi` builds against `alsa-lib` if no wheel is available for your Python version. Your user must be able to access `/dev/snd/seq` (normally the `audio` group is not required on Manjaro).

## Usage

```sh
uv run thr-control probe --list                  # list ports, detect THR
uv run thr-control probe                         # listen until Ctrl+C
uv run thr-control probe --duration 30 --log logs/probe.log
uv run thr-control probe --port "THR5 MIDI"      # choose port manually
```

## Phase 2 commands

```sh
uv run thr-control decode tests/fixtures/thr5_idle_heartbeat.txt   # offline parse
uv run thr-control read                                             # dry run: shows the request, sends nothing
uv run thr-control read --yes --save logs/dump.txt                  # sends ONE settings request, parses the reply
```

## Phase 3 commands

```sh
uv run thr-control params                 # list settable parameters and ranges
uv run thr-control show                   # read current values from the amp
uv run thr-control set master 40          # dry run: prints the SysEx, sends nothing
uv run thr-control set master 40 --yes    # sends it, then reads back to confirm
uv run thr-control set reverb on --yes
uv run thr-control set amp lead --yes     # names are assumed THR10 order; numbers 0-4 also work
```

Note: changing `amp` makes the amp re-apply its own cab setting.

## Desktop app (Phase 4)

```sh
uv run thr-control gui
```

Connection is automatic (with reconnect on unplug/replug) or pick a port in the top-bar combo box. Amp model, gain,
master, EQ and the modulation / delay / reverb / gate controls follow the amp live: turning a knob on the amp moves
the on-screen knob, and dragging an on-screen knob updates the amp (writes are coalesced to ~50/s and read back
~0.4 s after you stop). The Diagnostics tab lists MIDI ports, connection history, a raw SysEx monitor (heartbeats
hidden by default), the protocol log, and exports everything to a text file.

The Delay box has a **TIME** field in milliseconds. TAP/TIME on the amp (the delay must be on) updates it live, and
editing it sends the new time to the amp.

**Tempo-synced delay.** In the Delay box, enter a tempo and a note length (1/2, dotted 1/4, 1/4, dotted 1/8, 1/8,
1/8 triplet, 1/16) and press **Set**: the delay time is set to that note length (the amp accepts 0.1-999.9 ms; requests
outside that range are explained, never clamped). The line below shows your *current* delay time as a tempo for the chosen
note length, so tapping TAP/TIME on the amp doubles as a tap-tempo readout. CLI: `thr-control delay-sync 92 dotted-1/8
[--yes]`.

**EQ curve.** Under the knobs, a frequency-response plot follows bass / middle / treble live (also when you turn the
amp's own knobs). It is *illustrative*: the amp's real filter frequencies are not known, so the curve models a low shelf,
a mid peak and a high shelf and is not measured.

While the amp's tuner is on, the amp stops sending its heartbeat. The app keeps the connection, shows an amber
**♪ AMP BUSY** badge, pauses writes, and re-reads the amp when it comes back. The amp does not report the pitch over
MIDI, so tune using the amp's display.

### Presets

The left sidebar is the preset library: search, genre filter (Blues, Jazz, Bossa Nova, Indie, Rock, Ambient, Clean,
Uncategorized), favorites, and Load / Save amp as new / Rename / Duplicate / Delete / favorite / Import / Export
(also in the right-click menu, which has a Genre submenu). Double-click loads a preset onto the amp. The top bar shows
the active preset (`*` when the amp differs from it); **Save** writes the amp's current settings into the active
preset, or asks for a name if none is active.

- Presets are plain JSON files, one per preset, in `~/.local/share/thr-control/presets/` (`$XDG_DATA_HOME` respected),
  written atomically; corrupt files are skipped, never fatal. They live on the computer, so no onboard slots are needed.
- 20 starter presets covering every genre (Blues, Jazz, Bossa Nova, Indie, Rock, Ambient, Clean) are added on first run, each
  with a usage note. Presets added in later releases arrive once on upgrade; ones you delete stay deleted. They are
  starting points, and amp/effect type names are unverified on THR5.
- **Notes**: the box under the list edits the selected preset's notes (saved a moment after you stop typing, or when you
  select another preset). Notes are searchable and shown as the list item's tooltip.
- Export writes `{"format": "thr-control-preset", "version": 1, "presets": [...]}`. Import accepts that or a single
  preset object, validates every value, assigns fresh ids, and skips presets identical to ones already present.
- Only mapped parameters are stored (see `thr-control params`). Loading a preset writes the amp model first, then cab
  and effect types, then the rest. Values that only apply to another reverb type are never stored or written.
  Not mapped: the compressor type (stomp/rack) and the rack-type compressor parameters.

CLI: `thr-control presets list [--query blues] [--favorites]`, `presets apply "Warm Jazz" [--yes]`,
`presets save "Name"` (reads the amp), `presets export FILE`, `presets import FILE`, `--library DIR` to use another folder.

## Recording takes

The amp's USB capture is a normal 4-channel, 48 kHz audio input, so any recorder (Ardour, Audacity, Reaper, OBS) can use it.
`thr-control audio record` is a quick built-in recorder:

```sh
uv run thr-control audio record --seconds 30 --name riff     # play now; Ctrl+C stops early
```

It saves, in `~/Music/thr-control/` (or `--take-dir`): the untouched 4-channel recording (`-raw.wav`), each *active* channel
pair as its own 24-bit stereo WAV (`-ch1-2.wav`, `-ch3-4.wav`), and `-amp-settings.json` with every mapped amp setting at
that moment, so a take remembers its tone. It prints each channel's level (and warns about clipping or silence), whether each pair is mono or stereo, and
which pair arrives first. On a THR5A, **channels 1+2 are the processed sound** (amp, cabinet and effects, stereo) and
**channels 3+4 the dry guitar** (mono, about 1.2 ms earlier): you record the finished tone and a clean DI at the same time,
so the DI can be re-amped later in a DAW.

## Measuring the amp's real frequency response

The amp is also a USB sound card. `thr-control audio` plays an exponential sine sweep, records the amp, and computes a
smoothed frequency response (Farina deconvolution, 1/6-octave smoothing, normalised to 0 dB at 1 kHz).

```sh
uv run thr-control audio devices                   # PipeWire outputs/inputs, THR marked
uv run thr-control audio probe                     # dry run: shows the plan, plays nothing
uv run thr-control audio probe --yes               # quiet sweep to the amp's USB; reports which capture channels carry it
uv run thr-control audio measure --sink 35 --level -50 --yes   # sweep from the PC's output into the amp's guitar input
uv run thr-control audio show                      # print the latest saved measurement
```

**Important:** the amp's USB *playback* bypasses its amp model (a probe on a THR5A showed no capture channel contains
it), so to measure the amp you must feed the sweep into its **guitar input jack**, for example from the computer's
analog output with a 3.5 mm to 6.3 mm mono cable, choosing that output with `--sink`. Start very quiet (`--level -50`,
low system volume): the sweep is audible from the amp, and levels above -12 dBFS are refused. Results are saved as JSON in
`~/.local/share/thr-control/measurements/` together with the amp's settings at that moment. Needs `pw-play`/`pw-record`
(PipeWire).

## Verify on hardware (Phase 1)

1. Plug in the THR5, power it on. `aconnect -l` should show `client NN: 'THR5'`.
2. `uv run thr-control probe --list` shows `THR5` under "Detected THR devices".
3. `uv run thr-control probe --log logs/probe.log`, then turn knobs / switch the amp model on the amp. Any MIDI/SysEx the amp emits is printed with a timestamp and appended to the log. **No output** means the amp sends nothing unprompted (itself a useful Phase 2 finding).
4. Ctrl+C prints `Closed. N message(s) received.`; unplugging and re-running reports a clear "no input port" error.

## Development

```sh
uv run pytest
uv run ruff check . && uv run ruff format --check .
uv run mypy
```
