# Music Maker

Select **Music Maker** under Keyboard mode on the webpage. Learning retains English, Irish, sustained notes and its sound themes. Music Maker has its own fixed sounds.

| Level | Tone 1 | Tone 2 | Tone 3 |
| --- | --- | --- | --- |
| 1 Melody | Piano | Synth | Bass |
| 2 Drums | Acoustic | Electronic | Fun percussion |
| 3 Voice | Normal | Robot | Monster |

Eight keys play notes or eight drum sounds. Melody and voice sustain while held. Drum hits finish on their own. Volume works in both modes.

**Make a loop:** Hold Record. After a short hold, four clicks count you in. Keep holding, then play keys. Release Record to finish, or keep holding for the full eight seconds. Each loop is four bars at 120 BPM. Empty takes keep the old layer. A new take replaces only the current Level's layer; the other two remain. Changing Level finishes the current take. Keys pressed during the count-in are ignored: release and press after the clicks.

**Sample your voice:** At Level 3, tap and release Record instead of holding. Wait until the beep finishes, then make a short sound (up to 1.5 seconds). Your take plays once after saving. This replaces the voice used for future playing/recording; previously rendered voice layers retain their sound.

**Song button:** Tap to play/pause. Hold for 2 seconds, then release to clear the current Level's layer. Hold for 5 seconds, then release to clear all three layers and pause. One click marks the 2-second threshold; two clicks mark 5 seconds. Nothing is cleared before release. The Level is the one selected when you pressed Song. The webpage shows which clear is armed and offers Undo to restore the previous saved arrangement, including after clearing. Uploaded songs and your sampled voice remain available. The webpage also offers Play/pause, Clear all and timing correction to sixteenth notes. Undo toggles between the current and previous saved arrangement.

The platter bends live notes and changes loop speed/pitch together. During layer recording, playback and notes use normal speed so events remain aligned. Recording starts at the beginning of the loop. The layer being replaced is silent during capture; other layers play. Microphone sampling pauses the loop to prevent feedback.

Layers persist under `data/music_maker/`, with one atomic manifest referencing the current and previous arrangement. Loop preparation, voice effects and SD writes run outside the audio callback. Switching back to Learning pauses Music Maker and preserves its layers. Song uploads and Learning theme selection remain on the Learning webpage and admin page.

This is an audio loop instrument; it does not send MIDI. Back up personal
recordings and layers before updates; see [UPDATING.md](UPDATING.md).

## Drum sample folders

Optional custom drum hits live in `assets/drums/music_maker/`. `manifest.json` declares `sample_rate` and a `kits` object keyed by `piano`, `high`, `synth` (the three Tone positions). Each kit has a `name` and a `sounds` mapping from the eight colour names to relative WAV filenames. Use mono PCM16 at the configured sample rate (normally 48 kHz), at most two seconds per hit. Restart the audio service after replacing samples. Missing/invalid slots retain their generated drum sound and report a diagnostic; other valid slots still load.

The public release contains generated Acoustic, Electronic and Fun percussion
kits. Optional custom sample packs are excluded from the source export. See
[SAMPLES.md](SAMPLES.md#4-replace-music-maker-drum-hits) and
`examples/drum-kit/manifest.json` for preparing and installing your own kit.
Suggested keys: pink kick, red snare, orange closed hat, green open hat, yellow
tom, blue clap, purple cowbell/effect, black cymbal. Existing rendered layers
retain their old sound; record a new Level 2 layer after replacing a kit.
