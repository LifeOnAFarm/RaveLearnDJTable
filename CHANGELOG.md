# Changelog

## 9 October 2026: second table

**Repository layout:** guides moved to `docs/`, leaving the root for README, CHANGELOG,
CONTRIBUTING, SECURITY and LICENSE. New `docs/PUBLISHING.md` (GitHub steps and release
checklist, replacing RELEASE_CHECKLIST.md), `SECURITY.md`, issue and pull request templates,
and a CI check that scripts use LF line endings. The House sample test skips when only the
synthesised starter House is installed.

Lessons from setting up a second table on a fresh card, now built into the scripts and guide:

- **INSTALL.md is a strict, ordered procedure** with a check after every step, rules
  (unique hostname per table, fast A1/A2 card, no upgrades, never copy from a Windows folder),
  a "copy an existing table" path (3B) and a final hands-on checklist.
- `install-duplex.sh` now also sets I2C on, SPI off and UART off, and **removes Imager's
  serial login console**, which sat on BCM 14/15 (the Volume slider). It changes the image's
  `dtparam=audio=on` line instead of adding a second one, and is safe to run again.
- New `deploy/native-wifi.sh`: converts Imager's netplan Wi-Fi profile to NetworkManager's
  own format (boot was about 10 s slower with it).
- `install-services.sh` precompiles the code (the service user cannot write a bytecode cache).
- A slow SD card (11.7 MB/s against 23 MB/s) made start-up about 4 s slower; INSTALL.md now
  measures the card first.

## 6 October 2026: faster start-up

- Keys and words are ready first; songs load in the background a few seconds later
  (`Modes.load(..., songs=False)`). Sound is ready about 9 s sooner after power-on.
- `deploy/tune-pi.sh` also disables cloud-init (first-boot only) and `e2scrub_reap`.
- `djtable.service` gets CPU and I/O priority over other boot jobs.
- Switch inputs are read directly through lgpio (gpiozero is the fallback); other themes'
  instrument packs load after the songs. `tune-pi.sh` adds: no initramfs (when safe), no boot
  partition check, no splash/boot delay, and removes the unused netplan Ethernet profile.
  Keys play about 19 s after the kernel starts (was about 33 s).

## 5 October 2026 (late): one loudness scale

- `tools/level_report.py` measures every sound as the toy plays it (small-speaker weighted,
  relative to the Teenage Disco instruments). Targets: instruments 0 dB, words/announcements
  and voice instrument about −2 dB, songs about −3 dB, drums and scratches about −1 dB.
- Songs +2.5 dB (soft-limited) and **no longer dip when keys are pressed**, so music and keys blend.
- Punk instruments +3.5 dB (soft-limited); words and announcements +2.5 dB; Music Maker drums −3 dB;
  voice instrument raised (older saved takes are re-levelled when loaded).
- Record prompt beep (882 Hz) is notched out of every take, and capture starts 0.45 s after the beep.

## 5 October 2026 (night): platter scratching, one-and-done remixes

- **Remixes play once** after recording and are no longer saved or replayed.
- **Platter scratch**: in Learning, with nothing else playing, a spin plays a random scratch
  sample from `assets/scratch/` (never the same twice in a row; slow down before the next).
- Instruments may be **one-shot samples** (loop markers at the sample end): they ring out
  fully instead of looping a sustain. Used by the House theme.
- Music Maker voice sample is now 3 s (was 1.5 s); Music Maker level changes are no longer announced.

## 5 October 2026 (evening): voices and announcements, mode button hold

- Spoken announcements from `assets/announcements/` for theme, keyboard mode and Level
  changes, Bluetooth connection and Music Maker clears (see SAMPLES.md). Missing clips are silent.
- Mode button: hold 5 s for the next keyboard mode; a tap (now on release) still changes theme.
- The Dank theme is renamed **House** (folders `house_beats`, `house_library`, `house_remixes`,
  `assets/modes/house`, `assets/instruments/house*`). An old saved `dank` selection loads as House.

## 5 October 2026 (later): Bluetooth speaker mode

