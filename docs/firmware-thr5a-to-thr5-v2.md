# Experimental THR5A → THR5 V2 cross-flashing on Linux

This guide records one successful conversion of a first-generation Yamaha THR5A acoustic amplifier to THR5 V2 electric
guitar firmware using Manjaro Linux and ALSA USB-MIDI. It is a manual procedure independent of THR Control.
THR Control does not update firmware; its firmware and bootloader command blocks must remain enabled.

> **DANGER:** Cross-flashing is unsupported by Yamaha. A failed update can render the amplifier unusable.
> Reading firmware and validating a recovery file do **not** establish a working rollback method.
> Writing the original THR5A firmware back has **NOT BEEN TESTED**. Read the
> [recovery guide](firmware-recovery.md) before deciding to proceed.

Complete the backup section before preparing or transmitting any update. Commands here are instructions for a person
deliberately performing the procedure; do not run them as a development check, automated script or application feature.

## Scope and tested environment

| Component | Tested configuration |
| --- | --- |
| Original amplifier | Yamaha THR5A, first generation |
| Target firmware | Yamaha THR5 V2 |
| Operating system | Manjaro Linux |
| Connection | USB 2.0 Type-A to Type-B |
| USB vendor ID | `0499` |
| Observed USB product ID | `1506` |
| ALSA name | `THR5` |
| MIDI interface | `THR5 MIDI 1` |
| Original RawMIDI port | `hw:2,0,0` (example only) |
| Original Sequencer port | `24:0` (example only) |

Ports are dynamic: re-enumerate after reconnecting USB, rebooting or changing modes. Linux may call the original THR5A
`THR5` even before flashing; the name alone does not identify the installed firmware.
This result does not establish compatibility with every THR5A revision or other THR family members, including THR-II.

## Requirements and workspace

- First-generation THR5A and its original power adapter.
- USB Type-A to Type-B cable and a Linux computer with a stable USB connection.
- ALSA MIDI utilities, Lua (5.3 or newer for the converter), Git, Make and a C compiler.
- Space for several 1 MiB images, MIDI captures and the official updater archive.
- A second storage location for the original backup.

On Arch Linux / Manjaro:

```bash
sudo pacman -S --needed \
  alsa-utils git lua make gcc
```

`lsusb` is provided by `usbutils`; install it if missing. The optional artifact inspection below uses `file` and `od`
(`file` and `coreutils` packages on Arch).

Create a private workspace **outside the THR Control source checkout**:

```bash
mkdir -p ~/yamaha-thr5a-backup
cd ~/yamaha-thr5a-backup

git clone https://github.com/michaelforney/thr10.git
git -C thr10 rev-parse HEAD
```

Record the tools' revision alongside your backup. The locally retained tools used for this experiment were at
`f777b6a024633a63687edcf750335dd2c8e47b1b`; to use that same revision after cloning:

```bash
git -C thr10 checkout --detach f777b6a024633a63687edcf750335dd2c8e47b1b
```

Credit belongs to Michael Forney's independent [thr10 firmware research and tools](https://github.com/michaelforney/thr10).
Those tools were documented for the THR10 family. The read procedure and this particular cross-flash were established
experimentally on THR5A. We use only the converters, not the project's firmware patches or full firmware build.
No reference implementation code is copied into THR Control.

All subsequent relative file paths assume `~/yamaha-thr5a-backup` as the current directory, including in new terminals.
Use new filenames if backups already exist; never overwrite your only known-good copy. Close THR Control, DAWs, editors
and other MIDI clients before the procedure.

## 1. Back up the original THR5A firmware — mandatory

### 1.1 Enter firmware update mode

1. Connect the amplifier to its original power adapter.
2. Turn the amplifier off.
3. Hold **TAP/TUNER** while turning it on.
4. Once the display activates, press that same button five times within four seconds.
5. Wait approximately six seconds.
6. Confirm that the display shows **`U`**.

`U` indicates firmware update mode. **Do not proceed unless it is confirmed.** Connect USB to the Linux computer.

### 1.2 Identify USB and both MIDI interfaces

```bash
lsusb
amidi -l
arecordmidi -l
```

Observed on the tested original THR5A:

```text
ID 0499:1506 Yamaha Corp. THR5

Dir Device    Name
IO  hw:2,0,0  THR5 MIDI 1

Port    Client name    Port name
24:0    THR5           THR5 MIDI 1
```

