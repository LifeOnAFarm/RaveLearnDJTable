# Replace songs, samples and backing beats

The Home page stays simple: choose Learning/Music Maker, select a Music
theme, and upload songs. Admin manages each theme's song list and tests the hardware. Drum kits and remix backings are changed in folders,
not through new webpage controls. All paths below assume the default config
and an installation in `/opt/PiDJTable`.

## What can be changed?

| Sound | Easiest method | Applies to | When it loads |
| --- | --- | --- | --- |
| Random songs | Upload WAV on Home; choose the Music theme first | Song button in Learning; each theme has its own playlist | Automatically, within a few seconds when safe |
| Colour/shape words | Replace `assets/samples/colours|symbols/<en|ga>/<colour>.wav` | Levels 1/2 of all Learning themes | Restart audio |
| Individual key sounds | Replace `assets/samples/keys/<tone>/<colour>.wav` | Levels 1/2 of that key | Restart audio; plays once, with no sustain loop |
| Remix backing beats | Copy numbered WAVs to the theme's beats folder | Learning voice remixes | Restart audio after changing files |
| Recording prompt + beep | Replace `assets/recording-prompt.wav` | Learning and Music Maker microphone capture | Restart audio |
| Music Maker drums | Copy WAVs and `manifest.json` to `assets/drums/music_maker/` | Level 2, three Tone kits; independent of Learning theme | Restart audio; re-record saved drum layers to hear the new kit |
| Music Maker melody / voice effects | Developer changes to `djtable/music_maker.py` / `voice_instrument.py` | Music Maker Levels 1/3 | Restart audio |

Back up any file under `assets/samples/` before replacing it, keep the same
file name, and use the formats below.

## Spoken announcements

Optional clips in `assets/announcements/`, played when something changes. The file
name is the event; a missing file is simply silent. Restart audio after changes.

| File | Plays when |
| --- | --- |
| `theme_<theme>.wav` (`theme_teenage_disco`, `theme_house`, `theme_punk`, `theme_baby_raver`) | The Learning theme changes; in Bluetooth mode, the Level picks Punk / Teenage Disco / House |
| `mode_maker.wav`, `mode_bluetooth.wav`, `mode_keyboard.wav` | The keyboard mode changes |
| `level_keyboard_1..3.wav` | The Level slider moves in Learning (Music Maker level changes are silent) |
| `bluetooth_connected.wav` | A phone connects in Bluetooth mode |
| `maker_layer_deleted.wav`, `maker_all_deleted.wav` | Music Maker clears one layer / all layers |

Use 48 kHz mono PCM16 WAV with little leading silence, at a similar level to the words.

## Audio formats and length

| Audio | Good length | Format / limits |
| --- | --- | --- |
| Random song | 15–30 seconds | Web: PCM16 WAV, mono/stereo, 8–48 kHz with default config; >0 to 60 seconds, max 12 MiB. 12 songs per theme. |
| Remix backing | 8–16 seconds, cut to complete bars | Recommended mono PCM16 48 kHz; must be nonempty. Shorter clips loop into the 16-second remix with a 10 ms crossfade; longer ones only use their opening. Keep under 60 seconds for the checker and small-memory Pi. |
| Spoken colour/shape | Usually under 2 seconds | Web format above; use a clean recording with little leading silence. |
| Learning key one-shot | Usually 0.2–2 seconds | Web format above; every key needs its own pitch. Uploading one file does not transpose it across keys. |
| Music Maker drum hit | Usually 0.05–1 second; **at most 2 seconds** | Mono PCM16 WAV at the configured rate, normally 48 kHz. |
| Prompt | Short phrase + beep, usually 1–3 seconds | Recommended mono PCM16 48 kHz; checker caps at 10 seconds. Include the beep in this file. |

The backing and prompt durations above are recommendations/checker limits,
not new runtime restrictions. Use the default 48 kHz config with the starter
generator and preparation tool; those tools output 48 kHz files.

## 1. Songs: webpage

1. Prepare the clip on your computer using `tools/normalize_clips.py` (see below).
2. Open `http://<pi-address>:8080`, select **Learning** and the desired theme,
   then upload the WAV. Uploading does not require SSH or a service restart.
