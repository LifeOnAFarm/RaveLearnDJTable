# Installation

This sets up the table exactly as it runs on the original: the PCB's MAX98357A speaker
amp and INMP441 microphone, the AS5600 platter, the mode button, Bluetooth mode and the
web pages. Build the hardware first: see the
[hardware guide](https://nastypieceof.work/raveandrepeat) and the
[PCB notes](../hardware/README.md), especially the hand-wired fixes.

You need a Raspberry Pi Zero 2 W, a fast microSD card (16 GB or more, marked A1 or A2)
and a computer on the same Wi-Fi network.

## 1. Prepare the SD card

In [Raspberry Pi Imager](https://www.raspberrypi.com/software/) choose **Raspberry Pi
Zero 2 W** → **Raspberry Pi OS Lite (64-bit)**. Before writing, open the settings and set:

- a **hostname**, for example `djtable` (give each table its own name);
- your **username and password**;
- your **Wi-Fi** network (2.4 GHz) and country;
- **SSH** on.

Put the card in the table, power it on and give it about two minutes for its first start.

## 2. Install

From your computer, log in:

```sh
ssh <your-user>@<hostname>.local
```

Then on the Pi:

```sh
sudo apt update
sudo apt install -y --no-upgrade git
sudo git clone https://github.com/LifeOnAFarm/RaveRepeatDJTable /opt/PiDJTable
cd /opt/PiDJTable
sudo sh deploy/install.sh
sudo reboot
```

The installer takes a few minutes, mostly downloading packages. It:

1. installs the packages it needs, without upgrading anything else;
2. sets up Python and the table's settings (`config.json`);
3. copies the table's sounds into place;
4. installs the table's services and starts them on every boot;
5. sets up the speaker and microphone, turns I2C on for the platter, and turns SPI and
   the serial console off, because their pins are used by the buttons and sliders;
6. installs Bluetooth mode. Bluetooth stays off until that mode is chosen.

## 3. Check the table

After the reboot, wait about half a minute, then open `http://<hostname>.local:8080`
and go to **Admin**:

1. Move each slider through all three positions and press every key, the NumPad, Record and
   the mode button. Each should show in the live readout.
2. Spin the platter. Its reading should move.
3. Play some keys at full volume. There should be no hum or crackle.
4. Tap the mode button to change theme: a moment of silence, then the new theme.
5. In Learning, press Record and leave a message. It plays back as a remix.

If something doesn't respond, see [Troubleshooting](#troubleshooting).

## 4. Wi-Fi fallback (optional)

If the table can't join a known network within 45 seconds, it can offer its own network,
**DJTable-Setup**, so you can give it a new one. Choose a password of 8 or more
characters:

```sh
cd /opt/PiDJTable
sudo sh deploy/install-hotspot.sh 'your-own-hotspot-password'
```

To use it, join **DJTable-Setup** and open `http://10.42.0.1:8080/wifi`.

## 5. Slim down the Pi (optional, strongly recommended)

> **The Zero 2 W has only about 415 MB of memory, and the table really needs it.**
> On a standard install the Pi's own background services use close to 100 MB. Then
> switching theme can crackle or stutter, and start-up is slow: about 33 seconds to the
> first sound instead of about 19.

```sh
cd /opt/PiDJTable
sudo sh deploy/tune-pi.sh
sudo reboot
```

It backs up everything it changes to `/var/backups/` first, then:

- turns off the desktop, printing, Bluetooth's always-on service (Bluetooth mode still
  works), VNC, network file sharing, the modem manager and automatic updates;
- turns off PipeWire (the table plays sound directly) and reduces graphics memory;
- makes start-up faster: no start-up RAM disk (only when the Pi can start without
  one), no boot-partition check, no rainbow screen;
- removes the unused Ethernet profile and moves your Wi-Fi to NetworkManager's own
  format. Your Wi-Fi password is copied, not changed.

SSH, Wi-Fi, `<hostname>.local` and the clock stay on.

If the Pi doesn't start after this, put the SD card in a computer, open `config.txt` on
the boot partition and change `auto_initramfs=0` back to `auto_initramfs=1`.

## Updating

```sh
cd /opt/PiDJTable
sudo git pull
sudo sh deploy/install.sh
sudo reboot
```

An update never touches your settings, sounds, songs or recordings, even when the
repository's own sounds change. Back up `config.json`, `assets/` and `data/` now and then anyway.

## Troubleshooting

- **See what the table is doing:** `journalctl -u djtable -n 50 --no-pager`.
  `Audio running` and `Mode/library ready` mean it started properly.
- **No sound:** `aplay -l` must list `snd_rpi_googlevoicehat_soundcar`. If not, run
  `sudo sh deploy/install-duplex.sh` from `/opt/PiDJTable` and reboot.
- **Volume slider wrong or stuck:** `grep serial0 /boot/firmware/cmdline.txt` must print
  nothing. If it does, rerun `sudo sh deploy/install-duplex.sh` and reboot.
- **Crackle when changing theme:** check that the amp's SD pin is wired to BCM4, and do
  step 5 if you haven't.
- **Platter does nothing:** Admin shows `Sensor unavailable` when the AS5600 isn't found.
  Check its wiring and the magnet. `ls /dev/i2c-1` must show the I2C bus.
- **Slow start:** a slow SD card costs several seconds. Measure it with
  `sudo dd if=/dev/mmcblk0 of=/dev/null bs=1M count=200 iflag=direct`. About 20 MB/s or
  more is good.
- **Restart the table:** `sudo systemctl restart djtable`. **Turn it off safely:**
  `sudo poweroff`.
