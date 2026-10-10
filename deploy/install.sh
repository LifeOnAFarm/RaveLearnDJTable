#!/bin/sh
# Install the whole table: packages, Python environment, starter sounds, services,
# the PCB sound overlay and pin settings, and Bluetooth mode.
# Run as root from /opt/PiDJTable:  sudo sh deploy/install.sh
# Safe to run again (for example after `git pull`): existing sounds, songs and
# config.json are kept. Does not upgrade packages. Reboot afterwards.
set -eu
test "$(id -u)" = 0 || { echo 'Run with sudo'; exit 1; }
test "$(pwd -P)" = /opt/PiDJTable || { echo 'Run from /opt/PiDJTable'; exit 1; }

echo '== 1/6 Packages'
apt-get update
DEBIAN_FRONTEND=noninteractive apt-get install -y --no-upgrade --no-remove \
    python3-venv python3-numpy python3-gpiozero python3-lgpio libportaudio2 \
    alsa-utils espeak-ng device-tree-compiler

echo '== 2/6 Python environment'
test -x .venv/bin/python || python3 -m venv --system-site-packages .venv
.venv/bin/pip install -q 'sounddevice>=0.5,<0.6'

echo '== 3/6 Settings and sounds (about 2 minutes the first time)'
test -f config.json || cp config.example.json config.json
# Included sounds (words, announcements, prompt, scratches) first; never replaces your own.
(cd sounds && find . -type f -name '*.wav') | while read -r sound; do
    test -e "assets/$sound" || install -D -m 644 "sounds/$sound" "assets/$sound"
done
# Then generate everything else (instruments, beats, drums); existing files are kept.
.venv/bin/python tools/bootstrap_assets.py

echo '== 4/6 Services'
sh deploy/install-services.sh
systemctl enable djtable djtable-web

echo '== 5/6 Speaker, microphone and pins'
sh deploy/install-duplex.sh

echo '== 6/6 Bluetooth mode'
DEBIAN_FRONTEND=noninteractive sh deploy/install-bluetooth.sh

echo
echo 'Installed. Reboot now: sudo reboot'
echo 'Then open http://<this-pi>:8080'
