"""Persistent activity selection, independent of the music theme."""
import json
from pathlib import Path

from .library import atomic_json
from .settings import JsonReader

ACTIVITIES = {'keyboard': 'Learning', 'maker': 'Music Maker', 'bluetooth': 'Bluetooth'}


class Activities:
    def __init__(self, data_dir):
        self.path = Path(data_dir) / 'activity.json'
        self._selection = JsonReader(self.path)
        self._maker = JsonReader(self.path.with_name('maker_request.json'))

    def selected(self):
        try:
            value = self.validate(self._selection.read()['activity'])
            return 'maker' if value == 'voice' else value
        except (OSError, ValueError, KeyError, TypeError):
            return 'keyboard'

    @staticmethod
    def validate(value):
        if not isinstance(value, str) or value not in (*ACTIVITIES, 'voice'):
            raise ValueError('Choose Learning, Music Maker or Bluetooth')
        return value

    def select(self, value):
        atomic_json(self.path, {'activity': self.validate(value)})

    def maker_settings(self):
        try:
            value = self._maker.read()
            if not isinstance(value, dict): raise ValueError('Invalid settings')
            return {'quantize': True, **value}
        except (OSError, ValueError): return {'quantize': True}

    def maker_request(self, action=None, quantize=None):
        import uuid
        if action not in (None, 'clear', 'undo', 'toggle'): raise ValueError('Invalid Music Maker action')
        if quantize is not None and not isinstance(quantize, bool): raise ValueError('Timing correction must be true or false')
        value = self.maker_settings()
        if quantize is not None: value['quantize'] = quantize
        value.update(action=action, request=uuid.uuid4().hex)
        atomic_json(self.path.with_name('maker_request.json'), value)
        return value
