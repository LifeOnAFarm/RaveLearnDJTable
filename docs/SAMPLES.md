# Replacing sounds

Every sound on the table can be swapped for your own. Songs are uploaded on the web page;
everything else is a file in `/opt/PiDJTable/assets/` on the Pi. The installer fills that
folder from the repository's `sounds/` folder and generates the rest, and it never replaces
a file you have changed.

| Sound | Where | Used in |
| --- | --- | --- |
| Random songs | Upload on the **Home** page | NumPad button in Learning; each theme has its own list |
| Colour and shape words | `assets/samples/colours/<en or ga>/<colour>.wav` and `assets/samples/symbols/<en or ga>/<colour>.wav` | Learning, Levels 1 and 2 |
| Remix beats | `assets/backing_beats/` (Teenage Disco), `assets/house_beats/`, `assets/punk_beats/`, `assets/baby_raver_beats/` | Learning voice remixes |
| Recording prompt | `assets/recording-prompt.wav` | Before every recording |
| Announcements | `assets/announcements/` | Theme, mode and Level changes |
| Scratches | `assets/scratch/` (three included) | Platter spun in Learning with nothing playing |
| Music Maker drums | `assets/drums/music_maker/` | Music Maker, Level 2 |

The eight colours, used in every file name, are `pink`, `red`, `orange`, `green`,
`yellow`, `blue`, `purple` and `black`.

## Audio format

Use **WAV, 48 kHz, 16-bit, mono**, with little silence at the start. Keep levels similar
to the sounds you are replacing.

| Sound | Good length |
| --- | --- |
| Songs | 15–30 seconds (60 at most, 12 MB at most, 12 per theme) |
| Words | Under 2 seconds |
| Remix beats | 8–16 seconds, cut on whole bars so the loop joins cleanly |
| Recording prompt | 1–3 seconds, ending with the beep |
| Drum hits | Under 1 second (2 at most) |

Only use audio you made yourself or are allowed to use.

## Songs

1. On your computer, match the songs' loudness (below).
2. Open `http://<your-table>:8080`, choose **Learning** and the theme, and upload.
3. Use **Admin** to play, reorder or remove songs for any theme.

No restart is needed. Don't copy songs into the `data/` folders by hand.

### Matching loudness on your computer

Install [Python](https://www.python.org/downloads/) and
[FFmpeg](https://ffmpeg.org/download.html), download this repository, and run from its
folder:

```sh
# Every audio file in a folder (WAV, MP3, FLAC, M4A and more):
python tools/normalize_clips.py "my songs" --output "matched songs"

# A 25-second section starting 40 seconds into a song:
python tools/normalize_clips.py "song.mp3" --start 40 --duration 25 --output "matched songs"

# Remix beats, numbered and cut to 16 seconds:
python tools/normalize_clips.py "my beats" --kind backing --duration 16 --output "matched beats"
```

On Windows use `py` instead of `python`. It converts to the right format, matches
loudness and never overwrites your originals.

## Replacing files on the Pi

Copy the files from your computer to the Pi:

```sh
scp -r "matched beats" <your-user>@<your-table>.local:~/new-sounds
```

Then, on the Pi, stop the table, back up the folder you're changing, copy the new files
in and start it again. For example, for the House beats:

```sh
cd /opt/PiDJTable
sudo systemctl stop djtable
sudo cp -a assets/house_beats ~/house_beats-backup
sudo cp ~/new-sounds/*.wav assets/house_beats/
sudo chmod a+r assets/house_beats/*.wav
sudo systemctl start djtable
```

To replace a single word or the prompt, copy one file over the old one with exactly the
same name. Keep backups outside the `assets/` folders.

## Remix beats

Beat files must be named with two digits and an underscore, for example `01_funky.wav`,
`02_fast.wav`. Each remix picks one at random. A file without the number is ignored. To
replace all the beats in a theme, move the old folder somewhere else, create it again
empty, and copy in only the new beats.

## Recording prompt

`assets/recording-prompt.wav` is the whole prompt: "Record your message after the beep"
**and** the beep, in one file. Recording starts just after it ends.

## Announcements and scratches

Three scratches come with the table. Add more, or replace them, with any short WAVs
(about 1–2 seconds) in `assets/scratch/`; each platter spin plays a random one.

The announcements below are included. Replace any of them with a file of the same name;
delete one to make that event silent.

| File | Plays when |
| --- | --- |
| `theme_teenage_disco.wav`, `theme_house.wav`, `theme_punk.wav`, `theme_baby_raver.wav` | The theme changes (in Bluetooth mode, the Level picks Punk, Teenage Disco or House) |
| `mode_keyboard.wav`, `mode_maker.wav`, `mode_bluetooth.wav` | The keyboard mode changes |
| `level_keyboard_1.wav`, `level_keyboard_2.wav`, `level_keyboard_3.wav` | The Level slider moves in Learning |
| `bluetooth_connected.wav` | A phone connects |
| `maker_layer_deleted.wav`, `maker_all_deleted.wav` | Music Maker clears one layer or all of them |

## Music Maker drums

Each Tone position has its own kit of eight hits. Make a folder with your hits and a
`manifest.json`. The three kits are named `piano`, `high` and `synth`; these are only
the names for Tone 1, 2 and 3.

```json
{
  "sample_rate": 48000,
  "kits": {
    "piano": {
      "name": "My kit",
      "sounds": {
        "pink": "kick.wav", "red": "snare.wav", "orange": "hat.wav", "green": "open-hat.wav",
        "yellow": "tom.wav", "blue": "clap.wav", "purple": "cowbell.wav", "black": "crash.wav"
      }
    }
  }
}
```

Kits or keys you leave out keep the generated drums. Copy the folder to
`assets/drums/music_maker/`, so that `manifest.json` sits directly inside it, then
restart with `sudo systemctl restart djtable`. A file that can't be loaded is listed in
the log as `Drum sample fallback` (`journalctl -u djtable -n 50`). Loops recorded before the change keep their old drums.

## Back up

Keep copies of `config.json`, `assets/` and `data/` from `/opt/PiDJTable`. `data/` holds
your uploaded songs, the Music Maker loops and the sampled voice.
