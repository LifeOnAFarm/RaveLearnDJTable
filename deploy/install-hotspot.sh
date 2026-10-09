#!/bin/sh
# Optional Wi-Fi fallback: after 45 s without Wi-Fi, the Pi offers its own
# DJTable-Setup network so /wifi can join a new home network. Run as root
# from /opt/PiDJTable after install-services.sh. Requires NetworkManager.
#   sudo sh deploy/install-hotspot.sh 'choose-your-own-8-to-63-char-password'
set -eu
test "$(id -u)" = 0 || { echo 'Run with sudo'; exit 1; }
password=${1:-}
test ${#password} -ge 8 && test ${#password} -le 63 || { echo 'Give a hotspot password of 8-63 characters'; exit 1; }
command -v nmcli >/dev/null || { echo 'NetworkManager (nmcli) is required'; exit 1; }
install -m 0755 -o root -g root deploy/djtable-network.py /usr/local/lib/djtable-network.py
install -m 0644 deploy/djtable-network.service /etc/systemd/system/djtable-network.service
if ! nmcli -t -f NAME connection show | grep -qx DJTable-Hotspot; then
    nmcli connection add type wifi ifname wlan0 con-name DJTable-Hotspot autoconnect no \
        ssid DJTable-Setup 802-11-wireless.mode ap 802-11-wireless.band bg \
        ipv4.method shared wifi-sec.key-mgmt wpa-psk wifi-sec.psk "$password" >/dev/null
fi
systemctl daemon-reload
systemctl enable --now djtable-network
echo 'Hotspot fallback enabled (network DJTable-Setup, address 10.42.0.1).'
