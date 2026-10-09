#!/usr/bin/python3
"""Root helper for DJTable's Bluetooth speaker mode (phone -> table, A2DP sink).

Socket-activated by djtable-bluetooth.socket: it starts when DJTable first asks
and exits once Bluetooth is off and idle, so it costs no memory outside the
mode. Only root and the djtable group can use the socket. Pairing is accepted
only while the table is visible (a two-minute window); paired phones are
trusted and may reconnect later.
Actions: enable, visible, status, play_pause, next, disable.
"""
import json
import os
import socket
import socketserver
import subprocess
import threading
import time
from pathlib import Path

import dbus
import dbus.mainloop.glib
import dbus.service
from gi.repository import GLib

NAME = 'DJTable'
WINDOW = 120
IDLE_EXIT = 60
AGENT_PATH = '/djtable/agent'
ADAPTER, DEVICE, PLAYER, PROPS = 'org.bluez.Adapter1', 'org.bluez.Device1', 'org.bluez.MediaPlayer1', 'org.freedesktop.DBus.Properties'
A2DP_SOURCE = '0000110a-0000-1000-8000-00805f9b34fb'  # The phone sends; the table is the sink.

dbus.mainloop.glib.DBusGMainLoop(set_as_default=True)
bus = dbus.SystemBus()
loop = GLib.MainLoop()
state = {'enabled': False, 'visible_until': 0.0, 'agent': None, 'last_request': time.monotonic()}


class Rejected(dbus.DBusException):
    _dbus_error_name = 'org.bluez.Error.Rejected'


def radio(blocked):
    """Soft-block or unblock the Bluetooth radio (rfkill), so it is fully off outside the mode."""
    for device in Path('/sys/class/rfkill').glob('rfkill*'):
        if (device / 'type').read_text().strip() == 'bluetooth':
            (device / 'soft').write_text('1' if blocked else '0')


def systemctl(*args):
    subprocess.run(['/usr/bin/systemctl', *args], check=True, timeout=30, capture_output=True)


def managed():
    return dbus.Interface(bus.get_object('org.bluez', '/'), 'org.freedesktop.DBus.ObjectManager').GetManagedObjects()


def props(path):
    return dbus.Interface(bus.get_object('org.bluez', path), PROPS)


def adapter():
    for path, interfaces in managed().items():
        if ADAPTER in interfaces:
            return path
    raise RuntimeError('No Bluetooth adapter found')


def visible():
    return time.monotonic() < state['visible_until']


class Agent(dbus.service.Object):
    """NoInputNoOutput: 'just works' pairing, accepted only while visible."""
    def check(self, device):
        known = props(device).Get(DEVICE, 'Paired') and props(device).Get(DEVICE, 'Trusted')
        if not (visible() or known):
            raise Rejected('Not accepting new phones right now')
        props(device).Set(DEVICE, 'Trusted', dbus.Boolean(True))

    @dbus.service.method('org.bluez.Agent1', in_signature='', out_signature='')
    def Release(self):
        pass

    @dbus.service.method('org.bluez.Agent1', in_signature='os', out_signature='')
    def AuthorizeService(self, device, uuid):
        self.check(device)

    @dbus.service.method('org.bluez.Agent1', in_signature='o', out_signature='')
    def RequestAuthorization(self, device):
        self.check(device)

    @dbus.service.method('org.bluez.Agent1', in_signature='ou', out_signature='')
    def RequestConfirmation(self, device, passkey):
        self.check(device)

    @dbus.service.method('org.bluez.Agent1', in_signature='o', out_signature='s')
    def RequestPinCode(self, device):
        self.check(device)
        return '0000'

    @dbus.service.method('org.bluez.Agent1', in_signature='o', out_signature='u')
    def RequestPasskey(self, device):
        self.check(device)
        return dbus.UInt32(0)

    @dbus.service.method('org.bluez.Agent1', in_signature='ouq', out_signature='')
    def DisplayPasskey(self, device, passkey, entered):
        pass

    @dbus.service.method('org.bluez.Agent1', in_signature='os', out_signature='')
    def DisplayPinCode(self, device, pincode):
        pass

    @dbus.service.method('org.bluez.Agent1', in_signature='', out_signature='')
    def Cancel(self):
        pass


def make_visible():
    path = adapter()
    p = props(path)
    p.Set(ADAPTER, 'Pairable', dbus.Boolean(True))
    p.Set(ADAPTER, 'DiscoverableTimeout', dbus.UInt32(WINDOW))
    p.Set(ADAPTER, 'Discoverable', dbus.Boolean(True))
    state['visible_until'] = time.monotonic() + WINDOW


