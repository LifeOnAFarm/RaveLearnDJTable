import sys
import types
import unittest
from contextlib import ExitStack
from types import SimpleNamespace

import numpy as np

from djtable.bluetooth import BluetoothAudio, BluetoothManager
from djtable.core import Engine
from djtable.instruments import build_pack, InstrumentVoice
from test_mode_button import FakeButton

RATE = 16000


def tone(seconds, start=0):
    t = np.arange(start, start + round(RATE * seconds)) / RATE
    return (.5 * np.sin(2 * np.pi * 440 * t)).astype(np.float32)


class AudioBufferTests(unittest.TestCase):
    def test_waits_for_target_then_plays_continuously(self):
        audio = BluetoothAudio(RATE, target=.1)
        out = np.zeros(256, dtype=np.float32)
        audio.push(tone(.05))
        self.assertFalse(audio.read(out))  # Below the 100 ms target: stay silent.
        audio.push(tone(.2, start=round(RATE * .05)))
        played = []
        for _ in range(10):
            out[:] = 0
            self.assertTrue(audio.read(out))
            played.append(out.copy())
        joined = np.concatenate(played)
        # Smooth continuation of the same sine (no gaps or clicks between blocks).
        self.assertLess(np.max(np.abs(np.diff(joined))), .1)
        self.assertGreater(np.max(np.abs(joined)), .4)

    def test_drift_is_absorbed_without_unbounded_growth(self):
        audio = BluetoothAudio(RATE, target=.1)
        out = np.zeros(256, dtype=np.float32)
        position = 0
        for block in range(800):  # ~13 s; the phone runs 0.3% fast.
            chunk = round(256 * 1.003) + (1 if block % 3 == 0 else 0)
            audio.push(tone(chunk / RATE, start=position)); position += chunk
            out[:] = 0
            audio.read(out)
        fill = audio.written - audio.consumed
        self.assertLess(fill, 2 * audio.target)
        self.assertEqual(audio.underruns, 0)

    def test_underrun_returns_false_and_reprimes(self):
        audio = BluetoothAudio(RATE, target=.05)
        audio.push(tone(.06))
        out = np.zeros(512, dtype=np.float32)
        self.assertTrue(audio.read(out))
        self.assertFalse(audio.read(out))
        self.assertFalse(audio.primed)
        self.assertEqual(audio.underruns, 1)

    def test_overflow_drops_new_audio_instead_of_overwriting(self):
        audio = BluetoothAudio(RATE, target=.05, capacity=.1)
        audio.push(tone(.08))
        audio.push(tone(.08))  # Would exceed capacity; dropped.
        self.assertEqual(audio.written, round(RATE * .08))


class FakeAudio:
    def __init__(self):
        self.started = self.stopped = 0

    def start(self):
        self.started += 1

    def stop(self):
        self.stopped += 1


class ManagerTests(unittest.TestCase):
    def setUp(self):
        self.now, self.sent, self.device, self.fail = 0.0, [], None, False
        self.audio = FakeAudio()
        def send(value):
            if self.fail:
                raise OSError('no helper')
            self.sent.append(value['action'])
            return {'device': self.device} if value['action'] == 'status' else {}
        self.manager = BluetoothManager(self.audio, send=send, window=120, clock=lambda: self.now)

    def test_returns_to_learning_after_two_quiet_minutes(self):
        self.manager.wanted = True
        self.manager.step()
        self.assertEqual(self.sent[:2], ['enable', 'status'])
        self.assertEqual(self.manager.status()['state'], 'waiting')
        self.now = 119; self.manager.step()
        self.assertFalse(self.manager.timed_out)
        self.assertEqual(self.manager.status()['seconds_left'], 1)
        self.now = 120; self.manager.step()
        self.assertTrue(self.manager.timed_out)

    def test_connect_streams_and_forwards_buttons_then_reopens_on_disconnect(self):
        self.manager.wanted = True
        self.manager.step()
        self.device, self.now = 'Test phone', 30
        self.manager.requests.append('play_pause')
        self.manager.step()
        self.assertEqual(self.manager.status(), {'state': 'connected', 'device': 'Test phone'})
        self.assertEqual(self.audio.started, 1)
        self.assertIn('play_pause', self.sent)
        self.now = 500; self.manager.step()
        self.assertFalse(self.manager.timed_out)  # Connected time never counts.
        self.device = None; self.manager.step()
        self.assertEqual(self.audio.stopped, 1)
        self.assertEqual(self.sent[-1], 'visible')
        self.now = 619; self.manager.step()
        self.assertFalse(self.manager.timed_out)
        self.now = 620; self.manager.step()
        self.assertTrue(self.manager.timed_out)

    def test_leaving_the_mode_turns_bluetooth_off(self):
        self.manager.wanted = True
        self.manager.step()
        self.manager.wanted = False
        self.manager.step()
        self.assertEqual(self.sent[-1], 'disable')
        self.assertEqual(self.manager.status(), {'state': 'off'})

    def test_missing_helper_reports_error_and_falls_back_quickly(self):
        self.fail = True
        self.manager.wanted = True
        self.manager.step()
        self.assertEqual(self.manager.status()['state'], 'error')
        self.now = 10; self.manager.step()
        self.assertTrue(self.manager.timed_out)