`amidi` uses a **RawMIDI** hardware port such as `hw:2,0,0`. `arecordmidi`, `aseqdump` and `aplaymidi` use an
**ALSA Sequencer** port such as `24:0`. They are different address spaces and are not interchangeable.
Identify the connected Yamaha interface in each listing. Every numeric port below is an example from the tested system:
**replace it with your current verified port before running each command**. Do not rely on an old port number.

### 1.3 Start recording before requesting the dump

Terminal 1 (keep it running):

```bash
cd ~/yamaha-thr5a-backup
arecordmidi -p 24:0 \
  thr5a_backup_1.mid
```

Optional Terminal 2, to watch incoming MIDI and detect completion:

```bash
aseqdump -p 24:0
```

### 1.4 Request one firmware dump

In a separate terminal, using the verified **RawMIDI** port:

```bash
amidi -p hw:2,0,0 -S \
'F0 43 7D 50 44 54 41 31 52 4F 4D 52 02 F7'
```

This is Michael Forney's documented `DTA1ROMR` read request. **Send it once.** It requests firmware data rather than
erasing or updating it, but the protocol is unofficial and unsupported on THR5A. Transmission took approximately
2.5 minutes on the tested amplifier. Do not send another request while it is transmitting.

### 1.5 Wait for the checksum message, then stop recording

The transmission ends with `DTA1CSUM`. The tested final SysEx was:

```text
F0 43 7D 70
44 54 41 31 43 53 55 4D
7A F7
```

The ASCII command is `DTA1CSUM`; its final checksum byte (`7A` here) can vary by firmware version.
After that message arrives, stop `arecordmidi` with **Ctrl+C**, allowing it to finalize the MIDI file. Stop the optional
monitor too. A `.mid` file that is still zero bytes during recording does not necessarily indicate failure; the container
may only be finalized when the recorder exits. If you did not monitor, allow the expected transfer time and validate the
completed capture below; elapsed time alone is not evidence of a complete dump.

### 1.6 Extract and validate the first binary

```bash
cd ~/yamaha-thr5a-backup
lua thr10/tools/midtobin.lua \
  thr5a_backup_1.mid \
  thr5a_backup_1.bin

wc -c thr5a_backup_1.bin
sha256sum thr5a_backup_1.bin
```

Require normal command completion and `checksum matched`. The observed raw main firmware size was **1048576 bytes
(1 MiB)**, with SHA-256:

```text
4d4719740db8f1217127f23c3fb0406cad5b74f8a7421a7e2db8d5c158cf7f3e
```

This identifies one real THR5A dump, **not every THR5A firmware version**. Record your actual hash. A checksum message alone
is insufficient: also require the expected nonempty size and the second matching dump. This is a main firmware backup,
not a complete bootloader/flash-chip image.

### 1.7 Make a second independent capture

Repeat sections 1.3–1.5 with the recorder output named `thr5a_backup_2.mid`. Start a new recording, send the read request
once, wait for completion and stop the recorder. Do not just copy the first capture.

```bash
lua thr10/tools/midtobin.lua \
  thr5a_backup_2.mid \
  thr5a_backup_2.bin

wc -c thr5a_backup_2.bin
sha256sum \
  thr5a_backup_1.bin \
  thr5a_backup_2.bin

cmp -s \
  thr5a_backup_1.bin \
  thr5a_backup_2.bin \
  && echo "BACKUPS IDENTICAL" \
  || echo "BACKUPS DIFFER"
```

The experiment produced `checksum matched` for both captures and **`BACKUPS IDENTICAL`**. Only proceed if both conversions
pass, both images are 1 MiB and they match byte for byte. If they differ, stop and investigate ports, capture completion
and file paths. Never choose one arbitrarily.

### 1.8 Preserve the originals outside this computer

```bash
sha256sum thr5a_backup_1.bin \
  > firmware.sha256

tar -czf ~/THR5A_FACTORY_BACKUP.tar.gz \
  thr5a_backup_1.bin \
  thr5a_backup_1.mid \
  thr5a_backup_2.bin \
  thr5a_backup_2.mid \
  firmware.sha256
```

Copy the archive to a second computer, USB drive or private storage. Check that the second copy opens and its extracted
`thr5a_backup_1.bin` passes `sha256sum -c firmware.sha256` from the extraction directory. Preserve the captures and tools'
revision too. Do not commit these files or publish them as release assets.

