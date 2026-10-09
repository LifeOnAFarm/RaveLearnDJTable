# Fisher-Price Rave & Learn DJ Table

A Raspberry Pi rebuild of a Fisher-Price kids' DJ table toy: an eight-key musical play
table running on a **Raspberry Pi Zero 2 W**, written in Python 3.11+.

> Unofficial hobby project. Not affiliated with, endorsed by or sponsored by Fisher-Price
> or Mattel. Fisher-Price is a trademark of its owner, used here only to describe the toy
> this project rebuilds.

Choose between **Learning** (English/Irish colours and shapes,
sustained notes, random songs and voice remixes) and **Music Maker** (three
recorded loop layers), or play along with phone music over **Bluetooth**. This is
a working hobby project, built and tested on its own PCB.

## Start here

1. [docs/INSTALL.md](docs/INSTALL.md): the step-by-step setup, from a blank SD card to a finished table.
2. [docs/HARDWARE.md](docs/HARDWARE.md): switches, amplifier, INMP441 or USB microphone, platter and power.
3. Open `http://<pi-address>:8080`: **Home** picks the keyboard mode and music
   theme and adds songs; **Admin** tests buttons, sliders, platter and microphone
   and manages song lists; **Wi-Fi** joins a new network.
4. [docs/SAMPLES.md](docs/SAMPLES.md): replace songs, backings, drums, prompt and instruments.
5. [docs/UPDATING.md](docs/UPDATING.md): update code without losing personal audio/settings.

The release contains **no commercial songs, licensed drum packs or personal
recordings**. `tools/bootstrap_assets.py` generates original instruments and
six percussion backings per theme, plus eSpeak NG English/Irish words and a
prompt. These are functional starter voices. Songs start empty; Music Maker
has generated fallback drums until you supply a custom kit.

## Playing

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
Music Maker. See [docs/MUSIC_MAKER.md](docs/MUSIC_MAKER.md) and
[docs/VOICE_INSTRUMENT.md](docs/VOICE_INSTRUMENT.md) for recording, timing and Undo.

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

Two microphone paths work on the prototype: a USB microphone, or an INMP441
sharing the MAX98357A's I2S clocks (`deploy/install-duplex.sh`). Other PCB
layouts and OS/audio combinations need their own hardware checks. The
mode button (BCM0) changes theme on a tap and keyboard mode on a 5-second hold; CS4344 MCLK is not enabled.
Platter and capture default off. The Wi-Fi fallback hotspot is optional (`deploy/install-hotspot.sh`);
`deploy/tune-pi.sh` frees memory on a dedicated Zero 2 W ([docs/INSTALL.md](docs/INSTALL.md) step 9). Use the Pi's local IP; the web service has no accounts and
belongs on a trusted LAN, without router port forwarding.

MIT source; see [LICENSE](LICENSE). Dependencies and your uploaded audio retain
their own licences. Personal media is not covered by the source licence.
