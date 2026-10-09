#!/bin/sh
# Install the shared-clock INMP441 + MAX98357A overlay (voiceHAT driver) and the
# interface settings the DJTable PCB needs. Run as root from /opt/PiDJTable.
#   - on-board audio off (dtparam=audio=off), never two sound overlays
#   - I2C on (AS5600 platter), SPI off (BCM 7-11 are switches)
#   - serial console and UART off (BCM 14/15 are the Volume slider)
# Safe to run again. Reboot afterwards, then follow INSTALL.md to enable capture.
set -eu
test "$(id -u)" = 0 || { echo 'Run with sudo'; exit 1; }
test -f deploy/djtable-duplex-overlay.dts
command -v dtc >/dev/null || { echo 'dtc missing: sudo apt install --no-upgrade device-tree-compiler'; exit 1; }
config=/boot/firmware/config.txt
cmdline=/boot/firmware/cmdline.txt
backup=/var/backups/djtable-duplex-$(date +%Y%m%d-%H%M%S)
mkdir -p "$backup"
cp -a "$config" "$cmdline" "$backup/"
dtc -@ -q -I dts -O dtb -o /boot/firmware/overlays/djtable-duplex.dtbo deploy/djtable-duplex-overlay.dts
chmod 644 /boot/firmware/overlays/djtable-duplex.dtbo
# Never stack two I2S sound overlays. Also removes the retired pixel overlay (BCM20)
# and the image's own dtparam=audio/i2c/spi/enable_uart lines, which are rewritten below.
sed -i -e '/^dtoverlay=max98357a/d' -e '/^dtoverlay=djtable-pixel/d' -e '/^dtoverlay=djtable-duplex/d' \
    -e '/^dtparam=audio=/d' -e '/^dtparam=i2c_arm=/d' -e '/^dtparam=spi=/d' -e '/^enable_uart=/d' \
    -e '/^# DJTable shared-clock INMP441 + MAX98357A$/d' "$config"
# [all] so the lines are not scoped to a preceding [pi5]/[cm4] section.
printf '[all]\n# DJTable shared-clock INMP441 + MAX98357A\ndtparam=audio=off\ndtparam=i2c_arm=on\ndtparam=spi=off\nenable_uart=0\ndtoverlay=djtable-duplex\n' >> "$config"
# Repeated runs leave consecutive [all] lines; keep one.
awk '!($0 == "[all]" && previous == "[all]") { print } { previous = $0 }' "$config" > "$config.new"
cat "$config.new" > "$config" && rm "$config.new"
# Raspberry Pi Imager adds a serial login console on BCM 14/15 (the Volume slider pins).
sed -i -e 's/console=serial0,[0-9]* *//' -e 's/console=ttyAMA0,[0-9]* *//' "$cmdline"
systemctl disable --now serial-getty@ttyS0.service serial-getty@ttyAMA0.service >/dev/null 2>&1 || true
# /dev/i2c-1 for the platter.
grep -qx 'i2c-dev' /etc/modules 2>/dev/null || echo 'i2c-dev' >> /etc/modules
echo "Installed. Backup: $backup. Reboot now: sudo reboot"