- New Keyboard mode **Bluetooth**: phone music (A2DP) plays through the table, mixed
  with drift correction; keys play along with Level 1/2/3 = Punk / Teenage Disco / House
  instruments; Song taps play/pause and a hold skips track; Record is off.
- Visible as **DJTable** for two minutes; no connection returns to Learning. Pairing is
  accepted only in that window; paired phones are trusted.
- `deploy/install-bluetooth.sh` + socket-activated root helper: Bluetooth and BlueALSA
  run (and the radio is unblocked) only in this mode, so other modes use no extra memory.
- Phone audio is buffered 250 ms (absorbs bursty delivery when Wi-Fi shares the radio);
  `Bluetooth stream underruns=N` is logged every 10 s while streaming.

## 5 October 2026

- Slider pin order now matches the PCB: Tone 1/2/3 = BCM 7/24/23, Level = 8/26/25,
  Volume = 15/14/9 (previously the reverse). Fixed in code, not configurable.

## 4 October 2026: simpler web pages

- One header and navigation (Home · Admin · Wi-Fi) and one card/button style on all pages.
- **Home** (was "Add a song"): Keyboard mode first, then **Music theme** (hidden in
  Music Maker). Status text appears only while a mode or theme is loading or on an
  error. Theme changes no longer reload the page. The Music Maker panel is just its
  status, Play / pause, Undo, Clear all and the beat-alignment option.
- **Admin**: a compact **Hardware test** (tap Tone/Level/Volume to override a slider,
  live button presses, platter and microphone) and a **Songs** list for any theme,
  viewable without switching the toy. Sound previews, key/word replacement and
  explanatory text were removed; replace those files in `assets/samples/` instead.
- **Wi-Fi**: just the network status and the join form.
- Status feed adds `buttons` (held buttons and the last press) for the hardware test.

## 2 October 2026 (later): mode button, pixel removed

- **Mode button on BCM0 / pin 27** cycles the Learning themes, using the same
  path as the webpage (including the amp mute). Ignored in Music Maker and
  during recording/processing.
- **LED pixel support removed** (`djtable/pixel.py`, its SPI overlay, status and
  Admin display, `pixel_enabled`). BCM20 is used only for the INMP441. An old
  `pixel_enabled` key in `config.json` is ignored.

## 2 October 2026: audio reliability and shared-I2S microphone

### Fixed
- **Crackle when changing Learning theme.** Theme changes loaded samples from the
  SD card while the amplifier stayed on. DJTable now stops the output stream for
  the switch, which makes the voiceHAT driver pull the MAX98357A SD pin (BCM4)
  low, and restarts it once the new theme is queued. Typical silence is 2–3 s.
  Config: `mute_amp_on_switch` (default `true`). Requires amp SD → BCM4.
- **Underruns on a busy Pi.** `djtable.service` sets `OPENBLAS_NUM_THREADS=1` so
  NumPy does not start one worker thread per core next to the audio callback.
- **World-writable source after copying from Windows.** `install-services.sh`
  now removes group/other write permission from the installed code.

### Added
- `deploy/tune-pi.sh`: console boot, unused services and timers off, PipeWire
  masked, graphics CMA 256 → 64 MB. Removes the desktop's swap pressure on a Zero 2 W.
- `deploy/install-duplex.sh`: installs the shared-clock INMP441 + MAX98357A overlay.
- `deploy/install-hotspot.sh`: optional Wi-Fi fallback with your own password.
- HARDWARE.md: full shared-I2S pin table, amp mute wiring, the pin 38/40 short
  that causes constant noise/feedback, clock routing, decoupling and power notes.
- INSTALL.md: INMP441 setup and test, appliance tuning, hotspot, troubleshooting.

### Diagnosis notes (prototype PCB)
- Constant noise/feedback appeared only with the INMP441 fitted and stopped when it
  was removed; the refitted mic now captures clean 24-bit data. No software path
  sends microphone audio to the speaker.
- With the desktop running, theme switches produced 11 underruns; after tuning, 0.
  The remaining crackle had no underrun and followed SD card activity, which the
  amp mute removes.
- Moving amp power, ground, or both to the Pi header did not change the crackle.