## 2. Prepare an experimental recovery file — offline only

**A readable backup is not a proven recovery method.** Build only the host converter:

```bash
make -C thr10 tools/bintomid

thr10/tools/bintomid \
  thr5a_backup_1.bin \
  thr5a_restore_DO_NOT_FLASH.mid
```

The converter uses the host C compiler (`c99` by default); this target does not require the ARM toolchain used for the
reference project's firmware patches.

> **Write-capable file:** The generated MIDI contains firmware erase/write instructions.
> **DO NOT transmit it during ordinary verification.** Conversion only writes local files.

Decode it back and compare:

```bash
lua thr10/tools/midtobin.lua \
  thr5a_restore_DO_NOT_FLASH.mid \
  thr5a_roundtrip.bin

cmp -s \
  thr5a_backup_1.bin \
  thr5a_roundtrip.bin \
  && echo "ROUNDTRIP PASSED" \
  || echo "ROUNDTRIP FAILED"
```

Observed results: `checksum matched` and **`ROUNDTRIP PASSED`**. This verifies byte-for-byte round-trip conversion only.
**It does not prove that the resulting MIDI can restore a THR5A.** If validation fails, stop. Preserve the validated
recovery MIDI and its hash privately with a second copy, separate from any files intended for playback.

## 3. Obtain and verify official THR V2 firmware

