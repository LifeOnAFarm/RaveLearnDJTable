"""Bluetooth speaker mode: phone music in, mixed under the keyboard.

Two pieces, both outside the audio callback's critical work:
- BluetoothAudio reads the phone's A2DP stream (BlueALSA through arecord) on a
  thread and hands the callback drift-corrected mono blocks.
- BluetoothManager runs on its own thread: it turns Bluetooth on and off via
  the root helper, tracks the connected phone, forwards play/pause/next and
  asks main to return to Learning when nothing connects in time.
"""
from collections import deque
import json
import logging
import socket
import subprocess
import threading
import time

import numpy as np

SOCKET = '/run/djtable-bluetooth/control.sock'
WINDOW = 120.0  # Seconds to wait for a phone before returning to Learning.


def request(value, timeout=20):
    with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as client:
        client.settimeout(timeout)
        client.connect(SOCKET)
        client.sendall(json.dumps(value).encode() + b'\n')
        with client.makefile('rb') as stream:
            result = json.loads(stream.readline(16384) or b'{}')
    if result.get('error'):
        raise RuntimeError(result['error'])
    return result


class BluetoothAudio:
    """Ring buffer between the phone's clock and the I2S clock.

    The writer thread only advances `written`; the callback only advances
    `consumed`. Playback starts once `target` seconds are buffered and the
    read speed is nudged by at most 0.5% to hold that level, which absorbs
    clock drift without audible pitch change.
    """
    def __init__(self, rate=48000, target=.25, capacity=2.0, command=None):
        # 250 ms cushion: phone audio arrives in bursts when Wi-Fi shares the radio.
        # Delay does not matter for streamed music; gaps do.
        self.rate = rate
        self.target = round(rate * target)
        self.ring = np.zeros(round(rate * capacity), dtype=np.float32)
        self.written = self.consumed = 0
        self.fraction = 0.0
        self.primed = False
        self.underruns = 0
        self.command = command or ['arecord', '-q', '-D', 'plug:bluealsa', '-f', 'S16_LE', '-c', '2',
                                   '-r', str(rate), '-t', 'raw']
        self._process = None
        self._thread = None
        self._wanted = False
        self._steps = np.arange(4096, dtype=np.float64)

    # ---- writer side (reader thread) ----
    def push(self, samples):
        size = len(self.ring)
        if self.written - self.consumed + len(samples) > size:
            return  # Callback stalled; drop new audio rather than overwrite unread audio.
        start = self.written % size
        first = min(len(samples), size - start)
        self.ring[start:start + first] = samples[:first]
        self.ring[:len(samples) - first] = samples[first:]
        self.written += len(samples)

    def _run(self):
        while self._wanted:
            try:
                self._process = subprocess.Popen(self.command, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
                logging.info('Bluetooth audio: reading phone stream')
                remainder = b''
                while self._wanted:
                    data = self._process.stdout.read1(8192) if hasattr(self._process.stdout, 'read1') else self._process.stdout.read(8192)
                    if not data:
                        break
                    data = remainder + data
                    usable = len(data) - len(data) % 4  # Whole stereo PCM16 frames only.
                    remainder = data[usable:]
                    if usable:
                        frames = np.frombuffer(data[:usable], dtype='<i2').reshape(-1, 2)
                        self.push((frames[:, 0].astype(np.float32) + frames[:, 1]) * (.5 / 32768))
            except OSError as exc:
                logging.warning('Bluetooth audio reader: %s', exc)
            finally:
                process = self._process
                self._close()
                if self._wanted and process is not None:
                    message = process.stderr.read(400).decode(errors='replace').strip() if process.stderr else ''
                    logging.warning('Bluetooth audio stream ended (exit %s): %s', process.returncode, message or 'no message')
            if self._wanted:
                time.sleep(1)  # No stream yet (phone paused or still connecting); retry.

    def _close(self):
        process, self._process = self._process, None
        if process and process.poll() is None:
            process.terminate()
            try:
                process.wait(2)
            except subprocess.TimeoutExpired:
                process.kill()

    def start(self):
        if self._thread and self._thread.is_alive():
            return
        self._wanted = True
        self.written = self.consumed = 0
        self.primed = False
        self._thread = threading.Thread(target=self._run, name='bluetooth-audio', daemon=True)
        self._thread.start()

    def stop(self):
        self._wanted = False
        self._close()
        self.primed = False

    @property
    def running(self):
        return self._wanted

    # ---- reader side (audio callback) ----
    def ready(self):
        return self.primed or self.written - self.consumed >= self.target

    def read(self, out):
        """Add len(out) drift-corrected frames to out; False when nothing to play."""
        count = len(out)
        fill = self.written - self.consumed
        if not self.primed:
            if fill < self.target:
                return False
            self.primed = True
        if fill > 3 * self.target + count:  # Long stall: skip ahead instead of lagging behind.
            fill = self.target + count
            self.consumed, self.fraction = self.written - fill, 0.0
        ratio = 1.0 + float(np.clip((fill - self.target) / self.target * .01, -.005, .005))
        if fill < count * ratio + 2:
            self.primed = False
            self.underruns += 1
            return False
        steps = self._steps[:count] if count <= len(self._steps) else np.arange(count, dtype=np.float64)
        positions = self.fraction + steps * ratio
        whole = positions.astype(np.int64)
        weight = (positions - whole).astype(np.float32)
        size = len(self.ring)
        index = (self.consumed + whole) % size
        following = (index + 1) % size
        out += self.ring[index] * (1 - weight) + self.ring[following] * weight
        advance = self.fraction + count * ratio
        self.consumed += int(advance)
        self.fraction = advance - int(advance)
        return True


class BluetoothManager:
    """Owns the helper conversation; main only sets `wanted` and reads `status()`."""
    def __init__(self, audio, send=request, window=WINDOW, clock=time.monotonic):
        self.audio, self.send, self.window, self.clock = audio, send, window, clock
        self.wanted = False
        self.enabled = False
        self.device = None
        self.error = None
        self.waiting_since = None
        self.timed_out = False
        self.requests = deque()
        self._thread = None
        self._stop = threading.Event()

    def status(self):
        if not self.wanted:
            return {'state': 'off'}
        if self.error:
            return {'state': 'error', 'error': self.error}
        if self.device:
            return {'state': 'connected', 'device': self.device}
        if not self.enabled:
            return {'state': 'starting'}
        remaining = self.window - (self.clock() - self.waiting_since) if self.waiting_since is not None else self.window
        return {'state': 'waiting', 'name': 'DJTable', 'seconds_left': max(0, round(remaining))}

    def step(self):
        now = self.clock()
        if not self.wanted:
            if self.enabled:
                self.audio.stop()
                try:
                    self.send({'action': 'disable'})
                except (OSError, RuntimeError) as exc:
                    logging.warning('Bluetooth disable failed: %s', exc)
                self.enabled, self.device = False, None
            self.error, self.waiting_since, self.timed_out = None, None, False
            self.requests.clear()
            return
        try:
            if not self.enabled:
                self.send({'action': 'enable'})
                self.enabled, self.error, self.waiting_since = True, None, now
            device = self.send({'action': 'status'}).get('device')
            if device and not self.device:
                logging.info('Bluetooth: %s connected', device)
                self.audio.start()
            elif self.device and not device:
                logging.info('Bluetooth: %s disconnected', self.device)
                self.audio.stop()
                self.send({'action': 'visible'})  # Reopen the pairing window.
                self.waiting_since = now
            self.device = device
            while self.requests and self.device:
                self.send({'action': self.requests.popleft()})
            self.requests.clear()
        except (OSError, RuntimeError, ValueError) as exc:
            if self.error is None:
                logging.warning('Bluetooth: %s', exc)
                self.waiting_since = now
            self.error = str(exc) if isinstance(exc, RuntimeError) else 'Bluetooth is not available'
        if self.device:
            self.waiting_since = None
        elif self.waiting_since is not None:
            # Errors fall back sooner; a quiet two-minute window returns to Learning.
            limit = 10 if self.error else self.window
            if now - self.waiting_since >= limit:
                self.timed_out = True

    def _loop(self):
        while not self._stop.is_set():
            self.step()
            self._stop.wait(.25 if self.requests else 1.0)

    def start(self):
        self._thread = threading.Thread(target=self._loop, name='bluetooth-manager', daemon=True)
        self._thread.start()

    def close(self):
        self.wanted = False
        self._stop.set()
        if self._thread:
            self._thread.join(5)
        self.step()
