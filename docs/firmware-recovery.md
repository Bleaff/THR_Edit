# THR5A firmware recovery: experimental and untested

> **DANGER — UNTESTED ON THR5A:** Writing the saved original image back has not been tested.
> A generated recovery MIDI file contains erase/write instructions and can leave the amplifier unusable.
> A valid dump and a lossless conversion are **not a guaranteed rollback option**.

This document accompanies the [THR5A → THR5 V2 guide](firmware-thr5a-to-thr5-v2.md). Recovery is a manual last-resort
attempt, independent of THR Control. Do not add firmware commands to the application, disable its safety protections,
or transmit a restore file during development, routine checks or automated tests.

## What was verified

On the single tested THR5A using Manjaro and USB-MIDI:

- Original main firmware was read successfully.
- Two independent captures decoded to identical 1048576-byte images.
- The converter verified the firmware checksums; SHA-256 fingerprints were recorded.
- An update-format MIDI file was generated from the saved original image.
- That MIDI decoded back to a byte-identical binary (`checksum matched`, `ROUNDTRIP PASSED`).

## What was not verified

- Writing the original firmware back to THR5A.
- Behavior after an interrupted flash.
- Recovery when the bootloader cannot enter `U`.
- Compatibility with every THR5A hardware revision or other THR models.

Yamaha excludes THR5A from its V2 updater and describes the official update as irreversible in its
[updater information](https://europe.yamaha.com/en/support/updates/61280-en.html). This experimental procedure does not
establish a supported exception to that restriction.

## Main firmware and bootloader

The [thr10 reference research](https://github.com/michaelforney/thr10) describes its update process as overwriting main
firmware (`DTAm`) while leaving boot firmware (`DTAb`), which contains the updater, intact. Based on that research,
the documented main-firmware update is expected to preserve the bootloader. This is an expectation, not a verified THR5A
recovery guarantee. The 1 MiB main image is not a full flash-chip or bootloader backup. Bricking remains possible.

If the amplifier **cannot enter firmware update mode and show `U`, stop**. USB recovery may not be possible;
specialized hardware servicing may be required. Do not send guessed bootloader messages or try other models' firmware.

If writing appears active, do not immediately disconnect USB or power-cycle. Allow time and review the device status
and terminal errors to establish completion or failure before considering another operation.

## Validate the saved recovery material without transmitting it

Use your own original backup from this particular amplifier, created **before cross-flashing**. Do not use a fresh dump
of the converted amplifier as if it were the factory image. Restore private backups from the second storage location
if necessary, then work in their directory:

```bash
cd ~/yamaha-thr5a-backup
sha256sum -c firmware.sha256
wc -c thr5a_backup_1.bin thr5a_backup_2.bin
cmp -s thr5a_backup_1.bin thr5a_backup_2.bin \
  && echo "BACKUPS IDENTICAL" \
  || echo "BACKUPS DIFFER"
```

Require both images to be 1048576 bytes and identical. The manifest records your first backup's actual hash; see
[reference fingerprints](../firmware/README.md) for the experiment's values. Your original firmware need not have the
same version/hash as that example. Missing files, errors or mismatches mean stop and investigate.

If the recovery MIDI was not preserved, generate it offline using the external tools prepared in the main guide:

```bash
make -C thr10 tools/bintomid
thr10/tools/bintomid \
  thr5a_backup_1.bin \
  thr5a_restore_DO_NOT_FLASH.mid
```

Do not overwrite your only saved recovery file. Check the generated or preserved MIDI by decoding it to a separate file:

```bash
lua thr10/tools/midtobin.lua \
  thr5a_restore_DO_NOT_FLASH.mid \
  thr5a_roundtrip.bin

cmp -s thr5a_backup_1.bin thr5a_roundtrip.bin \
  && echo "ROUNDTRIP PASSED" \
  || echo "ROUNDTRIP FAILED"
```

Require normal converter completion, `checksum matched` and `ROUNDTRIP PASSED`. These are local file operations;
they do not contact the amplifier and **do not establish that restoration will work**.

## Last-resort restore attempt — UNTESTED ON THR5A

Only consider this after reading the limitations above and validating the original backups and recovery MIDI.
First rule out ordinary audio-path/preset problems using the main guide's verification and troubleshooting sections.

1. Use the original AC adapter and a stable USB connection. Close THR Control and all other MIDI clients.
2. With the amplifier off, hold TAP/TUNER and switch it on. Once the display activates, press the same button five times
   within four seconds, then wait approximately six seconds.
3. Require **`U`**. If it does not appear, stop; do not try transmitting a file anyway.
4. Run `aplaymidi -l` and identify the connected Yamaha's current **ALSA Sequencer output**. Ports can change after every
   reconnection or mode change. A RawMIDI address such as `hw:2,0,0` is not an `aplaymidi` port.
5. A technically possible recovery attempt is sending the validated original-image MIDI once to that output.

**UNTESTED ON THR5A; potentially destructive.** The following is a command template, not a ready-to-run example.
Replace `<VERIFIED_PORT>` (including the angle brackets) with the output just identified, for example `24:0` only if
that is its current address. Literal angle brackets are shell redirection syntax; never paste the placeholder unchanged.

```text
aplaymidi -p <VERIFIED_PORT> \
  thr5a_restore_DO_NOT_FLASH.mid
```

The raw backup `.bin` is not a MIDI playback file. Never substitute it for the generated `.mid`.
Do not run or test the restore automatically, and do not repeatedly resend it on failure.

For a hypothetical successful restore, the reference update sequence would be erase indicators, a blinking write dot
and cycling `E`, `n`, `d` (`End`). **These indications have not been observed for a THR5A restore.** Keep power and USB
connected while erase/write is active. Successful player exit alone does not establish completion.

Only following a successful `End` indication should a normal reboot be attempted: switch off, wait briefly and power on
without TAP/TUNER. Then check normal operation and the original acoustic model behavior. No successful THR5A restore
result is claimed here. If the expected completion never arrives, review the status and seek servicing rather than
cycling power during active writing or sending further experimental commands.

## Keep recovery artifacts private

Yamaha firmware remains proprietary, including a MIDI file regenerated from your own dump. The project's AGPL license
does not grant distribution rights to it. Keep dumps, recovery MIDI, archives and derived patches in private storage;
do not commit them or upload them to GitHub Releases without distribution rights. See the
[firmware storage policy](../firmware/README.md).
