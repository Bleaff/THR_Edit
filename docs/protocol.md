# THR protocol notes

Only verified findings belong in "Verified". Everything else is unverified.

Firmware/bootloader research is documented separately in the
[experimental cross-flashing guide](firmware-thr5a-to-thr5-v2.md) and
[recovery guide](firmware-recovery.md). Those manual procedures are outside normal amplifier control.
THR Control must continue to reject firmware read, erase, write and bootloader SysEx commands at its existing send layer;
these documents do not add commands to its allowlist.

## Verified (observed on hardware, read-only)

- ALSA client `THR5`, port `THR5 MIDI 1` (USB 0499:1506), appears in both input and output lists.
- While idle and with no host traffic, the amp emits `F0 43 7D 60 44 54 41 30 F7` roughly every 0.5 s
  (fixture: `tests/fixtures/thr5_idle_heartbeat.txt`).
  - Decoded (matches the reference sources): `F0 43 7D` THR prefix, `60` = heartbeat, `44 54 41` = ASCII `DTA`,
    `30` = model byte **THR5** (the cross-flashed THR5A reports THR5, not 0x34), `F7`.
  - A heartbeat needs no reply according to the reference tools (they only listen for it). Not tested.

- **Settings request works on THR5** (2026-10-19): sending `F0 43 7D 20 44 54 41 31 41 6C 6C 50 F7` makes the amp reply
  within ~10 ms with a 276-byte dump (header, 256-byte payload, valid checksum; fixture `thr5_dump_baseline.txt`).
  - The byte after `DTA` is the constant `31` ("DTA1"), **not** the model byte: the `30` form got no reply.
  - Right after the dump the amp sent `F0 43 7D 30 41 30 02 02 F7` (system-type message, meaning unknown;
    fixture `thr5_post_request_system.txt`).
  - Heartbeats continue unchanged during and after the exchange; no session setup was needed.
- Baseline dump decoded with the THR10 offsets: amp=2, gain/master/bass/middle/treble = 52/51/59/50/62, cab=2,
  all in 0-100 range. Consistent with the THR10 layout but **not yet confirmed** against actual knob positions;
  the preset name field (payload 0-63) is empty.
- **The amp pushes knob changes** (verified): turning TONE produced 2001 messages in ~6 s, each of the form
  `F0 43 7D 10 41 30 01 <id> 00 <value> F7` (fixture `thr5_tone_knob_events.txt`). Ids 03/04/05 (the bass/mid/treble
  ids in the THR10 table) arrive as a triplet per knob step, values 50-100 / 21-73 / 37-75, at ~100 steps/s
  (so the GUI must throttle/coalesce). Heartbeats continue. No polling is needed for at least this knob; the other
  knobs are not yet logged.
- With no knobs touched, 8 s of listening showed only heartbeats.

- **Hardware note (photo `knob_pos.jpg`):** the case is a THR5A. Its printed controls are VOLUME, DLY/REV, EFFECT, TONE,
  MASTER, BLEND (mic/direct), MIC TYPE (selector with LEDs) -- not the THR5's gain/bass/mid/treble. What each knob does
  under the THR5 V2 firmware is unknown, so the THR10-offset interpretation of the dump is doubtful until mapped with
  `thr-control map`.

## Verified: knob -> dump offset map (THR5A case, THR5 V2 firmware)

From `thr-control map` (fixture `tests/fixtures/thr5a_knob_map.json`; each knob swept min then max, one at a time).
Offsets are payload indices (0-255). They match the THR10 layout in sysex_tones.

| Physical knob | Payload offset(s) | Observed | Interpretation |
| --- | --- | --- | --- |
| MASTER | 130 | 0 .. 100 | master, direct 1:1 |
| BLEND | 129 | 0 .. 100 | the THR10 "gain" slot, direct 1:1 |
| MIC TYPE | 128 | 0 .. 4 | amp model index (5 positions; THR10 order starts Clean, Crunch, Lead, BritHi, Modern: names unconfirmed) |
| MIC TYPE (side effect) | 131-133, 134, 223 | EQ values, cab 2->1->0, 223 127->0 | the firmware re-applies per-amp tone and cab when the model changes; 223 (THR10 gate on/off) flipped on |
| TONE | 131, 132, 133 | min (35,50,4), max (70,60,80) | one knob drives three EQ bytes (bass/mid/treble slots) through a per-amp curve, so it is not 1:1 |
| VOLUME | none | no change | analog, not in the dump (cannot be read or set over MIDI) |
| EFFECT | 160-165, 175 | type 0->2, params 161-165, 175 127->0 | modulation block: type 160, params 161-165, on/off 175 (0 = on, 127 = off) |
| DLY/REV | 179-184, 192-203, 207 | delay params, reverb type 192 2->0, 207 127->0 | delay block (time 177-178?, feedback 179, level 184) and reverb block (type 192, on/off 207) |

