"""Read-only AS5600 angle input, isolated from GPIO and the audio callback.

Registers: ams AS5600 datasheet (STATUS 0x0B, RAW ANGLE 0x0C/0x0D).
No configuration or OTP writes; register pointer selection only.
"""
import math
import os
import threading
import time


class Motion:
    def __init__(self):
        self.previous = None
        self.when = None
        self.value = 0.0

    def update(self, angle, now):
        if angle is None:
            self.previous = self.when = None
            self.value = 0.0
            return self.value
        if self.previous is not None:
            dt = now - self.when
            if .001 <= dt <= .2:
                delta = (angle-self.previous+2048) % 4096 - 2048
                # Two counts of noise should not bend a stationary key.
                speed = 0 if abs(delta) <= 2 else delta / 4096 / dt
                target = max(-1.0, min(1.0, speed))
                self.value += (target-self.value) * (1-math.exp(-dt/.10))
            else:
                self.value = 0.0
        self.previous, self.when = angle, now
        return self.value


class Platter:
    def __init__(self, bus=1, direction=1):
        self.bus, self.direction = bus, direction
        self.snapshot = dict(connected=False, magnet=False, value=0.0, error='Checking sensor')
        self.stop = threading.Event()
        self.thread = threading.Thread(target=self._run, name='AS5600', daemon=True)

    def __enter__(self):
        self.thread.start()
        return self

    def __exit__(self, *args):
        self.stop.set()
        self.thread.join(timeout=2)

    def status(self):
        result = dict(self.snapshot)
        if time.monotonic()-result.get('sampled_at', 0) > .25:
            result.update(connected=False, value=0.0, error='Sensor unavailable')
        return result

    def _run(self):
        import fcntl
        motion = Motion()
        fd = None
        try:
            while not self.stop.is_set():
                delay = .02
                try:
                    if fd is None:
                        fd = os.open(f'/dev/i2c-{self.bus}', os.O_RDWR)
                        fcntl.ioctl(fd, 0x0703, 0x36)  # I2C_SLAVE, AS5600 address.
                    os.write(fd, b'\x0b')
                    raw = os.read(fd, 3)
                    if len(raw) != 3:
                        raise OSError('Short AS5600 read')
                    status, high, low = raw
                    magnet = bool(status & 0x20)
                    healthy = magnet and not status & 0x18
                    angle = ((high & 15) << 8) | low
                    now = time.monotonic()
                    value = motion.update(angle if healthy else None, now) * self.direction
                    error = None if healthy else ('No magnet detected' if not magnet else 'Adjust magnet distance')
                    self.snapshot = dict(connected=True, magnet=magnet, angle=angle, value=value,
                                         error=error, sampled_at=now)
                except OSError as exc:
                    motion.update(None, time.monotonic())
                    self.snapshot = dict(connected=False, magnet=False, value=0.0,
                                         error=f'AS5600 not available: {exc.strerror or str(exc)}', sampled_at=time.monotonic())
                    if fd is not None:
                        os.close(fd)
                        fd = None
                    delay = 1.0
                self.stop.wait(delay)
        finally:
            if fd is not None:
                os.close(fd)
