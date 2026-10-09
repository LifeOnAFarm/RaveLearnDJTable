# Python audio optimisation, 27 September 2026

## Changes

- Input callback copies into a fixed pool of 16 buffers instead of allocating
  an array per callback. Ownership moves through single-producer/single-consumer
  CPython deques; buffers are returned only after copying completes.
- Output gathers microphone frames into preallocated storage instead of
  concatenating arrays. Oversize callbacks and exhausted pools are counted as
  dropped blocks rather than causing an unbounded allocation.
- Engine reuses gain ramps and retrigger fade scratch storage. Scalar smoothing
  uses `math.exp`. Each engine owns its buffers, preventing cross-engine reuse.
- Output blocks larger than the 4096-frame workspace are processed in chunks.
- Existing interpolation, limiting and small Python control objects still
  allocate; this is a targeted optimisation, not an allocation-free engine.

## Pi hardware measurements

Zero 2 W, 48 kHz, 512-frame blocks, reported output latency 32 ms. Silent tests
exercise eight keys, retriggers, a song and pitch bending, with the microphone
stream open. They do not record speech or establish perceived latency.

| House 12-second run | Before | After |
| --- | ---: | ---: |
| Key presses | 240 | 240 |
| Peak callback CPU fraction | 54.7% | 53.1% |
| Neutral-pitch peak CPU fraction | 36.2% | 31.9% |
| Reported output/input status blocks | 0 / 0 | 0 / 0 |
| Dropped commands/input blocks | 0 / 0 | 0 / 0 |
| Slowest timed callback | 10.438 ms | 11.468 ms |

All four modes passed a 12-second post-change test without reported dropouts.
These short, non-randomised runs show modest load reduction, not a guaranteed
speedup. Worst-case timing did not improve; Linux scheduling, memory pressure
and page faults remain relevant. A 512-frame deadline is about 10.67 ms; the
configured output latency can absorb some isolated callback lateness.

Local regression tests cover repeated recordings, buffer reuse, queue overflow,
oversize input, learning alternation, polyphony, remixes, web uploads and modes.
No package holds, boot audio settings or user media were changed for this pass.

The before/after mixer produced identical samples over 1,200 compared blocks
across the four modes (maximum absolute difference 0). The clean source suite
passes 76 tests on Windows with three optional asset checks skipped. In a
separate directory on the actual Pi, locally generated starter assets passed
the asset check, all 76 tests passed without skips, the simulation WAV rendered,
and the service installer passed `sh -n`. eSpeak NG and its data/libraries were
downloaded and unpacked for that test without installing system packages. This
does not validate the complete service installation on a fresh OS image.

## Reproduce

Stop the normal audio service before opening the same device in the benchmark:

```sh
cd /opt/PiDJTable
sudo systemctl stop djtable
sudo -u djtable .venv/bin/python -m djtable.bench --mode house --seconds 30
sudo systemctl start djtable
```

Repeat for `teenage_disco`, `punk` and `baby_raver`. The command exits nonzero
on reported stream errors or dropped input/commands. Always restart the service
after testing, including a failed test. Keep device, governor and audio settings
the same for before/after comparisons. Listen and test real recordings separately.
# Voice instrument — 30 September 2026

The latest character revision replaces the higher/chipmunk patch with a metallic
robot and adds distortion, moving chorus and flutter to the lower monster.
Effects are prepared offline, preserving the playback workload. All 94 local
tests and 14 Pi voice tests passed. The 20-second stress run reported zero
dropouts/dropped blocks or commands, peak callback CPU fraction 0.552, and one
14.114 ms callback against a 10.667 ms block duration, covered by buffering in
this run. See `VOICE_INSTRUMENT.md` for the current tone mapping.

The three-character update (normal, higher/chipmunk and lower/monster) passed
all 93 tests locally and on the Pi. Its 20-second muted stress test exercised
400 presses with all three tones, a song, bending and USB input: reported
dropouts and dropped commands/blocks were zero. Peak callback CPU fraction
was 0.577. One callback reached 11.605 ms against a 10.667 ms block duration;
buffering covered it in this run, so this does not establish that every callback
meets its deadline. A successful save now plays the original-pitch take once.

The voice activity reuses the existing held-note mixer. Capture, trimming,
filtering and all eight transposed samples are prepared in the worker, then
published to the callback. The latest take is limited to 1.5 seconds.

A muted 20-second Zero 2 W test played 400 key presses with eight voice notes,
retriggering, a song, pitch bending and USB input. Output/input status blocks
and dropped commands/blocks were all zero. Peak callback CPU fraction was
0.581 (0.339 at neutral pitch); the longest callback was 10.044 ms against a
10.667 ms block duration. This is a bounded stress result, not an audible test
or guarantee against dropouts in every situation. All 90 local tests passed.


Music Maker adds three saved loop layers (melody, drums, voice), selected on the webpage independently of Learning themes. See [Music Maker controls](MUSIC_MAKER.md). Loop rendering and persistence run on the background worker; playback uses preloaded eight-second tracks.

## Music Maker optimisation — 1 October 2026

Normal sustained notes now mix directly from their prepared patches without a
per-voice waveform allocation. Loop playback resamples one combined arrangement,
prepared by the worker, instead of resampling each of the three layers. During
recording the individual layers remain available so the selected layer can be
muted. The combined float64 track uses about 3 MiB extra RAM at 48 kHz.

Custom drum kits are loaded before generating procedural fallback hits, so a
complete kit avoids synthesising 24 unused sounds. Small settings JSON files are
cached until their file signature changes; unchanged quantisation settings are
no longer repeatedly queued. Webpage polling pauses while the tab is hidden.

Recording fixes retain very short quantised notes, fade retriggered held notes,
wrap full drum tails across the loop boundary, and align capture timestamps with
the callback that actually starts recording. Saved loop formats and manifest
shapes are validated; cleanup only removes orphaned generated loop filenames.

Matched muted 20-second tests on the same Zero 2 W, 48 kHz, 512 frames and 32 ms
output latency used three layers, 24 custom drum hits, 400 key presses, live bend
and an open USB microphone stream.

| Measurement | Before | After |
| --- | ---: | ---: |
| Neutral-pitch peak callback CPU fraction | 38.7% | 32.7% |
| Bending peak callback CPU fraction | 53.1% | 50.0% |
| Output/input status blocks | 0 / 0 | 0 / 0 |
| Dropped commands/input blocks | 0 / 0 | 0 / 0 |
| Slowest timed callback | 9.430 ms | 12.474 ms |

The neutral result is about a 15% reduction; the bending result about 6%.
These are short sequential runs, not a statistical guarantee. Worst-case timing
did not improve: one changed-code callback exceeded the 10.667 ms block duration,
with five minor page faults. Buffering covered this in the measured run. The
tests were muted, so physical sound quality still needs listening verification.

All 113 regression tests passed on Windows and the Pi. Audio parity tests cover
neutral sustain/release and combined versus individual loop resampling, including
wraps and changed speeds. New tests cover short quantised taps, long cymbal tails,
invalid saved loops and settings cache refresh/recovery. Live app/web services
restarted successfully with all 24 custom drum hits and no loop-load errors.
Saved loop/voice file hashes and protected package versions/holds were unchanged.
V1 was not modified.

Reproduce the audio run with the normal service stopped:

```sh
sudo systemctl stop djtable
cd /opt/PiDJTable
sudo -u djtable env OPENBLAS_NUM_THREADS=1 .venv/bin/python -m djtable.bench --activity maker --mode baby_raver --preload-modes --seconds 20
sudo systemctl start djtable
```

Always restart the service after a failed benchmark too.
