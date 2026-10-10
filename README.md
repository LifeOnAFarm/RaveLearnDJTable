# Fisher-Price: Rave & Repeat DJ Table

A Raspberry Pi rebuild of a Fisher-Price kids' DJ table toy: an eight-key musical play
table running on a **Raspberry Pi Zero 2 W**, written in Python 3.11+.

Full run down of the hardware setup can be found [here](https://nastypieceof.work/raveandrepeat)

## Software guides

1. [Installation](docs/INSTALL.md): the step-by-step setup, from a blank SD card to a finished table.
2. [Hardware](docs/HARDWARE.md): switches, amplifier, INMP441 or USB microphone, platter and power.
3. [Samples](docs/SAMPLES.md): replace songs, backings, drums, prompt and instruments.
4. [Updates](docs/UPDATING.md): update code without losing personal audio/settings.

The release contains **no commercial songs, licensed drum packs or personal
recordings**. `tools/bootstrap_assets.py` generates original instruments and
six percussion backings per theme, plus eSpeak NG English/Irish words and a
prompt. These are functional starter voices.

## Playing

Choose between **Learning** (English/Irish colours and shapes,
sustained notes, random songs and voice remixes) and **Music Maker** (three
recorded loop layers), or play along with phone music over **Bluetooth**.

| Control | Learning | Music Maker |
| --- | --- | --- |
| Level | 1 English; 2 Irish; 3 sustained notes | 1 melody; 2 drums; 3 sampled voice |
| Tone | Three sounds in the selected Learning theme | Three instruments/kits/voice characters for the current Level |
| Record | Prompt/beep, 3-second voice capture, 16-second pitched remix | Hold through count-in to record a layer; tap at Level 3 to sample voice |
| Song | Random uploaded song, or stop current song/remix | Tap play/pause; hold 2s clear current layer, 5s clear all; release to apply |
| Bluetooth mode | Phone music plays through the table; keys play along (Level = Punk / Teenage Disco / House); Song = play/pause, hold = next | |
| Platter (optional) | Bend notes / change song speed; when idle, scratch your latest recording like vinyl | Bend live notes / change loop speed; neutral during layer capture |

Volume low/medium/high works in both modes. In Learning Levels 1/2, repeat a
key to alternate colour and shape; a different key resets to colour. Keys may
accompany songs/remixes. Learning themes are Teenage Disco, House, Punk and
Baby Raver; each has separate random songs/backings. Themes do not affect
Music Maker. 
See [Music Maker](docs/MUSIC_MAKER.md) and
[Voice Instrument](docs/VOICE_INSTRUMENT.md) for recording actions.

## Folder layout

```text
RaveLearnDJTable/           # installed on the Pi as /opt/PiDJTable
  README.md                 # this page
  CHANGELOG.md, CONTRIBUTING.md, SECURITY.md, LICENSE
  config.example.json       # tracked, safe defaults
  requirements.txt
  docs/                     # INSTALL, HARDWARE, SAMPLES, UPDATING, MUSIC_MAKER,
                            # VOICE_INSTRUMENT, PERFORMANCE, PUBLISHING
  djtable/                  # Python engine, GPIO, web service
    static/                 # Home, Admin and Wi-Fi pages
  deploy/                   # installers, services, I2S overlay, Pi tuning, hotspot, Bluetooth
  tools/                    # starter sounds, loudness matching, media checker
  tests/                    # hardware-free regression tests
  examples/drum-kit/        # editable manifest; no licensed audio
  .github/                  # CI workflow, issue and pull request templates
  config.json               # your settings, ignored
  assets/                   # generated/custom sounds, ignored
  data/                     # uploads, settings, saved recordings/layers, ignored
  .venv/                    # Python environment, ignored
```

Generated and personal files are deliberately separate from source. No folder
renaming is needed on an existing toy.

## Development checks

Install FFmpeg and eSpeak NG for utility and starter-asset checks, plus NumPy
and PortAudio. On a development computer, GPIO is not needed for unit tests:

```sh
cp config.example.json config.json
python3 -m venv .venv
.venv/bin/pip install 'numpy>=1.24,<3' 'sounddevice>=0.5,<0.6'
.venv/bin/python tools/bootstrap_assets.py
.venv/bin/python -m djtable --check-assets
.venv/bin/python tools/check_media.py
.venv/bin/python -m unittest discover -s tests -v
```

Windows: use `py -m venv .venv` and `.venv/Scripts/python.exe`; eSpeak NG and
FFmpeg must be on PATH. Tests do not require GPIO or a sound device; the asset
checks require generated audio. `--no-speech` only makes a notes-only development
build, not a playable complete install. [docs/PERFORMANCE.md](docs/PERFORMANCE.md) records
Pi measurements and limitations; [CONTRIBUTING.md](CONTRIBUTING.md) explains
callback constraints.

## Boundaries and licence

> Unofficial hobby project. Not affiliated with, endorsed by or sponsored by Fisher-Price
> or Mattel. Fisher-Price is a trademark of its owner, used here only to describe the toy
> this project rebuilds.

MIT source; see [LICENSE](LICENSE). Dependencies and your uploaded audio retain
their own licences.