Caveats: values at sweep ends only; the EFFECT/DLY-REV knobs are probably multi-position selectors, so intermediate
positions are unmapped. The first entry of each pair compares against the previous step's state, not a fixed baseline.

## Verified: parameter writes (Phase 3)

Format (same as the amp's own knob events): `F0 43 7D 10 41 30 01 <id> 00 <value> F7`.
Tested on hardware 2026-10-19 by setting each value, reading it back with a settings request, and restoring:
amp, gain, master, bass, middle, treble, modulation/delay/reverb/gate on-off all confirmed; the amp applied
each write immediately and a readback ~50 ms later showed the new value. A full dump after the round trip was
byte-identical to the one before (including the cab byte, which the amp changes itself when the amp model changes).

- Switch values: `00` = on, `7F` = off (same encoding in the dump).
- Writable set = `protocol/thr_v2.py` table only; the transport's allowlist rejects any other id, out-of-range
  value, system command (`30`), dump, or bootloader message.
- Not writable yet: cab, amp-specific effect parameters (modulation speed/depth..., delay time, reverb time/filter),
  compressor. Multi-byte (14-bit) values were seen in events (`31`, `34`, `36`, `43`, `45`, `47`) but are unmapped.
- Amp names in index order (clean, crunch, lead, brit hi, modern) and effect type names are assumed from THR10.

## Verified: applying presets (Phase 5), and one side effect

Applying a preset (amp first, then the rest) was tested on hardware by both the CLI/controller path and the GUI's
coalesced session path; every mapped parameter read back correctly and a snapshot restored exactly.

**Side effect:** the byte-for-byte dump after the test differed from the one before at payload offsets 161-163
(modulation speed/depth/mix) and 194-202 (reverb sub-parameters). These are effect-specific values that are not in the
parameter table, so they cannot be written or restored. Writing effect type/on-off parameters appears to make the amp
reload its defaults for those blocks (the "after" values equal the defaults seen in the very first baseline dump).
Consequence: loading a preset that touches an effect can reset that effect's unmapped settings. The GUI says so in the
Load button tooltip. Fix: map the effect sub-parameters (161-165, 177-184, 193-203) and include them in presets.

## Verified: the amp pauses its heartbeat while its tuner is on

Probe-only capture (app closed) while using the tuner (summary in `tests/fixtures/thr5_tuner_heartbeat_gap.txt`):
heartbeats stopped for 12.5 s (t=18.0 to 30.5), and the amp then sent unsolicited settings dumps (t=30.1, 32.7, 37.7,
39.9). No other messages appeared. The app therefore must not treat heartbeat silence as a disconnect: it checks
that the amp's ALSA ports still exist (they vanish on unplug), shows an "AMP BUSY" badge, holds writes while busy and
re-reads the amp when the heartbeat resumes. The amp's tuner pitch is not reported over MIDI.

**Retracted:** an earlier version of these notes called `F0 43 7D 30 41 30 00 01 F7` / `... 00 00 F7` "tuner on/off".
That was an inference from one GUI session and is contradicted by the capture above (no such messages during a tuner
session). They were seen in the GUI session (fixture `thr5_system_messages_gui_session.txt`; the `00 00` arrived 1 ms
after a dump the app had requested), so they may be status replies tied to our requests. Meaning unknown. The
sysex_tones reference labels the same bytes "wide" off/on. Sending system messages remains blocked by the allowlist.
Another system message, `... 30 41 30 02 02 F7`, follows a settings request; meaning unknown.

## Verified: delay time and TAP/TIME

- TAP/TIME only changes anything while the delay is on (with it off nothing happens and no LED reacts).
- Each tap (from the second on) makes the amp send `F0 43 7D 10 41 30 01 31 <hh> <ll> F7`: parameter id `31`, a 14-bit
  value `(hh<<7)|ll`. The value is the measured tap interval in **units of 0.1 ms**: five consecutive events arrived
  ~0.30, 0.31, 0.36, 0.34 and 0.53 s apart and carried 3000, 2999, 3599, 3399 and 5299. The settings dump holds the same
  value at payload offsets 177-178 (the dump read after the taps matched the last event, 5299).
- Writing the same message back sets the delay time: tested on hardware with 4000, 1500, 9000 and a restore, each
  confirmed by readback with all other parameters unchanged. Range used: 1..9999 (the THR10 table's limits, 0.1 ms to
  999.9 ms); only 1500-9000 were exercised, the end points are untested.
- The `delay_time` parameter is therefore in the table (`thr-control set delay_time 400ms --yes`) and in the GUI.
- Turning the delay on and tapping also changed delay feedback and cut bytes (offsets 179-181) in one test, so the amp
  may reload parts of the delay block; not isolated.

## Verified: noise gate and compressor (software-only controls)

The THR5A panel has no gate or compressor knob, and none of these bytes ever moved during the knob map, but the dump
holds both blocks. Writing the THR10 command ids worked on hardware (each write changed exactly one dump byte; all
five were restored and the full 256-byte payload ended identical to the start):

| Parameter | Command id | Dump offset | Tested |
| --- | --- | --- | --- |
| gate_threshold | `51` | 209 | 50 -> 30 -> 50 |
| gate_release | `52` | 210 | 50 -> 70 -> 50 |
| compressor on/off | `1F` | 159 | off -> on -> off (`00` on, `7F` off) |
| compressor_sustain | `11` | 145 | 50 -> 70 -> 50 |
| compressor_output | `12` | 146 | 50 -> 40 -> 50 |

Caveats: sustain/output apply to the stomp-type compressor (type 0, which this amp was set to; offset 144). The type
parameter (`10`) and the rack-type parameters were not tested, and in rack mode ids `11`/`12` mean other parameters, so
do not write them if the type is not 0. Gate on/off is also switched by the amp itself for some amp models (it turned on
at the last MIC TYPE position, amp model 4).

## Verified: cabinet and modulation parameters

Tested on a THR5A with the same write / read-dump / restore method (restore left the dump byte-identical):

- **Cab** (id `06`, dump offset 134): values 0-5 were all accepted with no other byte changing. Value 6 ("none" on the
  THR10) was deliberately not tested, so the app limits cab to 0-5. Cab names are the THR10's index order and are
  UNVERIFIED on a THR5 (the amp picks its own cab when the amp model changes).
- **Modulation type** (id `20`, offset 160): 0-3 accepted. Each type loads its own default parameter block
  (type 0: 53,29,34,58,99; type 1: 14,22,37,58,99; type 3: 53,9,88,6,23; type 2 loaded 50,50 and left the rest).
  Type names (chorus, flanger, tremolo, phaser) and the per-type parameter labels are the THR10's and are UNVERIFIED
  on a THR5.
- **Modulation parameters p1-p5** (ids `21`-`25`, offsets 161-165): each write changed exactly its own byte for every
  type, including parameters a type does not appear to use (tremolo p3-p5). The GUI labels and shows only the knobs
  the assumed type uses.
- **Preset apply order:** because a type change resets that effect's parameters and an amp change resets the cab,
  presets are written amp first, then cab and effect types, then everything else. Applying a preset in one fast burst
  (no delays) through the GUI's session path stuck completely, and restoring a snapshot afterwards reproduced the
  original dump exactly. Chorus/phaser/etc. parameters are therefore no longer lost when loading presets.

## Verified: delay cuts and reverb parameters (type-dependent)

Tested on a THR5A with write / read-dump / restore (restore matched all 35 mapped settings exactly):

- **Delay high cut** (`34`, offsets 180-181) and **low cut** (`36`, 182-183): 14-bit values, accepted. The amp's own
  values were 4000 and 21, so the unit is assumed to be Hz (the THR10 range is 1000-16001 / 21-8000).
- **Reverb types 0-2 (hall/room/plate)**: time `41` (193-194), pre-delay `43` (195-196), low cut `45` (197-198),
  high cut `47` (199-200), all 14-bit; high ratio `49` (201) and low ratio `4A` (202), one byte. All accepted on all
  three types, each changing exactly its own bytes. Units of time/pre-delay are unverified. The original low ratio
  was 0, below the THR10 table's minimum of 1, so the minimum is 0.
- **Spring (type 3)**: id `41` is the same wire message `41 00 <v>` but means "spring reverb amount" and is stored in
  the single dump byte 193; id `42` is the spring filter (byte 194). The amp's dump layout changes per type, so the
  app only treats a value as meaningful for its own type (`applies_when`), uses the last known reverb type to decode
  the amp's own events, and never stores or writes values for another type (a hall preset can not carry spring values).
- **Switching the reverb type resets** that type's parameters and the reverb level to defaults; presets rewrite them
  after the type (apply order: amp, then cab/effect types, then the rest).
- A hardware test applied a spring-reverb preset with new delay cuts and a tremolo modulation type in one burst: all
  values stuck, and restoring the snapshot reproduced every setting.

## USB audio (not MIDI): what was found

- ALSA/PipeWire expose the THR5 as a stereo playback device (`THR5 Analog Stereo`) and a **4-channel** capture device
  (`THR5 Analog Surround 4.0`, positions FL FR RL RR).
- A quiet sweep played to the playback device (3 s, -40 dBFS) did **not** appear on any of the four capture channels
  (matched-filter score 13 dB on every channel, i.e. noise; channel levels about -110 and -117 dBFS, effectively digital
  silence with no guitar connected). So USB playback is not looped back and does not pass through the amp model.
- To measure the amp the sweep must enter the guitar jack. Which of the four capture channels carries the processed
  (wet) signal and which the dry one is still unknown until that measurement is done.

- First recording test (3 s, no sweep playing, nothing intentionally played; 2026-10-19): channels 1 and 2 were nearly silent
  (rms -82.3 dBFS, peak -70.8) and identical to each other, while channels 3 and 4 were louder (rms -56.3, peak -52.0, spectral
  centroid about 1.4 kHz) and also identical to each other. An earlier run with the same device showed all four channels at
  about -110 to -117 dBFS. So the pairs carry different things; what was audible on 3+4 then (noise, a cable, or playing) is unknown.
- **Channel assignment (verified by a 30 s take of playing, preset Indie Rock: amp 2, cab 2, gain 62, master 40, reverb and
  gate on):** channels 1+2 differ from each other (stereo; reverb is on), channels 3+4 are bit-identical (mono). Pair 3+4
  arrives **57 samples = 1.19 ms before** pair 1+2 (normalised cross-correlation +0.76 at that lag), and the crest factor is
  17.3 dB on 1+2 versus 23.0 dB on 3+4 (the processed signal is denser). Conclusion: **1+2 = processed output, 3+4 = dry
  input (DI)**. This is one take on one amp; `thr-control audio record` repeats the test on every take.

- Live streaming works: `pw-record --target <THR source> --channels 4 --format s32 --raw --latency 20ms -` delivers raw
  little-endian 32-bit frames of four channels that the app splits into dry (3+4) and wet (1+2). A real run showed the dry
  input at about -49 dBFS and the processed output at about -16 dBFS while playing (about 33 dB of gain through the amp).

- PortAudio (`sounddevice`) on this Linux machine lists the amp as `THR5: USB Audio (hw:2,0)` but opening its 4-channel
  input failed with `Invalid sample rate` while PipeWire owns the device, so Linux keeps PipeWire as the default backend.
  The PortAudio path exists for macOS and has not been run against a Mac yet.

## Implementation note: do not use rtmidi callbacks

Opening the amp's input port with a mido/rtmidi callback made `port.close()` hang intermittently (1 of 14 runs; stack:
`mido/backends/rtmidi.py` `_close` -> `close_port`). The amp's 2 Hz heartbeat guarantees a message sometimes arrives while
closing. After switching to polled reads (`RequestTransport.poll`, `MidiMonitor`), 60 consecutive `show` runs and 20
`probe` runs against the amp completed without a stall.