Use [Yamaha's official THR downloads](https://usa.yamaha.com/products/musical_instruments/guitars_basses/amps_accessories/thr/downloads.html).
The [Windows V2 updater information](https://europe.yamaha.com/en/support/updates/61280-en.html) specifies THR5/THR10 only,
explicitly excludes THR5A, THR10C and THR10X, and describes the official update as irreversible.
Cross-flashing a THR5A is therefore an unsupported modification, even if the bytes come from Yamaha.

### 3.1 Locate the Mac updater resource

The successful experiment used the resource from Yamaha's **Mac V2 updater**, not a patched image or a Windows executable.
Select the Mac THR V2 updater on the downloads page, review its terms, and download/extract it privately. Do not execute
the updater as part of this Linux workflow. Inside the extracted application bundle, locate:

```text
THR_V2_Updater.app/
  Contents/
    Resources/
      THR_Firm_ver200main.bin
```

Archive/container layouts can vary. This record establishes the resource path and its exact bytes; it does not establish
a tested Linux unpacking command for every Yamaha package. If your archive tool cannot expose the bundle, extract it
on a Mac and transfer the resource privately. Do not substitute a third-party firmware download.

Copy the resource into the private workspace, replacing `/path/to/extracted` with the actual extraction directory:

```bash
cd ~/yamaha-thr5a-backup
cp /path/to/extracted/THR_V2_Updater.app/Contents/Resources/THR_Firm_ver200main.bin .
```

Despite its `.bin` extension, this resource is a **Standard MIDI File (SMF)**. Inspection should identify format 1 with
two tracks. Its first four bytes are `4D 54 68 64` (ASCII `MThd`). For local inspection:

```bash
file THR_Firm_ver200main.bin
od -An -tx1 -N4 THR_Firm_ver200main.bin
wc -c THR_Firm_ver200main.bin
sha256sum THR_Firm_ver200main.bin
```

It contains SysEx commands including `DTA1ERASE` and `DTA1MAIN`: treat it as a dangerous, write-capable update file.
Header inspection alone does not verify its content.

### 3.2 Check the exact update artifact

| File | Size (bytes) | SHA-256 |
| --- | ---: | --- |
| `THR_Firm_ver200main.bin` | 1252328 | `7104965b7957255bad94b2be078045b3dbffef8cd16642217f0e39185e74ebd5` |

An explicit local check for the tested resource:

```bash
printf '%s  %s\n' \
  '7104965b7957255bad94b2be078045b3dbffef8cd16642217f0e39185e74ebd5' \
  'THR_Firm_ver200main.bin' | sha256sum -c -
```

Expect `THR_Firm_ver200main.bin: OK`. This fingerprint identifies the exact file used successfully. Other official
downloads may differ. **Investigate a mismatch rather than assuming equivalence or renaming another file to match.**
A different artifact requires independent verification of origin and content and falls outside this reproduced result.

### 3.3 Optional: decode the raw V2 main image

```bash
lua thr10/tools/midtobin.lua \
  THR_Firm_ver200main.bin \
  thr5_v2_extracted.bin

wc -c thr5_v2_extracted.bin
sha256sum thr5_v2_extracted.bin
```

The experiment produced `checksum matched`, **1048576 bytes**, and:

```text
a502d43aaccb8062a0cb657400032e7c04dd9e37ff30f413b0267d782de3d753
```

The decoded raw image and original MIDI update have different sizes and hashes. **The raw 1 MiB `.bin` was not
transmitted during the tested update.** Playback used the original Yamaha MIDI resource, including its update messages
and timing. See the [manifest and filename notes](../firmware/README.md).

## 4. Flash THR5 V2 on Linux — destructive operation

> **DANGER: This operation erases and overwrites the amplifier's main firmware. A failed update can render the device
> unusable. THR5A cross-flashing is not supported by Yamaha. Recovery is not guaranteed.**

### 4.1 Before flashing

Verify every item:

- Two independently captured original backups passed converter checksums, have the expected size and match byte for byte.
- The original firmware SHA-256 is recorded.
- A readable backup copy is stored outside the working computer.
- The recovery MIDI was generated and passed round-trip validation; restoration remains untested.
- The official MIDI update matches the tested hash, or its origin and content have been independently verified.
- The amplifier uses its AC adapter, the USB connection is stable and power will remain available.
- Recording and monitoring have stopped, and no other MIDI application is using the interface.
- The amplifier is in firmware update mode and displays `U`.

If entering update mode again, use section 1.1 and wait for `U`. Do not proceed with a failed prerequisite.

### 4.2 Identify the MIDI output again

```bash
aplaymidi -l
```

Select the connected Yamaha THR's **ALSA Sequencer** port. The tested system used `24:0`; this may have changed.
The command below is valid **only if you have just verified that `24:0` is the correct output** and verified the update file.

### 4.3 Transmit the official MIDI update once

**This is a real write operation. Do not execute it for documentation development or verification.**

```bash
cd ~/yamaha-thr5a-backup
aplaymidi -p 24:0 \
  THR_Firm_ver200main.bin
```

Never pass `thr5_v2_extracted.bin` or another raw 1 MiB image to `aplaymidi`. It requires a valid Standard MIDI File with
the appropriate update messages. Do not replay the file repeatedly or alter its timing.

### 4.4 Watch the amplifier until completion

The thr10 reference describes tuner triangles during initial erasure (approximately 16 seconds), then a blinking green
dot during writing. Total update time is typically approximately 2.5 minutes. Treat these timings as estimates.
The tested THR5A completed by cycling its display through:

```text
E
n
d
```

This spells **`End`**. Do not interrupt USB or power while erasing or writing. Successful exit of `aplaymidi` alone does
not establish successful firmware completion or a working normal boot. If `End` does not appear, use troubleshooting
and the recovery guide; do not repeatedly send updates.

### 4.5 Reboot normally

Only after the amplifier displays successful `End`:

1. Switch it off.
2. Wait briefly.
3. Turn it on normally, without holding TAP/TUNER.

## 5. Verify normal operation

1. Confirm a normal boot.
2. Connect a working electric guitar to **INPUT**.
3. Leave **PHONES** empty when testing the speakers; an inserted plug disables the internal speakers.
4. Select an audible amp model/preset.
5. Set Gain, Master and output Volume to reasonable, audible levels.
6. Play the guitar.
7. Switch the physical amplifier model selector and listen for changes.
8. Check clean and overdriven sounds.
9. Check effects and tuner behavior, including leaving tuner mute mode before playing again.

The THR5A's printed labels stay the same. THR5 electric models include Clean, Crunch, Lead, Brit Hi and Modern;
audible differences were confirmed, but this experiment does not independently establish each selector position's model
name. On this converted unit BLEND serves the Gain function and MIC TYPE selects the amp model; MASTER and VOLUME
remain relevant. The later [control protocol observations](protocol.md) record the physical knob mapping and its limits.

The tester initially heard silence with an unsuitable preset/setting. Selecting an appropriate preset restored normal
guitar playback. Before interpreting silence as firmware corruption, check the cable, guitar volume, selected model,
Gain, Master, output Volume and tuner mute. Confirm the guitar is in INPUT rather than PHONES, and remove headphones
when testing internal speakers.

### Recorded result and limits

```text
Device: Yamaha THR5A
Target: THR5 V2
Host OS: Manjaro Linux
Transport: ALSA USB-MIDI
Backup: Passed
Round-trip recovery image validation: Passed
Flash completion: End
Normal reboot: Passed
Electric guitar playback: Passed
Amp models: Audible changes confirmed
Recovery flash to original THR5A: NOT TESTED
```

This records **one successfully tested configuration**. The checklist above includes recommended functional checks;
the recorded result establishes playback and audible model changes, not an exhaustive certification of every effect,
tuner function or hardware revision.

## 6. Troubleshooting

| Symptom | Possible cause / meaning | Action |
| --- | --- | --- |
| Recording `.mid` stays at 0 bytes | Recorder still running; container may not be finalized | Wait for `DTA1CSUM`, then stop `arecordmidi` with Ctrl+C and validate the finalized file. |
| No MIDI data | Not in update mode, wrong port, changed port after reconnection, or another client owns the device | Confirm `U`; rerun `amidi -l` and `arecordmidi -l`; close competing applications. Keep RawMIDI and Sequencer addresses distinct. |
| `midtobin.lua`: `attempt to index a nil value` | Missing/inaccessible input filename | Check `pwd`, input path and both positional filenames. Avoid relying on an unset shell variable. |
| `THR_Firm_ver200main.bin` is identified as MIDI | Expected: this `.bin` is an SMF container | Verify its `MThd` header, size and SHA-256; keep it distinct from the decoded raw image. |
| `checksum matched` but output is empty | Wrong file/path inspected or incomplete command | Confirm the exact output filename, normal command completion and `wc -c`; rerun offline verification with distinct paths. Do not flash an empty or unverified image. |
| `stat -f` gives unexpected output | macOS and Linux `stat` syntax differs | Use `wc -c firmware.bin` (replace with the actual filename). |
| Backups differ or converter reports checksum failure | Incomplete/corrupt capture, wrong file or transfer problem | Stop. Preserve both captures, check ports/paths and repeat independent backups. |
| Official update hash differs | Different download, resource or damaged file | Recheck the official source and bundle path; investigate before proceeding. |
| Flash completes but no guitar sound | Preset/level, cable, input routing, headphones or tuner mute | Follow section 5's audio-path checks before assuming corruption. |
| Update fails or `End` never appears | Playback completion does not establish device completion | Do not immediately power-cycle during active erase/write. Review terminal errors and device status, allow time for confirmed completion or failure, then consult the recovery guide. Do not repeatedly transmit updates. |
| Device cannot enter `U` | Boot/update path unavailable | Stop. USB recovery may be impossible; specialized hardware servicing may be required. |

## 7. Sources, attribution and distribution

- [Michael Forney's thr10 firmware read/write research and converters](https://github.com/michaelforney/thr10): original
  independent protocol work behind this procedure; originally documented for THR10-family devices.
- [Research write-up](https://mforney.org/blog/2026-05-28-patching-my-guitar-amps-firmware.html): main firmware (`DTAm`) and
  bootloader (`DTAb`) analysis. The expectation that the bootloader remains intact is based on this reference research,
  not a THR5A recovery test. It does not remove the risk of bricking.
- [Yamaha official downloads](https://usa.yamaha.com/products/musical_instruments/guitars_basses/amps_accessories/thr/downloads.html).
- [Yamaha V2 updater and cross-model restrictions](https://europe.yamaha.com/en/support/updates/61280-en.html).
- [Historical THR5A cross-flash report](https://www.musiker-board.de/threads/yamaha-thr-5a-firmware.579837/): an owner's
  firsthand account of accidentally installing electric firmware and lacking a rollback; historical context, not a
  validated recovery method or proof of universal compatibility.

The hardware results and fingerprints above come from the experiment reported by this project's developer. Independent
researchers retain credit for their own findings. No implementation code was copied from their projects; review their
licenses before reusing code.

Yamaha firmware is proprietary. This project's AGPL license grants **no distribution rights** to Yamaha firmware.
Do not commit or upload to GitHub Releases firmware dumps, extracted images, Yamaha archives, updater executables,
generated recovery MIDI or binary patches derived from Yamaha firmware without distribution rights. Use official
downloads and private local storage; see the [firmware policy](../firmware/README.md).