3. Use Admin to preview, reorder or remove songs for any theme.

The app stores uploads under `data/library/uploads/` (Disco) or
`data/<theme>_library/uploads/`. Hashed filenames and `library.json` are managed
by the app. Do not copy songs into those folders or hand-edit their manifests.
A folder named `songs` on your computer is just an input collection; the app
does not automatically scan it. Once a web playlist exists, it is authoritative,
even when empty; `config.json`'s old `songs` list is only a pre-upload fallback.

## 2. Match song/backing volume on your computer

Install Python 3.11+ and FFmpeg. Run from the repository root:

```sh
# WAV/MP3/FLAC/etc directly inside the folder, not recursive:
python tools/normalize_clips.py "my songs" --output "matched songs"
# Extract a 25-second section starting at 40 seconds:
python tools/normalize_clips.py "full song.mp3" --start 40 --duration 25 --output "matched songs"
# Prepare numbered backing WAVs:
python tools/normalize_clips.py "my beats" --kind backing --duration 16 --output "matched beats"
```

On Windows use `py` if needed and optionally
`--ffmpeg "C:/ffmpeg/bin/ffmpeg.exe"`. The tool converts to mono PCM16 48 kHz,
uses two-pass loudness matching (-16 LUFS, -1.5 dBTP), adds short fades, preserves
originals and refuses to overwrite outputs. Read the JSON report and listen.
The helper accepts 1–60 second excerpts; **do not use it for very short drum
hits**. It matches loudness, not bass/treble EQ. Playback volume/ducking also
changes the final result. A full song needs an explicit excerpt; it is not
silently truncated. Inputs need to be your own or licensed for your use.

## 3. Replace remix backing beats

| Learning theme | Default backing folder |
| --- | --- |
| Teenage Disco | `assets/backing_beats/` |
| House | `assets/house_beats/` |
| Punk | `assets/punk_beats/` |
| Baby Raver | `assets/baby_raver_beats/` |

Names **must** start with two digits and an underscore and end with lowercase
`.wav`, for example `01_my_beat.wav` or `06_fast_loop.wav`. A plain `beat.wav`
is ignored. At least one numbered beat is required in each configured folder.
Use clean loop boundaries; a crossfade cannot fix a badly cut phrase.

Transfer your prepared folder with SCP, using your own username/address:

```sh
scp -r "matched beats" <your-user>@<pi-address>:~/incoming-beats
```

Then on the Pi, wait until recording/preparation finishes:

```sh
cd /opt/PiDJTable
sudo systemctl stop djtable
# Save the entire old folder OUTSIDE the scanned backing directory:
task_old="assets/house_beats.before-$(date +%Y%m%d-%H%M%S)"
sudo cp -a assets/house_beats "$task_old"
# Copy or replace individual numbered clips; other old beats remain in the pool:
sudo cp ~/incoming-beats/*.wav assets/house_beats/
sudo chmod a+r assets/house_beats/*.wav
sudo .venv/bin/python tools/check_media.py
sudo systemctl start djtable
```

To replace the whole pool, move the old directory to a backup name, create the
original directory again, and copy only the desired clips into it. Do not store
backup numbered WAVs inside an active beats folder. Always restart the service,
even if the checker fails; restore the previous folder first when necessary.
Copying raw backing files is not an automatic live reload: the beat list is
cached until restart. Saved remixes retain their original sound.

Default folder paths can be changed with `backing_beats_dir`, `house_beats_dir`,
`punk_beats_dir`, `baby_raver_beats_dir` in `config.json`. Paths there resolve
relative to the config file, not your current shell directory. A theme's
backing folder and its random-song playlist are different things.

## 4. Replace Music Maker drum hits

Copy `examples/drum-kit/manifest.json` into your own kit folder and edit it.
The example lists all 24 slots but contains **no WAV files**. Supply them or
remove assignments you do not want; omitted slots use generated fallback hits.

```text
my-kit/
  manifest.json
  piano/pink.wav     # Tone 1 kick, for example
  piano/red.wav      # Tone 1 snare
  ...
  high/pink.wav      # Tone 2 kick
  ...
  synth/pink.wav     # Tone 3 kick
  ...
```

