#!/bin/sh
# Convert Wi-Fi networks saved by Raspberry Pi Imager (netplan profiles, shown as
# "netplan-wlan0-<name>") into NetworkManager's own format. Debian's NetworkManager
# reruns netplan and reloads systemd at boot for every netplan profile (about 10 s
# on a Zero 2 W). Networks joined from the DJTable Wi-Fi page are already native.
# Run as root, over a working connection; reboot afterwards. The original files
# are backed up and the Wi-Fi password is copied file to file, never printed.
set -eu
test "$(id -u)" = 0 || { echo 'Run with sudo'; exit 1; }
runtime=/run/NetworkManager/system-connections
target=/etc/NetworkManager/system-connections
found=0
for profile in "$runtime"/netplan-wlan0-*.nmconnection; do
    [ -e "$profile" ] || continue
    grep -qx 'type=wifi' "$profile" || continue
    found=1
    name=$(sed -n 's/^id=netplan-wlan0-//p' "$profile")
    old_uuid=$(sed -n 's/^uuid=//p' "$profile")
    [ -n "$name" ] && [ -n "$old_uuid" ] || { echo "Skipped $profile: no name"; continue; }
    if nmcli -t -f NAME connection show | grep -qxF "$name"; then
        echo "Skipped $name: a connection with that name already exists"; continue
    fi
    yaml=$(grep -l "uuid: \"$old_uuid\"" /etc/netplan/*.yaml 2>/dev/null | head -n 1 || true)
    [ -n "$yaml" ] || { echo "Skipped $name: netplan file not found"; continue; }
    backup=/var/backups/djtable-wifi-$(date +%Y%m%d-%H%M%S)
    mkdir -p "$backup"
    cp -a "$yaml" "$profile" "$backup/"
    file="$target/djtable-$(printf %s "$name" | tr -c 'A-Za-z0-9_-' '_').nmconnection"
    NAME=$name UUID=$(cat /proc/sys/kernel/random/uuid) awk '
        /^id=/ { print "id=" ENVIRON["NAME"]; next }
        /^uuid=/ { print "uuid=" ENVIRON["UUID"]; next }
        { print }
        /^type=wifi$/ { print "autoconnect-priority=10"; print "interface-name=wlan0" }' "$profile" > "$file.new"
    chmod 600 "$file.new"
    mv "$file.new" "$file"
    nmcli connection load "$file"
    nmcli -t -f NAME connection show | grep -qxF "$name" || { rm -f "$file"; echo "Failed for $name; nothing removed"; exit 1; }
    rm "$yaml"
    echo "Converted $name (backup: $backup). Reboot to finish: sudo reboot"
done
[ "$found" = 1 ] || echo 'No netplan Wi-Fi profiles: nothing to do.'
