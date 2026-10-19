# THR Control

An **unofficial** editor for first-generation Yamaha THR guitar amplifiers (THR5, THR5A, THR10 family; developed and tested on a
THR5A running THR5 V2 firmware). Control the amp from your computer over USB: amp model, gain, master, EQ, cabinet and every effect,
with a preset library, tempo-synced delay, a live frequency-response plot and a recorder that saves the dry and the processed
guitar at the same time. No Wine and no official editor needed.

*Yamaha and THR are trademarks of their owner. This project is independent and is not affiliated with or endorsed by Yamaha.*

**Safe by design:** the app only ever sends the amp's settings request and validated parameter changes. Firmware, erase and
bootloader commands (`DTA1ERASE`, `DTA1MAIN`, `DTA1ROMR`) are blocked in code and covered by tests.

## Install

You need Python 3.12 or newer. THR Control is **not on PyPI yet**; until the first public release, install it from a
checkout of the source (this works today and was verified in a clean environment):

```sh
git clone <repository-url> thr-control && cd thr-control
pipx install .                    # or: uv tool install .
thr-control doctor                # checks everything and tells you what to fix
thr-control install-desktop       # adds "THR Control" to your application menu (Linux)
thr-control-gui                   # or just start it from the menu
```

After the first release this becomes `pipx install thr-control`.

### Other ways to get it

Each of these is prepared in `packaging/`; see the status in the table.

| Package | Where | Status |
| --- | --- | --- |
| Arch / Manjaro (AUR) | `packaging/arch/PKGBUILD` | Builds with `makepkg` and the files land in the right places; all dependencies are in the official repositories. Not submitted: it needs the public repository URL first |
| macOS `.app` / `.dmg` | `packaging/macos/` (`build.sh`) | The PyInstaller configuration was validated on Linux (the bundle starts, finds its data and opens the MIDI ports), but a Mac build has **not been run**; ad-hoc signed, not notarized |
| Flatpak | `packaging/flatpak/` | Manifest drafted, **not built**; recording and the live plot would be unavailable in the sandbox |

Plug the amp in with its USB cable and switch it on. If something is missing, `thr-control doctor` explains it in plain
words (for example: "add yourself to the audio group" or "install the PipeWire tools").

| Platform | Status |
| --- | --- |
| **Linux** (tested on Manjaro) | Supported: MIDI control, presets, GUI, recording, live measurement. Needs the ALSA and JACK *client libraries* (python-rtmidi links both; JACK itself is not used: Arch `pipewire-jack`, Debian/Ubuntu `libjack-jackd2-0`); recording and live measurement also need the PipeWire tools (`pw-record`, `pw-play`, `pw-dump`) |
| **macOS** | MIDI control, presets and the GUI should work (CoreMIDI), and recording and live measurement use PortAudio, but **none of it has been tested on a Mac yet**: see `docs/macos-testing.md` |
| **Windows** | Not supported (the THR needs a Yamaha driver there) |

**Audio backends.** Recording and live measurement use PipeWire's command-line tools on Linux and PortAudio (`sounddevice`) on
macOS. Force one with `--audio-backend pipewire|portaudio` or `THR_AUDIO_BACKEND`. On Linux PortAudio is only a fallback: it
often cannot open a USB device that PipeWire already owns. On macOS the first recording asks for microphone permission; allow it,
otherwise the input is silent.

### From source (developers)

```sh
sudo pacman -S --needed alsa-lib alsa-utils uv    # Arch / Manjaro; use your distribution's equivalents
uv sync
uv run thr-control doctor
uv run pytest
```

## License

GNU Affero General Public License v3.0 or later (`AGPL-3.0-or-later`); see `LICENSE`. Protocol facts were learned from the
reference projects listed in `docs/protocol.md`; no code was copied from them.

Files are kept in the platform's standard folders: on Linux `~/.local/share/thr-control` (presets, measurements) and your Music
folder (recorded takes).

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

## Live response curve

While you play, the app can estimate the amp's frequency response in real time from its USB audio, with no cable or test
tone: it compares the dry input (channels 3+4) with the processed output (channels 1+2), as spectrum over spectrum,
averaged over a few seconds. In the GUI press **Measure live** under the EQ curve; the measured curve is drawn in blue over
the dimmed illustrative model, and it moves as you change bass / middle / treble, the amp model or the cabinet. In a
terminal: `uv run thr-control audio live --seconds 30`.

- Play continuously for a few seconds (chords and notes across the neck): the app first finds the amp's latency (about 1.2
  ms) from your playing, then needs about two seconds of averaging before it shows anything.
- Only bands where the two signals are clearly related (coherence 0.6 or more) and the guitar actually has energy are
  drawn; everything else is left blank rather than guessed. Heavy distortion (high gain) lowers coherence, especially in
  the highs, and reverb or delay tails are not part of a simple response, so use a clean or low-gain tone for the cleanest
  curve. The curve is a *shape* (0 dB at 1 kHz), not an absolute level.

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