`piano`, `high`, `synth` are internal names for Tone positions 1, 2, 3;
they do not mean that drums play a piano. `name` sets the kit label shown in
status. `sounds` maps colour keys to relative filenames; those filenames may
be descriptive and must remain inside the kit directory. Example partial kit:

```json
{
  "sample_rate": 48000,
  "kits": {
    "piano": {
      "name": "My punchy kit",
      "sounds": {"pink": "kick.wav", "red": "snare.wav"}
    }
  }
}
```

Recommended roles are pink kick, red snare, orange closed hat, green open hat,
yellow tom, blue clap, purple cowbell/effect, black cymbal. Any hit may occupy
any colour. Convert each to mono PCM16 48 kHz, trim unwanted silence, add tiny
edge fades where appropriate and leave headroom. For example:

```sh
ffmpeg -i kick-source.wav -ac 1 -ar 48000 -c:a pcm_s16le kick.wav
```

This only converts format: trim and balance hits in your audio editor. The
song normaliser's one-second minimum makes it unsuitable for short drum hits.

Transfer from your computer: `scp -r my-kit <your-user>@<pi-address>:~/`.
Then on the Pi, after any recording/preparation finishes:

```sh
cd /opt/PiDJTable
sudo .venv/bin/python tools/check_media.py --drum-root ~/my-kit
# Continue only when the assigned files pass checks:
sudo systemctl stop djtable
sudo mkdir -p assets/drums
# If a custom kit already exists, move it out of the active path:
if [ -d assets/drums/music_maker ]; then
  sudo mv assets/drums/music_maker "assets/drums/music_maker.before-$(date +%Y%m%d-%H%M%S)"
fi
sudo cp -a ~/my-kit assets/drums/music_maker
sudo chmod -R a+rX assets/drums/music_maker
sudo .venv/bin/python tools/check_media.py
sudo systemctl start djtable
```

`manifest.json` must sit directly inside `assets/drums/music_maker/`, not in
an extra nested `my-kit` folder. If checks fail, restore the backup before
restarting. A first custom install has no old folder to back up.

The checker is read-only and exits nonzero on file/format errors. It checks
all four backing folders and the prompt too, so read which path failed.
Missing custom slots are allowed; missing/invalid *assigned* files are errors.
The runtime falls back per invalid drum slot and reports `drum_errors` on
Admin. The checker does not measure loudness or check that a WAV is nonsilent.
Re-record Level 2 to replace an already rendered drum layer. Learning themes
and uploaded songs do not change this kit.

## 5. Prompt and built-in sustained instruments

For the prompt, replace `assets/recording-prompt.wav` after backing it up,
check it, and restart audio. Include “Record a message after the beep” **and**
the beep in one WAV. Capture begins after the whole file plus a 120 ms settling
tail; no separate beep is added.

Built-in sustained Learning instruments use
`assets/instruments/<theme>-48000-v2.npz` (loop metadata + samples). These are
created by `tools/bootstrap_assets.py`; editing the oscillator code in
`djtable/instruments.py` does not replace an existing archive. Back up/move the
archive, then regenerate with audio stopped. Only that missing archive is
rewritten. The generator preserves existing key/word/backing WAVs too.
`assets/instruments/piano.wav` etc. and its theme subfolders contain admin
**previews**, not keyboard inputs. Existing previews remain until separately
backed up/moved and regenerated. Uploaded key overrides still take priority.

Music Maker melody uses the default Disco piano/synth plus its own bass,
not the selected Learning theme or uploaded Learning key slots. Voice effects
are prepared from the latest recorded take; see [VOICE_INSTRUMENT.md](VOICE_INSTRUMENT.md).

## Back up before changes

Keep `config.json`, **all of `data/`**, and your custom **`assets/`** together.
`data/music_maker/` contains current/Undo layers; `data/voice_instrument/`
contains the sampled voice; `data/*remixes/` contains saved Learning remixes.
Stop both services for a consistent backup. These directories are ignored by
Git and are not included in the MIT source licence. See [UPDATING.md](UPDATING.md).