class EngineTests(unittest.TestCase):
    def engine(self):
        held, _ = build_pack(RATE)
        engine = Engine(SimpleNamespace(instruments=held, sequences={}, songs=[np.ones(100, np.float32)]), rate=RATE, volume=1.0, capture=True)
        engine.bluetooth_instruments = {1: {('piano', 'pink'): 'punk'}, 2: {('piano', 'pink'): 'disco'}, 3: held}
        engine.submit('activity', 'bluetooth')
        engine.render(np.zeros((64, 2), np.float32))
        return engine, held

    def test_level_picks_the_instrument_set(self):
        engine, held = self.engine()
        engine.submit('key', 'pink', 'piano', 3)
        engine.render(np.zeros((64, 2), np.float32))
        self.assertIsInstance(engine.voices['pink'], InstrumentVoice)
        self.assertIs(engine.voices['pink'].patch, held['piano', 'pink'])

    def test_song_record_and_platter_do_nothing_in_bluetooth(self):
        engine, _ = self.engine()
        engine.saved_songs = (np.ones(100, np.float32),)
        for command in (('song',), ('record',), ('platter', 0.0), ('platter', .5)):
            engine.submit(*command)
        engine.render(np.zeros((64, 2), np.float32))
        self.assertEqual(engine.voices, {})
        self.assertEqual(engine.record_state, 'idle')

    def test_phone_audio_is_mixed_into_the_output(self):
        engine, _ = self.engine()
        engine.bluetooth_audio = audio = BluetoothAudio(RATE, target=.01)
        audio.push(tone(.1))
        out = np.zeros((256, 2), np.float32)
        engine.render(out)
        self.assertGreater(np.max(np.abs(out[:, 0])), .2)
        np.testing.assert_array_equal(out[:, 0], out[:, 1])


class SongButtonTests(unittest.TestCase):
    def setUp(self):
        self._saved = sys.modules.get('gpiozero')
        sys.modules['gpiozero'] = types.SimpleNamespace(Button=FakeButton)
        FakeButton.pins = {}

    def tearDown(self):
        if self._saved is None:
            sys.modules.pop('gpiozero', None)
        else:
            sys.modules['gpiozero'] = self._saved

    def press(self, controls, engine, pin, start, seconds):
        FakeButton.pins[pin].is_pressed = True
        t = start
        while t <= start + seconds:
            controls.poll(t, engine); t += .02
        FakeButton.pins[pin].is_pressed = False
        for step in range(3):
            controls.poll(t + step * .02, engine)
        return t + .1

    def test_tap_is_play_pause_hold_is_next_record_is_ignored(self):
        from djtable.__main__ import Controls
        sent = []
        engine = SimpleNamespace(submit=lambda *command: sent.append(command) or True, activity='bluetooth')
        with ExitStack() as stack:
            controls = Controls(stack, 30)
            t = self.press(controls, engine, 10, 0, .1)
            t = self.press(controls, engine, 10, t, 1.0)
            self.press(controls, engine, 11, t, .1)
        self.assertEqual(controls.bluetooth_requests, ['play_pause', 'next'])
        self.assertFalse([c for c in sent if c[0] in ('song', 'record', 'song_button', 'record_button')])


if __name__ == '__main__':
    unittest.main()