## Documented by reference sources, NOT yet verified on this THR5

Sources: `SysExTones/sysex_tones` (THR10; AGPL-3.0, so only facts are used, no code), `MathisRosenhauer/THR_Footswitch`
(THR10/THR5, preset write), `michaelforney/thr10` (firmware/bootloader only; not used for control).

| Item | Bytes / rule |
| --- | --- |
| Framing | `F0 43 7D <type> ... F7`; types: `00` dump, `10` parameter command, `20` request, `30` system, `50`/`70` bootloader (never used) |
| Model bytes | `30` THR5, `31` THR10, `32` THR10X, `33` THR10C, `34` THR5A |
| Settings request ("AllP") | `F0 43 7D 20 44 54 41 31 41 6C 6C 50 F7` (verified on THR5; constant `31`) |
| Settings dump | 276 bytes: 18-byte header `F0 43 7D 00 02 0C 44 54 41 31 41 6C 6C 50 00 00 7F 7F`, 256-byte payload, checksum, `F7`. Header contains literal `DTA1AllP` (not a forbidden command) |
| Checksum | `(~sum(bytes[6:-2]) + 1) & 0x7F`; the footswitch's header running sum `0x71` agrees (tested) |
| Dump also sent by amp | on preset-button press (per sysex_tones README) |
| Parameter command | `F0 43 7D 10 41 30 01 <param> ... F7`; THR10 ids: amp `00 00 <n>`, gain `01 00 <v>`, master `02`, bass `03`, middle `04`, treble `05`, cab `06 00 <n>`; effects `1x` comp, `2x` mod, `3x` delay, `4x` reverb, `5x` gate. 14-bit values are two 7-bit bytes |
| THR10 payload layout | name 0-63, amp 128, gain..treble 129-133, cab 134, effect blocks 144-223. **THR5 layout is unknown** (fewer amps/effects); the parser exposes raw bytes only |
| Knob events | verified on this amp for TONE (see above) |
| Bootloader | `DTA1ERASE`, `DTA1MAIN`, `DTA1ROMR` (and the `50`/`70` types): blocked in `protocol/safety.py` |

## Unverified / to research next

- Full effect/reverb/delay sub-layouts and amp names for the 5 MIC TYPE positions (compare LED positions with dumps).
- Whether knob movements produce MIDI notifications (probe while turning knobs: not yet tested).
- Device identification, session init, parameter IDs and encoding, checksums.
