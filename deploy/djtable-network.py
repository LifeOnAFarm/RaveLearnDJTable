#!/usr/bin/python3
"""Small root helper: NetworkManager fallback AP and bounded local Wi-Fi setup.

Installed root-owned outside the application. Only the djtable group can use
the Unix socket; the web server additionally checks same-origin and CSRF.
"""
import hashlib
import json
import os
from pathlib import Path
import socketserver
import subprocess
import threading
import time
import uuid

SOCKET = '/run/djtable-network/control.sock'
HOTSPOT = 'DJTable-Hotspot'
PROFILE_DIR = Path('/etc/NetworkManager/system-connections')
lock = threading.Lock()
state = {'mode': 'starting', 'connection': '', 'address': '', 'busy': False, 'error': None}


def nm(*args, timeout=12):
    result = subprocess.run(['/usr/bin/nmcli', '--wait', str(timeout), *args],
                            capture_output=True, text=True, timeout=timeout+3,
                            env={**os.environ, 'LC_ALL': 'C'})
    if result.returncode:
        raise RuntimeError('NetworkManager could not complete this operation')
    return result.stdout.strip()


def credentials(value):
    ssid, password = value.get('ssid'), value.get('password')
    if not isinstance(ssid, str) or not 1 <= len(ssid.encode('utf-8')) <= 32 or any(ord(c)<32 for c in ssid):
        raise ValueError('Enter a Wi-Fi name of 1–32 bytes')
    if not isinstance(password, str) or not 8 <= len(password) <= 63 or not all(32 <= ord(c) <= 126 for c in password):
        raise ValueError('Enter the WPA/WPA2 password (8–63 printable characters)')
    return ssid, hashlib.pbkdf2_hmac('sha1', password.encode(), ssid.encode(), 4096, 32).hex()


def refresh():
    connection = nm('-g', 'GENERAL.CONNECTION', 'device', 'show', 'wlan0')
    address = nm('-g', 'IP4.ADDRESS', 'device', 'show', 'wlan0').splitlines()
    connected = bool(address) and connection not in ('', '--')
    state.update(mode=('hotspot' if connection == HOTSPOT else 'wifi') if connected else 'offline',
                 connection=connection if connected else '', address=address[0].split('/')[0] if address else '')
    return connected


def hotspot():
    nm('connection', 'up', 'id', HOTSPOT, timeout=25)
    refresh()


def connect(ssid, psk):
    # Give the HTTP response time to reach the browser before changing radios.
    time.sleep(2)
    with lock:
        identifier = str(uuid.uuid4())
        path = PROFILE_DIR / ('djtable-' + identifier + '.nmconnection')
        try:
            encoded = ';'.join(str(b) for b in ssid.encode()) + ';'
            content = (f'[connection]\nid=DJTable-{identifier[:8]}\nuuid={identifier}\n'
                       'type=wifi\ninterface-name=wlan0\nautoconnect=false\n'
                       f'[wifi]\nmode=infrastructure\nssid={encoded}\nhidden=true\n'
                       f'[wifi-security]\nkey-mgmt=wpa-psk\npsk={psk}\n'
                       '[ipv4]\nmethod=auto\n[ipv6]\nmethod=auto\n')
            fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
            with os.fdopen(fd, 'w') as handle:
                handle.write(content)
            nm('connection', 'load', str(path))
            nm('connection', 'up', 'uuid', identifier, timeout=40)
            nm('connection', 'modify', 'uuid', identifier, 'connection.autoconnect', 'yes',
               'connection.autoconnect-priority', '10')
            state['error'] = None
            refresh()
        except (OSError, RuntimeError, subprocess.TimeoutExpired):
            state['error'] = 'Could not join that network. Check the name/password and use a 2.4 GHz network.'
            try:
                nm('connection', 'delete', 'uuid', identifier)
            except (RuntimeError, subprocess.TimeoutExpired):
                pass
            path.unlink(missing_ok=True)
            try:
                if not refresh():
                    hotspot()
            except (RuntimeError, subprocess.TimeoutExpired):
                pass
        finally:
            state['busy'] = False


def monitor():
    # Allow NetworkManager to try saved profiles at boot/restart first.
    offline_since = time.monotonic()
    while True:
        if lock.acquire(blocking=False):
            try:
                if not state['busy']:
                    if refresh():
                        offline_since = time.monotonic()
                    elif time.monotonic()-offline_since >= 45:
                        hotspot()
                        offline_since = time.monotonic()
            except (RuntimeError, subprocess.TimeoutExpired, OSError):
                state['error'] = 'Network service unavailable; retrying automatically'
            finally:
                lock.release()
        time.sleep(15)


class Handler(socketserver.StreamRequestHandler):
    def handle(self):
        self.connection.settimeout(3)
        try:
            raw = self.rfile.readline(4097)
            if len(raw) > 4096:
                raise ValueError('Request too large')
            value = json.loads(raw)
            if value.get('action') == 'status':
                result = dict(state)
            elif value.get('action') == 'connect':
                ssid, psk = credentials(value)
                if state['busy']:
                    raise ValueError('A connection attempt is already running')
                state.update(busy=True, error=None)
                threading.Thread(target=connect, args=(ssid, psk), daemon=True).start()
                result = {'accepted': True}
            else:
                raise ValueError('Unknown network action')
        except (ValueError, TypeError, AttributeError, OSError):
            result = {'error': 'Invalid request, or another connection attempt is running. Check the Wi-Fi name and password.'}
        self.wfile.write(json.dumps(result).encode()+b'\n')


if __name__ == '__main__':
    import grp
    Path(SOCKET).unlink(missing_ok=True)
    with socketserver.UnixStreamServer(SOCKET, Handler) as server:
        os.chown(SOCKET, 0, grp.getgrnam('djtable').gr_gid)
        os.chmod(SOCKET, 0o660)
        threading.Thread(target=monitor, daemon=True).start()
        server.serve_forever()
