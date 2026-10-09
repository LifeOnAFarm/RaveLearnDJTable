# Voice instrument

Choose **Music Maker** under **Keyboard mode** on the home or Admin page, then move Level to **3**. See [Music Maker](MUSIC_MAKER.md) for the three-layer looper controls. Learning themes apply only to Learning.

1. Pause the loop with the Song button if it is playing.
2. **Tap and release Record** (holding records a loop layer), wait until the usual prompt and beep have finished, then make a short sound.
   Capture starts after the prompt's short 120 ms settling tail, never on the beep.
   Capture lasts **1.5 seconds** (or the configured recording duration if shorter).
   Try “ah”, “meow”, a laugh, or a short word close to the microphone.
3. After saving, the new recording plays **once at its original pitch** to confirm
   it is ready. Preparation takes a short moment after capture. Keys can play alongside this confirmation.
4. With Tone 1, pink uses the original pitch; successive colours transpose it by
   2, 4, 7, 9, 12, 14 and 16 semitones. These are relative intervals, not automatic
   tuning of speech to concert C. Higher notes are shorter, as on a sampler.
5. Hold to repeat the sound; release to fade out. Play chords and use the platter
   for the existing ±2-semitone bend. Volume works as usual.

The latest usable take is available in Music Maker and survives restarting.
Record again to replace it. Quiet/invalid takes or a failed save retain the
previous working voice. In Voice instrument, the tone slider selects:

| Tone position | Voice |
| --- | --- |
| 1 | Normal recording |
| 2 | Metallic robot: ring modulation and coarse digital texture |
| 3 | Growly monster: distortion, moving chorus and throat flutter, pitched down 7 semitones |

Each character has the same eight key intervals. The robot keeps the normal
recording speed; the monster also plays lower and slower. Both effects alter
the voice texture before keyboard transposition. Move the tone slider, then press the keys again.
Existing saved voice takes gain all three characters automatically on startup.

In Music Maker, Levels 1 and 2 play melody and drums. Hold Record through the count-in to record a layer at any Level. Tap Record at Level 3 to replace the sampled voice. Song plays/pauses the loop; hold for two seconds to clear the current layer, or five seconds to clear all; release to apply. Undo is on the webpage. Learning retains spoken colours/symbols, random songs and voice remixes. The instrument take is separate from the five remixes and is not added to the song pool.

## Implementation and recovery

- Selection: `data/activity.json`; default is `keyboard`.
- Latest instrument: `data/voice_instrument/take.wav`, mono PCM16 at the configured
  sample rate. Only the last successful take is kept.
- Recording, trimming, filtering, gain and all eight pitches are prepared by
  the existing worker. Playback reuses the held-note mixer, release fades,
  retrigger tails and chord limiting; no files are read in the audio callback.
- The physical Record action is fixed at the start of capture, so moving a
  slider or choosing another activity cannot redirect a take halfway through.
- Back up `config.json`, `data/` and custom `assets/` before source updates;
  see [UPDATING.md](UPDATING.md). This feature does not require boot changes.

For a silent hardware stress test, stop the audio service first, run
`python -m djtable.bench --activity maker --mode baby_raver --preload-modes --seconds 20`,
then restart the service. This uses a synthetic test take in RAM, leaves saved
voice/media untouched, and does not verify how the microphone sounds.
