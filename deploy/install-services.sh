#!/bin/sh
# Run as root from /opt/PiDJTable after following INSTALL.md.
# Does not install packages, change boot settings, enable a hotspot or start audio.
set -eu
test "$(id -u)" = 0
test "$(pwd -P)" = /opt/PiDJTable
test -x .venv/bin/python
test -f config.json
getent passwd djtable >/dev/null || useradd --system --user-group --no-create-home djtable
for group in audio gpio i2c spi; do
    getent group "$group" >/dev/null || { echo "Missing OS group: $group"; exit 1; }
    usermod -a -G "$group" djtable
done
install -d -o djtable -g djtable -m 0750 data
chown -R djtable:djtable data
# Source/config stay root owned; only the media library is writable by the service.
# Precompile: the service user cannot write a bytecode cache into root-owned source.
.venv/bin/python -m compileall -q djtable >/dev/null
chown -R root:root djtable tools deploy .venv assets
chmod -R a+rX,go-w djtable tools deploy .venv assets
chown root:djtable config.json
chmod 0640 config.json
install -m 0644 deploy/djtable.service /etc/systemd/system/djtable.service
install -m 0644 deploy/djtable-web.service /etc/systemd/system/djtable-web.service
systemctl daemon-reload
echo 'Services installed, not started. Follow INSTALL.md for checks and enabling.'
