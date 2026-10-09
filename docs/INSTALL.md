# Install on a Raspberry Pi Zero 2 W

This is the tested procedure for the DJTable PCB (MAX98357A speaker amp and INMP441
microphone on shared I2S, AS5600 platter). Follow the steps **in order** and do not
skip a check: each later step assumes the earlier ones passed. It was last run from a
freshly imaged card on Raspberry Pi OS (Debian 13 "trixie", 64-bit, Python 3.13) on
9 October 2026.

## Rules

1. **One table, one SD card, one hostname.** Give every table its own hostname
   (`djtable1`, `djtable2`, …). Two tables with the same name fight over `<name>.local`.
2. **Use a fast card.** Choose an A1/A2-rated card of 16 GB or more. Check it in step 2:
   a card reading under about 20 MB/s makes start-up several seconds slower.
3. **No upgrades during setup.** Every `apt` command here uses `--no-upgrade`. Never run
   `apt upgrade`/`full-upgrade` on a working table, and never unhold networking packages.
4. **Copy files from Linux, git or the Pi, never from a Windows folder.** Windows copies
   add CRLF line endings, which break the shell scripts, and make files world-writable.
   `git clone` of the published repository is fine.
5. **Run every command from `/opt/PiDJTable`** unless the step says otherwise. The scripts
   check this and stop.
6. **Back up before changing a working table.** All scripts here save what they change
   under `/var/backups/djtable-*`, but copy `config.json` and `data/` off the Pi first.
7. **Do not type a password into any script.** Only `install-hotspot.sh` takes one, and
   that is the new hotspot's own password.

## 1. Prepare the SD card (on your computer)

