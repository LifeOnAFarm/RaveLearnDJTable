from contextlib import ExitStack
import io
import json
import threading
from types import SimpleNamespace
import unittest
from unittest.mock import patch
from urllib.request import Request, urlopen
from urllib.error import HTTPError
from http.server import ThreadingHTTPServer
import wave

import numpy as np

from test_core import scratch_directory
from djtable.core import Engine, KEY_PINS, SLIDER_PINS
from djtable.__main__ import Controls, read_config
from djtable.library import Library, load_bank
from djtable.web import handler_for
from pathlib import Path


def wav_bytes(frames=160, rate=16000):
    out = io.BytesIO()
    with wave.open(out, 'wb') as wav:
        wav.setparams((1, 2, rate, 0, 'NONE', ''))
        wav.writeframes((np.ones(frames) * 4096).astype('<i2').tobytes())
    return out.getvalue()


class LibraryTests(unittest.TestCase):
    def test_upload_reorder_remove_restore_and_reload(self):
        with scratch_directory() as tmp:
            lib = Library(tmp)
            config = read_config(Path(__file__).resolve().parents[1] / 'config.json')
            initial = lib.stamp()
            lib.upload(wav_bytes(), '<a song>', 'song')
            state = lib.upload(wav_bytes(320), 'second', 'song')
            self.assertNotEqual(lib.stamp(), initial)
            names = [s['file'] for s in state['songs']]
            lib.change('order', list(reversed(names)))
            lib.upload(wav_bytes(), 'pink replacement', 'keys/piano/pink.wav')
            bank = load_bank(config, lib)
            self.assertEqual(len(bank.songs[0]), 960)
            self.assertEqual(len(bank.sequences['piano', 3, 'pink'][0]), 480)
            engine = Engine(bank)
            engine.submit('song')
            out = np.zeros((100, 2), dtype=np.float32)
            engine.render(out)
            self.assertGreater(float(out.max()), 0)
            lib.change('remove', names[0])
            lib.change('reset', 'keys/piano/pink.wav')
            self.assertEqual(len(lib.read()['songs']), 1)
            self.assertEqual(lib.read()['assignments'], {})
            self.assertFalse(lib.path(names[0]).exists())
            engine.submit('bank', load_bank(config, lib))
            engine.render(out)
            self.assertEqual(engine.song_index, -1)

    def test_bad_uploads_never_change_manifest(self):
        with scratch_directory() as tmp:
            lib = Library(tmp)
            lib.upload(wav_bytes(), 'valid')
            original = lib.manifest.read_bytes()
            for payload, slot in ((b'not wav', 'song'), (wav_bytes(), '../../config.json'), (wav_bytes(rate=96000), 'song')):
                with self.assertRaises(ValueError):
                    lib.upload(payload, 'invalid', slot)
                self.assertEqual(lib.manifest.read_bytes(), original)
            with self.assertRaises(ValueError):
                lib.path('../config.json')
            with self.assertRaises(ValueError):
                lib.change('order', [])

    def test_memory_budget_and_long_sample_rejected(self):
        with scratch_directory() as tmp:
            lib = Library(tmp)
            with self.assertRaises(ValueError):
                lib.upload(wav_bytes(16000 * 61), 'long')
            with patch('djtable.library.MAX_DECODED', 100):
                with self.assertRaises(ValueError):
                    lib.upload(wav_bytes(), 'too much memory')
            self.assertFalse(lib.manifest.exists())

    def test_http_upload_csrf_validation_and_audio_preview(self):
        with scratch_directory() as tmp:
            lib = Library(tmp)
            server = ThreadingHTTPServer(('127.0.0.1', 0), handler_for(lib, tmp))
            thread = threading.Thread(target=server.serve_forever, daemon=True)
            thread.start()
            base = f'http://127.0.0.1:{server.server_port}'
            try:
                with urlopen(base + '/api/library') as response:
                    state = json.load(response)
                with self.assertRaises(HTTPError) as err:
                    urlopen(Request(base + '/api/upload', data=wav_bytes()))
                self.assertEqual(err.exception.code, 403)
                headers = {'X-DJTable-CSRF': state['csrf'], 'Origin': base}
                word = Path(tmp) / 'symbols/ga/pink.wav'
                word.parent.mkdir(parents=True)
                word.write_bytes(wav_bytes())
                with urlopen(base + '/word/symbols/ga/pink.wav') as response:
                    self.assertEqual(response.read(), wav_bytes())
                with self.assertRaises(HTTPError):
                    urlopen(base + '/word/../config.json')

                with urlopen(Request(base + '/api/upload?title=Hello&slot=song', data=wav_bytes(), headers=headers)) as response:
                    state = json.load(response)
                with urlopen(base + '/audio/' + state['songs'][0]['file']) as response:
                    self.assertEqual(response.read(), wav_bytes())
                with self.assertRaises(HTTPError) as err:
                    urlopen(Request(base + '/api/upload', data=wav_bytes(), headers={**headers, 'Origin':'http://evil.example'}))
                self.assertEqual(err.exception.code, 403)
                with self.assertRaises(HTTPError):
                    urlopen(base + '/audio/../config.json')
            finally:
                server.shutdown()
                server.server_close()
                thread.join()


class ControlsTests(unittest.TestCase):
    def test_gpio_allocation_is_unique_and_preserves_audio_i2c(self):
        pins = list(KEY_PINS.values()) + [p for group in SLIDER_PINS.values() for p in group] + [10, 11, 2, 3, 4, 18, 19, 20, 21]
        self.assertEqual(len(pins), len(set(pins)))
        self.assertEqual(set(pins), set(range(2, 28)))

    def test_three_contacts_debounce_and_press_snapshots(self):
        class Button:
            def __init__(self, pin, **kwargs): self.is_pressed = False
            def __enter__(self): return self
            def __exit__(self, *args): pass
        with patch.dict('sys.modules', {'gpiozero': SimpleNamespace(Button=Button)}), ExitStack() as stack:
            controls = Controls(stack, 30)
            submitted = []
            engine = SimpleNamespace(submit=lambda *event: submitted.append(event) or True)
            controls.buttons['tone_3'].is_pressed = True
            controls.buttons['level_2'].is_pressed = True
            controls.buttons['volume_1'].is_pressed = True
            controls.buttons['pink'].is_pressed = True
            controls.poll(1, engine)
            self.assertEqual(submitted, [])
            controls.poll(1.031, engine)
            self.assertEqual(submitted, [('level', 2), ('volume', 1), ('key', 'pink', 'synth', 2)])
            controls.buttons['tone_2'].is_pressed = True
            controls.poll(2, engine)
            controls.poll(2.04, engine)
            self.assertEqual(controls.tone, 3)
            snapshot = controls.status()
            self.assertEqual([snapshot[n]['position'] for n in ('tone', 'level', 'volume')], [3, 2, 1])
            self.assertEqual(snapshot['tone']['grounded'], [2, 3])
            self.assertFalse(snapshot['tone']['valid'])
            self.assertTrue(snapshot['volume']['valid'])
            self.assertEqual(len(submitted), 3)


if __name__ == '__main__':
    unittest.main()
