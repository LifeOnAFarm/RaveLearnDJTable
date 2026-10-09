"""Small JSON settings that refresh when an atomic file replacement changes it."""
import json
import threading
import uuid
from pathlib import Path


class WebControls:
    """Persistent slider requests, applied outside the audio callback."""
    def __init__(self, root):
        self.path = Path(root) / 'controls.json'
        self.reader = JsonReader(self.path)
        self.lock = threading.Lock()

    def read(self):
        return self.reader.read()

    def select(self, name, position):
        if name not in ('tone', 'level', 'volume') or type(position) is not int or position not in (1, 2, 3):
            raise ValueError('Choose tone, level or volume and a position from 1 to 3')
        from .library import atomic_json
        with self.lock:
            state = self.read()
            state[name] = dict(position=position, request=uuid.uuid4().hex)
            atomic_json(self.path, state)
        return state

class JsonReader:
    def __init__(self, path):
        self.path = Path(path)
        self.signature = None
        self.value = {}
        self.loaded = False
        self._lock = threading.Lock()

    def read(self):
        with self._lock:
            return self._read()

    def _read(self):
        try:
            stat = self.path.stat()
            signature = (stat.st_ino, stat.st_mtime_ns, stat.st_ctime_ns, stat.st_size)
        except OSError:
            signature = None
        if not self.loaded or signature != self.signature:
            try:
                if signature is None or signature[-1] > 65536: raise ValueError('Missing or oversized settings')
                value = json.loads(self.path.read_text(encoding='utf-8'))
                if not isinstance(value, dict): raise ValueError('Settings must be an object')
            except (OSError, ValueError): value = {}
            self.value, self.signature, self.loaded = value, signature, True
        return self.value.copy()  # Callers can update settings without mutating the cache.