In [Raspberry Pi Imager](https://www.raspberrypi.com/software/) choose **Raspberry Pi Zero
2 W** → **Raspberry Pi OS Lite (64-bit)**. Lite has no desktop; the full image also works
(step 9 turns the desktop off) but takes longer and uses more of the card. In the
customisation settings:

- **Hostname:** a unique name, for example `djtable2` (rule 1).
- **Username and password:** your own.
- **Wi-Fi:** your 2.4 GHz network, and your Wi-Fi country.
- **Services:** enable SSH and paste your computer's **public key** (`~/.ssh/id_ed25519.pub`).
  Key login lets you copy files and run commands without retyping a password.

Insert the card, power the table and wait about two minutes for the first boot.

## 2. First login and checks

```sh
ssh <your-user>@<hostname>.local
```

Check the board, the OS and the card:

```sh
cat /proc/device-tree/model; echo
. /etc/os-release; echo "$PRETTY_NAME"
python3 --version
sudo dd if=/dev/mmcblk0 of=/dev/null bs=1M count=200 iflag=direct
```

Expect `Raspberry Pi Zero 2 W`, Debian 12 or 13, Python 3.11 or newer, and a read speed of
about 20 MB/s or more. If the card is slower, replace it now (rule 2).

Install the packages DJTable needs, without upgrading anything:

```sh
sudo apt update
sudo apt install --no-upgrade --no-remove git python3-venv python3-numpy python3-gpiozero \
    python3-lgpio libportaudio2 alsa-utils espeak-ng ffmpeg device-tree-compiler
```

If APT wants to remove or upgrade packages to resolve dependencies, stop and investigate.

## 3. Install the code

Pick **one** of these.

**A. New table:** start from the published source and generate the starter sounds.

```sh
git clone https://github.com/LifeOnAFarm/RaveLearnDJTable ~/PiDJTable
sudo cp -a ~/PiDJTable /opt/PiDJTable
cd /opt/PiDJTable
sudo cp config.example.json config.json
```

**B. Second table or replacement card:** copy an existing table, including songs,
sounds, Music Maker loops and settings. Run this on a **computer** that can SSH into both
Pis with keys (old table first, new table second):

```sh
ssh <user>@<old-table> 'sudo tar cf - -C /opt --exclude=PiDJTable/.venv --exclude=__pycache__ PiDJTable' \
  | ssh <user>@<new-table> 'sudo tar xpf - -C /opt'
```

The Python environment (`.venv`) is never copied; it is rebuilt in step 4. Compare file
counts afterwards; they must match:

```sh
ssh <user>@<old-table> 'sudo find /opt/PiDJTable -path "*/.venv" -prune -o -name __pycache__ -prune -o -type f -print | wc -l'
ssh <user>@<new-table> 'sudo find /opt/PiDJTable -type f | wc -l'
```

If the old table is older than this guide, also copy the newest `deploy/` scripts from the
repository into `/opt/PiDJTable/deploy/` on the new table.

## 4. Python environment and services

```sh
cd /opt/PiDJTable
sudo python3 -m venv --system-site-packages .venv
sudo .venv/bin/pip install 'sounddevice>=0.5,<0.6'
sudo sh deploy/install-services.sh
```

`install-services.sh` creates the `djtable` service user, makes the code read-only
(only `data/` is writable), precompiles it and installs the two services. It does not start them.

For a **new table (3A)** only, generate the starter sounds now. This takes a while on a
Zero 2 W; let it finish:

```sh
sudo .venv/bin/python tools/bootstrap_assets.py
```

Check, as the service user:

```sh
sudo -u djtable env HOME=/tmp .venv/bin/python -m djtable --config /opt/PiDJTable/config.json --check-assets
sudo -u djtable env HOME=/tmp .venv/bin/python -m unittest discover -s tests
```

Expect `0 errors` and every test `OK`. Do not continue until both pass.

## 5. PCB audio and pins

Wire the board per [HARDWARE.md](HARDWARE.md), including amp SD → BCM4. Then:

```sh
cd /opt/PiDJTable
sudo sh deploy/install-duplex.sh
sudo reboot
```

This one script sets everything the PCB needs in `config.txt` and `cmdline.txt`:

- installs the shared-clock overlay (the kernel's voiceHAT driver at 48 kHz) and turns the
  on-board audio off;
- I2C on (platter);
- SPI off (BCM 7–11 are switches);
- the serial console off. Imager puts a login console on BCM 14/15, which are the Volume
  slider; while it is there, Volume reads wrong.

Check after the reboot:

```sh
aplay -l | grep googlevoicehat
pinctrl get 18-21
grep -c serial0 /boot/firmware/cmdline.txt
ls /dev/i2c-1
```

Expect the `snd_rpi_googlevoicehat_soundcar` card, PCM_CLK, PCM_FS, PCM_DIN and PCM_DOUT,
a `0`, and `/dev/i2c-1`.

## 6. Configure audio (new table only)

A copied table (3B) already has its `config.json`; skip to step 7.

Test the microphone before enabling it. The card is exclusive, so DJTable must not be running:

```sh
cd /opt/PiDJTable
arecord -D hw:CARD=sndrpigooglevoi -f S32_LE -r 48000 -c 2 -d 4 mic-test.wav
```

Copy `mic-test.wav` to a computer and listen: speech on the left channel, right silent.
Then set in `config.json` (`sudo nano config.json`):

```json
"input_device": "snd_rpi_googlevoicehat",
"output_device": "snd_rpi_googlevoicehat",
"input_channels": 2,
"mic_channel": 0,
"independent_input": false,
"capture_enabled": true,
"block_size": 512,
"volume": 1.0
```

Use the prefix `snd_rpi_googlevoicehat`; ALSA truncates the full card name. Set
`"platter_enabled": true` only once the AS5600 and its magnet are fitted.

## 7. Bluetooth and Wi-Fi fallback

```sh
cd /opt/PiDJTable
sudo sh deploy/install-bluetooth.sh
```

This installs BlueALSA and an on-demand helper; Bluetooth stays off until the
Bluetooth Keyboard mode is chosen (see [Bluetooth speaker mode](#bluetooth-speaker-mode)).

The hotspot fallback offers **DJTable-Setup** if no saved Wi-Fi connects for 45 seconds.
On a **new table**, choose its password:

```sh
sudo sh deploy/install-hotspot.sh 'your-own-hotspot-password'
```

On a **copied table (3B)**, keep the old table's hotspot password by copying its profile
straight across, from the same computer as step 3B, then install the watcher:

```sh
ssh <user>@<old-table> 'sudo cat /etc/NetworkManager/system-connections/DJTable-Hotspot.nmconnection' \
  | ssh <user>@<new-table> 'sudo install -m 600 /dev/stdin /etc/NetworkManager/system-connections/DJTable-Hotspot.nmconnection && sudo nmcli connection reload'
ssh <user>@<new-table> 'cd /opt/PiDJTable && sudo install -m 755 deploy/djtable-network.py /usr/local/lib/ && sudo install -m 644 deploy/djtable-network.service /etc/systemd/system/ && sudo systemctl daemon-reload && sudo systemctl enable djtable-network'
```

## 8. Wi-Fi in NetworkManager's own format

Imager saves its Wi-Fi network as a netplan profile (`nmcli connection show` lists
`netplan-wlan0-<name>`). NetworkManager then reruns netplan and reloads systemd several
times during every boot, about 10 extra seconds. Convert it:

```sh
cd /opt/PiDJTable
sudo sh deploy/native-wifi.sh
```

The original is backed up and the Wi-Fi password is copied file to file, never shown.
Networks joined later from the DJTable Wi-Fi page are already in the native format.

## 9. Tune as an appliance, enable and reboot

```sh
cd /opt/PiDJTable
sudo sh deploy/tune-pi.sh
sudo systemctl enable djtable djtable-web
sudo reboot
```

`tune-pi.sh` backs up first, then:

- boots to the text console (no desktop);
- disables printing, Bluetooth (until the mode starts it), udisks2, accounts-daemon, VNC,
  NFS/rpcbind, ModemManager, cloud-init and the automatic apt/man-db timers;
- masks PipeWire (DJTable uses ALSA directly);
- reduces graphics memory to 64 MB;
- boots without an initramfs (only when the kernel has the SD card and ext4 drivers
  built in), skips the boot-partition check and the rainbow splash;
- removes the unused first-boot Ethernet profile.

It is safe to run again. If a board will not boot afterwards, put the card in a computer
and set `auto_initramfs=1` again in `config.txt` on the boot partition.

## 10. Final checks

After the reboot:

```sh
systemd-analyze
systemctl is-active djtable djtable-web djtable-network djtable-bluetooth.socket
systemctl --failed
journalctl -b -u djtable -o short-monotonic | grep -E 'Audio running|Mode/library ready'
nmcli -t -f NAME,DEVICE connection show --active
free -m
```

Expect four `active` lines and no failed units. With a good card, `Audio running` appears
about 20 s after power-on and `Mode/library ready` with the song count a few seconds later.
The active Wi-Fi connection must not start with `netplan-`.

Then test with your hands and ears:

1. Open `http://<hostname>.local:8080` and then **Admin → Hardware test**.
2. Move each slider through all three positions and check the reading.
3. Press every key, Song, Record and the mode button and check the button readout.
4. Spin the platter.
5. Play keys at full volume: no hum, howl or crackle.
6. Change theme with the mode button: silence for 2–3 s, then no crackle.
7. Record a message and listen to the remix.
8. Choose Bluetooth on Home and pair a phone within two minutes.

Constant hum or howl with the INMP441 fitted means microphone data is reaching amp DIN;
see HARDWARE.md (pins 38/40).

## Bluetooth speaker mode

Bluetooth stays off, with the radio blocked, until **Bluetooth** is chosen as the
Keyboard mode on Home. The table is then visible as **DJTable** for two minutes;
pair with no PIN. If no phone connects in that time it returns to Learning and turns
Bluetooth off. Paired phones reconnect without the window.

In Bluetooth mode the keys play sustained notes over the music: Level 1 Punk,
Level 2 Teenage Disco, Level 3 House instruments, Tone picks the instrument.
Tap Song for play/pause on the phone, hold it (about a second) for the next
track. Record is off. Wi-Fi and Bluetooth share the Zero 2 W's radio, so the web
pages may respond more slowly while music streams.

## Using the table

Open `http://<hostname>.local:8080` to choose the Keyboard mode and Music theme and to
upload random songs. Admin (`/admin`) has the live hardware test and each theme's song
list. The mode button on BCM0 changes theme on a tap and keyboard mode on a 5-second hold.
There is no shutdown button: use `sudo poweroff`.

For replacing sounds, folder maps and the drum manifest, see [SAMPLES.md](SAMPLES.md).
Drum kits and backing beats are folder-based updates.

## Preparing audio

### Clip lengths and formats

| Audio | Recommended length | Actual playback/limit |
| --- | --- | --- |
| Random songs | 15–30 seconds | Web uploader accepts more than zero and **at most 60 seconds**, up to 12 MiB per file. |
| Recording backings | 8–16 seconds, preferably a whole number of musical bars | Each remix is **16 seconds**. Shorter backings automatically loop with a 10 ms crossfade; longer tracks use only the opening 16 seconds. There is no fixed minimum or enforced duration cap in the backing loader, but keep files short to avoid unnecessary memory use. |
| Voice capture | 3 seconds by default | The voice is pitched up and repeated four times in the remix. |

Use **48 kHz, PCM 16-bit WAV**, preferably mono. The web uploader also accepts
stereo and lower sample rates, but mono saves memory. A 60-second mono file at
48 kHz is about 5.5 MiB. The per-mode library also has aggregate memory/disk
limits; the 60-second limit is per clip, not permission to preload unlimited songs.

A backing does **not** have to be exactly 16 seconds. Choose a clean musical
loop so its end joins its beginning naturally; crossfading cannot repair a
badly cut beat. If you want no repeated section, provide at least 16 seconds.

### Match clip volume before uploading

Run this on your computer, preferably while the Pi is being used for playback.
Install Python 3.11+ and [FFmpeg](https://ffmpeg.org/download.html), then ensure
`ffmpeg -version` works. No additional Python packages are needed by this tool.
On Linux, the package is usually installed with `sudo apt install ffmpeg`.

From the source repository folder:

```sh
# Process all supported audio files directly inside a folder:
python tools/normalize_clips.py "my songs" --output "matched songs"

# Explicitly take a 25-second hook starting 40 seconds into a full song:
python tools/normalize_clips.py "full song.mp3" --start 40 --duration 25 --output "matched songs"

# Prepare a backing and give it the required two-digit filename prefix:
python tools/normalize_clips.py "beat.mp3" --kind backing --duration 16 --output "matched beats"
```

On Windows you can use `py` instead of `python`. If FFmpeg is not on PATH, add
`--ffmpeg "C:/ffmpeg/bin/ffmpeg.exe"` (substitute your own installation path).

The script matches **loudness**, rather than applying bass/treble EQ. It uses
[two-pass FFmpeg loudnorm](https://ffmpeg.org/ffmpeg-filters.html#loudnorm),
targeting **−16 LUFS**, **−1.5 dBTP**, with short edge fades. It converts the
selected excerpt to mono before measuring and remeasures the saved result.
A JSON report records actual output loudness and any failures/warnings.
An unusual clip may miss the target; the script reports this and returns a
nonzero exit status so it can be reviewed.

Originals are preserved, and existing output files are never overwritten.
Supported folder inputs: WAV, MP3, FLAC, OGG, Opus, M4A, AAC and AIFF. Folders
are not searched recursively. By design the helper accepts **1–60 seconds**
for either type; longer inputs require explicit `--start`/`--duration` selection.
It never silently truncates a full song. The helper's minimum exists because
very short clips cannot be measured reliably; it is not a backing-loop engine limit.

Upload the resulting song WAVs through the normal webpage. For backings, copy
`01_name.wav`, `02_name.wav`, etc. into `assets/backing_beats`,
`assets/house_beats`, `assets/punk_beats` or `assets/baby_raver_beats` while the
service is stopped, then restart it. The normal webpage does not upload remix
backings. Do not put the recording prompt among the numbered beat files.

Playback also applies the toy's own level processing and volume control,
so −16 LUFS describes the prepared file, not guaranteed speaker
loudness. Listen to the result before adding a whole collection.

## Other audio hardware

Without the PCB, a USB sound adapter is the easiest test. Skip step 5, run
`.venv/bin/python -m djtable --list-devices`, and set `output_device` to a unique part of
the adapter's name. For a USB microphone with a separate speaker output, set
`input_device`, `input_channels` (usually 1), `mic_channel: 0`, `independent_input: true`
and `capture_enabled: true`. Keep `sample_rate` at `48000`. A speaker-only build may use
the stock `dtoverlay=max98357a` from the
[Adafruit guide](https://learn.adafruit.com/adafruit-max98357-i2s-class-d-mono-amp/raspberry-pi-usage)
instead of step 5. Never enable two sound overlays.

## Maintenance and troubleshooting

- Stop audio before diagnostics: `sudo systemctl stop djtable`. Start it again afterwards.
- Silent stress test: `sudo -u djtable .venv/bin/python -m djtable.bench --mode house --seconds 30`.
- `status_blocks` and `dropped_commands` rising in the log mean missed audio deadlines or
  too much input, not a volume problem. Check `free -m` and `vcgencmd get_throttled`.
  Avoid asset generation, package installation or large uploads during play.
- Crackle when changing theme: confirm amp SD is wired to BCM4, check `free -m` (run
  `deploy/tune-pi.sh` if under about 100 MB available) and look for
  `Amp unmuted after …s mode switch` in the journal. `"mute_amp_on_switch": false` turns
  the mute off.
- Volume slider stuck or wrong: `grep serial0 /boot/firmware/cmdline.txt` must print
  nothing; rerun `deploy/install-duplex.sh` and reboot.
- Slow start: check `systemd-analyze blame` and the card speed (step 2). If
  `NetworkManager.service` takes over 10 s, run `deploy/native-wifi.sh` (step 8).
- Back up `config.json`, `data/` and custom `assets/` before updates; follow
  [UPDATING.md](UPDATING.md). Generated media and configuration are deliberately ignored by Git.
- Remove the services with `sudo systemctl disable --now djtable djtable-web`, delete their
  unit files from `/etc/systemd/system` and run `sudo systemctl daemon-reload`. Keep
  `/opt/PiDJTable` until its data is backed up.
