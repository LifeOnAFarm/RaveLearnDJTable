# Fisher-Price: Rave & Repeat DJ Table

A Raspberry Pi rebuild of a Fisher-Price kids' DJ table toy: an eight-key musical play
table running on a **Raspberry Pi Zero 2 W**, written in Python 3.11+.

Full run down of the hardware setup can be found [here](https://nastypieceof.work/raveandrepeat).

## Software guides

1. [Installation](docs/INSTALL.md): from a blank SD card to a finished table.
2. [Replacing sounds](docs/SAMPLES.md): songs, words, beats, drums, the recording prompt
   and announcements.

## What it does

The table has three keyboard modes, chosen on its web page or by holding the mode button
for 5 seconds.

**Learning.** The keys say their colour and shape in English (Level 1) or Irish (Level 2),
or play notes (Level 3). Song plays a random song. Record asks for a message, records
3 seconds of your voice and plays it back as a pitched-up remix over a beat. There are four
music themes, each with its own instruments, songs and beats: **Teenage Disco, House, Punk
and Baby Raver**. A tap on the mode button changes theme.

**Music Maker.** Build a loop in three layers: melody (Level 1), drums (Level 2) and your
own voice as an instrument (Level 3).

**Bluetooth.** Phone music plays through the table and the keys play along.

| Control | Learning | Music Maker | Bluetooth |
| --- | --- | --- | --- |
| Keys | Colour/shape words or notes | Notes, drums or your voice | Notes over the music |
| Level | 1 English, 2 Irish, 3 notes | 1 melody, 2 drums, 3 voice | 1 Punk, 2 Teenage Disco, 3 House sounds |
| Tone | Three sounds per theme | Three instruments, kits or voice characters | Three instruments |
| Volume | Low / medium / high | Low / medium / high | Low / medium / high |
| Record | Voice remix | Hold: record a layer after the count-in. Tap at Level 3: sample a sound to play on the keys | Off |
| Song | Random song, or stop | Tap: play/pause. Hold 2 s: clear this layer. Hold 5 s: clear all | Tap: play/pause. Hold: next track |
| Platter | Bends notes and song speed; spun on its own, plays a scratch | Bends notes and loop speed | |

Optional spoken announcements say when the theme, mode or Level changes.

In Bluetooth mode the table is visible as **DJTable** for two minutes. Pair with no PIN.
If no phone connects in time, it goes back to Learning.

## Web pages

Open `http://<your-table>:8080` from a phone or computer on the same network.

- **Home:** keyboard mode, music theme and song uploads.
- **Admin:** live test of every button, slider, the platter and the microphone, plus each
  theme's song list.
- **Wi-Fi:** join a new network. If the table can't find a known network, it offers its
  own **DJTable-Setup** network (see the install guide).

## Sounds

The repository contains **no commercial songs, licensed samples or personal recordings**.
The installer generates original starter instruments, beats and drums, and English/Irish
words with eSpeak NG. Make the table your own with [Replacing sounds](docs/SAMPLES.md).

## Folder layout

```text
djtable/        the app: audio engine, buttons, platter, web pages
deploy/         install scripts, services, sound overlay
tools/          starter sound generator, song volume matcher
docs/           install and sound guides
config.example.json   the table's settings (copied to config.json on install)
```

On the Pi, `config.json`, `assets/` (sounds) and `data/` (songs, recordings, loops) are
created by the installer and are never part of the repository.

## Licence

> Unofficial hobby project. Not affiliated with, endorsed by or sponsored by Fisher-Price
> or Mattel. Fisher-Price is a trademark of its owner, used here only to describe the toy
> this project rebuilds.

MIT source; see [LICENSE](LICENSE). Your own songs and sounds keep their own licences.