def enable():
    if not state['enabled']:
        radio(blocked=False)
        systemctl('start', 'bluetooth.service')
        systemctl('start', 'bluealsa.service')
        deadline = time.monotonic() + 10
        while True:
            try:
                path = adapter()
                break
            except (dbus.DBusException, RuntimeError):
                if time.monotonic() > deadline:
                    raise RuntimeError('Bluetooth did not start')
                time.sleep(.3)
        p = props(path)
        for attempt in range(20):  # The adapter needs a moment after rfkill unblock.
            try:
                p.Set(ADAPTER, 'Powered', dbus.Boolean(True))
                break
            except dbus.DBusException:
                if attempt == 19:
                    raise
                time.sleep(.25)
        p.Set(ADAPTER, 'Alias', NAME)
        if state['agent'] is None:
            state['agent'] = Agent(bus, AGENT_PATH)
        manager = dbus.Interface(bus.get_object('org.bluez', '/org/bluez'), 'org.bluez.AgentManager1')
        try:
            manager.RegisterAgent(AGENT_PATH, 'NoInputNoOutput')
        except dbus.DBusException:
            pass  # Already registered after a restart of this helper.
        manager.RequestDefaultAgent(AGENT_PATH)
        state['enabled'] = True
    make_visible()
    return {}


def connected():
    for path, interfaces in managed().items():
        device = interfaces.get(DEVICE)
        if device and device.get('Connected') and A2DP_SOURCE in [str(u).lower() for u in device.get('UUIDs', [])]:
            return path, str(device.get('Alias') or device.get('Name') or 'Phone')
    return None, None


def player():
    path, _ = connected()
    if path:
        for object_path, interfaces in managed().items():
            if PLAYER in interfaces and object_path.startswith(path + '/'):
                return object_path, interfaces[PLAYER]
    raise RuntimeError('The phone is not sharing playback controls')


def status():
    if not state['enabled']:
        return {'enabled': False}
    _, name = connected()
    return {'enabled': True, 'device': name, 'visible': visible()}


def play_pause():
    path, info = player()
    method = 'Pause' if str(info.get('Status')) == 'playing' else 'Play'
    getattr(dbus.Interface(bus.get_object('org.bluez', path), PLAYER), method)()
    return {}


def next_track():
    path, _ = player()
    dbus.Interface(bus.get_object('org.bluez', path), PLAYER).Next()
    return {}


def disable():
    if state['enabled']:
        try:
            for path, interfaces in managed().items():
                if interfaces.get(DEVICE, {}).get('Connected'):
                    dbus.Interface(bus.get_object('org.bluez', path), DEVICE).Disconnect()
            p = props(adapter())
            p.Set(ADAPTER, 'Discoverable', dbus.Boolean(False))
            p.Set(ADAPTER, 'Powered', dbus.Boolean(False))
        except (dbus.DBusException, RuntimeError):
            pass  # Stopping the services below still turns the radio off.
        state['enabled'], state['visible_until'] = False, 0.0
    for unit in ('bluealsa.service', 'bluetooth.service'):
        subprocess.run(['/usr/bin/systemctl', 'stop', unit], timeout=30, capture_output=True)
    radio(blocked=True)
    return {}


ACTIONS = {'enable': enable, 'visible': make_visible, 'status': status, 'play_pause': play_pause,
           'next': next_track, 'disable': disable}


def in_loop(function):
    """Run D-Bus work on the GLib thread and wait for its result."""
    done, box = threading.Event(), {}
    def call():
        try:
            box['value'] = function() or {}
        except (dbus.DBusException, RuntimeError, subprocess.SubprocessError, OSError) as exc:
            text = f'{exc.get_dbus_name()}: {exc.get_dbus_message()}' if isinstance(exc, dbus.DBusException) else str(exc)
            print('Bluetooth helper:', function.__name__, text, flush=True)
            box['value'] = {'error': text or type(exc).__name__}
        done.set()
        return False
    GLib.idle_add(call)
    if not done.wait(45):
        return {'error': 'Bluetooth helper timed out'}
    return box['value']


class Handler(socketserver.StreamRequestHandler):
    def handle(self):
        state['last_request'] = time.monotonic()
        try:
            action = json.loads(self.rfile.readline(4096)).get('action')
            result = in_loop(ACTIONS[action]) if action in ACTIONS else {'error': 'Unknown action'}
        except (ValueError, AttributeError):
            result = {'error': 'Bad request'}
        self.wfile.write(json.dumps(result).encode() + b'\n')


class Server(socketserver.ThreadingMixIn, socketserver.UnixStreamServer):
    daemon_threads = True


def idle_check():
    if not state['enabled'] and time.monotonic() - state['last_request'] > IDLE_EXIT:
        loop.quit()  # Socket activation restarts the helper on the next request.
        return False
    return True


def main():
    if os.environ.get('LISTEN_PID') != str(os.getpid()) or os.environ.get('LISTEN_FDS') != '1':
        raise SystemExit('Start through djtable-bluetooth.socket')
    server = Server('/run/djtable-bluetooth/control.sock', Handler, bind_and_activate=False)
    server.socket = socket.socket(fileno=3)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    GLib.timeout_add_seconds(10, idle_check)
    try:
        loop.run()
    finally:
        server.shutdown()


if __name__ == '__main__':
    main()
