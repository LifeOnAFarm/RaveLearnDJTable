"""Read-only hardware telemetry shared via the service's RAM runtime directory."""
import json
from pathlib import Path
import time

STATUS_PATH = Path('/run/djtable/status.json')


def publish(sliders, master_volume, path=STATUS_PATH, recording=None, platter=None, keyboard=None, mode=None, activity=None, buttons=None, bluetooth=None):
    temporary = path.with_suffix('.tmp')
    temporary.write_text(json.dumps({'updated_at': time.time(), 'sliders': sliders,
                                     'master_volume': master_volume,
                                     'recording': recording, 'platter': platter, 'keyboard': keyboard, 'mode': mode,
                                     'activity': activity, 'buttons': buttons, 'bluetooth': bluetooth}), encoding='utf-8')
    temporary.replace(path)


def read_status(path=STATUS_PATH):
    try:
        data = json.loads(path.read_text(encoding='utf-8'))
        age = time.time() - data['updated_at']
        return dict(data, online=0 <= age < 4)
    except (OSError, ValueError, KeyError, TypeError):
        return {'online': False, 'sliders': {}}
