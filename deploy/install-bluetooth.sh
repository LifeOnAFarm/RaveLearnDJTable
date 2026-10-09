#!/bin/sh
# Bluetooth speaker mode: phone music plays through the table.
# Run as root from /opt/PiDJTable after install-services.sh. Installs BlueALSA
# (two packages, no upgrades) and keeps Bluetooth off until the mode is chosen.
set -eu
test "$(id -u)" = 0 || { echo 'Run with sudo'; exit 1; }
apt-get install -y --no-upgrade --no-install-recommends bluez bluez-alsa-utils python3-dbus python3-gi
# Bluetooth only runs in Bluetooth mode; the helper starts and stops it.
systemctl disable --now bluealsa-aplay.service bluealsa.service bluetooth.service 2>/dev/null || true
install -d /etc/systemd/system/bluealsa.service.d
install -m 0644 deploy/bluealsa-sink.conf /etc/systemd/system/bluealsa.service.d/djtable.conf
install -m 0755 -o root -g root deploy/djtable-bluetooth.py /usr/local/lib/djtable-bluetooth.py
install -m 0644 deploy/djtable-bluetooth.socket /etc/systemd/system/djtable-bluetooth.socket
install -m 0644 deploy/djtable-bluetooth.service /etc/systemd/system/djtable-bluetooth.service
systemctl daemon-reload
systemctl enable --now djtable-bluetooth.socket
echo 'Bluetooth mode installed. Choose Bluetooth on the Home page to pair a phone.'
