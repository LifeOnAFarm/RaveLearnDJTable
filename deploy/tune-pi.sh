#!/bin/sh
# Optional appliance tuning for a dedicated Pi Zero 2 W DJTable (415 MB usable RAM).
# Frees memory so large Learning themes load without audio underruns.
# Run as root. Backs up first; changes boot settings, so reboot afterwards.
# Does not install, upgrade or remove packages, and never touches networking.
set -eu
test "$(id -u)" = 0 || { echo 'Run with sudo'; exit 1; }
backup=/var/backups/djtable-tune-$(date +%Y%m%d-%H%M%S)
mkdir -p "$backup"
cp -a /boot/firmware/config.txt "$backup/config.txt"
cp -a /boot/firmware/cmdline.txt "$backup/cmdline.txt"
systemctl list-unit-files --state=enabled --no-legend > "$backup/enabled-units.txt"
systemctl get-default > "$backup/default.target"
echo "Backup: $backup"

# 1. Boot to the text console; a desktop session costs ~100 MB on this board.
systemctl set-default multi-user.target
systemctl disable lightdm.service >/dev/null 2>&1 || true

# 2. Services and timers a headless toy does not use. Missing units are skipped.
for unit in cups.service cups.socket cups.path accounts-daemon.service \
    bluetooth.service udisks2.service wayvnc-control.service glamor-test.service \
    rp1-test.service nfs-blkmap.service rpcbind.service rpcbind.socket \
    nfs-client.target ModemManager.service e2scrub_reap.service \
    apt-daily.timer apt-daily-upgrade.timer man-db.timer; do
    if systemctl list-unit-files "$unit" --no-legend 2>/dev/null | grep -q .; then
        systemctl disable --now "$unit" >/dev/null 2>&1 && echo "disabled $unit"
    fi
done
# Automatic apt runs start large background jobs during play; update manually.

# Faster boot: cloud-init only configures a Pi's very first boot (about 6 s each boot).
if [ -d /etc/cloud ] && [ ! -e /etc/cloud/cloud-init.disabled ]; then
    touch /etc/cloud/cloud-init.disabled && echo 'cloud-init disabled (delete /etc/cloud/cloud-init.disabled to undo)'
fi

# 3. DJTable opens ALSA directly; PipeWire is not used.
systemctl --global mask pipewire.socket pipewire-pulse.socket pipewire.service \
    pipewire-pulse.service wireplumber.service filter-chain.service >/dev/null 2>&1 \
    && echo 'masked PipeWire user units'

# 4. Graphics memory: no display is attached, 64 MB of CMA is ample.
if grep -qx 'dtoverlay=vc4-kms-v3d' /boot/firmware/config.txt; then
    sed -i 's/^dtoverlay=vc4-kms-v3d$/dtoverlay=vc4-kms-v3d,cma-64/' /boot/firmware/config.txt
    echo 'graphics CMA reservation set to 64 MB'
fi

# 5. Faster boot (about 13 s sooner to sound on a Zero 2 W, together with the steps above).
cp -a /etc/fstab "$backup/fstab"
# Skip the boot (FAT) partition check every boot; the root partition is still checked.
awk '$2 == "/boot/firmware" && $6 == "2" { $6 = "0" } { print }' /etc/fstab > /etc/fstab.djtable-new \
    && mv /etc/fstab.djtable-new /etc/fstab
# No initramfs, only when the SD card and ext4 drivers are built into the kernel.
modprobe configs 2>/dev/null || true
if zcat /proc/config.gz 2>/dev/null | grep -qx 'CONFIG_EXT4_FS=y' && zcat /proc/config.gz | grep -qx 'CONFIG_MMC_BLOCK=y'; then
    sed -i 's/^auto_initramfs=1$/auto_initramfs=0/' /boot/firmware/config.txt && echo 'initramfs disabled'
else
    echo 'initramfs kept: root filesystem drivers are modules on this kernel'
fi
grep -qx 'disable_splash=1' /boot/firmware/config.txt \
    || printf '\n[all]\n# DJTable fast boot\ndisable_splash=1\nboot_delay=0\n' >> /boot/firmware/config.txt
# Debian's NetworkManager regenerates netplan and reloads systemd for each netplan profile.
# The first-boot Ethernet profile is useless on a board without Ethernet (Zero 2 W).
if [ ! -e /sys/class/net/eth0 ] && nmcli -t -f NAME connection show 2>/dev/null | grep -qx netplan-eth0; then
    nmcli connection delete netplan-eth0 >/dev/null && echo 'removed unused netplan-eth0 profile'
fi

echo 'Done. Reboot now: sudo reboot'
echo "Undo: restore $backup/config.txt, re-enable units listed in $backup/enabled-units.txt,"
echo "      run 'systemctl --global unmask pipewire.socket pipewire-pulse.socket' and"
echo "      'systemctl set-default graphical.target' if you want the desktop back."
