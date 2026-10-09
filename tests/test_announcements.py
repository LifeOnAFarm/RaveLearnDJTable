import sys
import types
import unittest
from contextlib import ExitStack
from types import SimpleNamespace

import numpy as np

from djtable.core import Engine, MODE_PIN
from djtable.instruments import build_pack
from test_mode_button import FakeButton

RATE = 16000
NAMES = ('theme_punk', 'theme_teenage_disco', 'mode_maker', 'mode_bluetooth', 'level_keyboard_2',
         'level_maker_3', 'bluetooth_connected', 'maker_all_deleted')


def engine():
    held, _ = build_pack(RATE)
    e = Engine(SimpleNamespace(instruments=held, sequences={}, songs=[]), rate=RATE, volume=1.0)
    e.announcements = {name: np.full(4000, i + 1, np.float32) for i, name in enumerate(NAMES)}
    e.maker = SimpleNamespace(busy=lambda: False, playing=False, position=0, jobs=[], state='idle', record_down=None,
                              song_down=None, song_held=False, clear_all_armed=False, click_voice=None,
                              finish=lambda: None, advance=lambda n: None, mix=lambda out, speed: None)
    return e


def step(e, *command):
    e.submit(*command)
    e.render(np.zeros((64, 2), np.float32))
    voice = e.voices.get('announcement')
    return None if voice is None else voice.parts[0][0]


class AnnouncementTests(unittest.TestCase):
    def test_level_mode_theme_and_bluetooth_events_speak(self):
        e = engine()
        self.assertEqual(step(e, 'level', 2), 5)               # Learning level 2 -> level_keyboard_2
        self.assertEqual(step(e, 'activity', 'maker'), 3)      # mode_maker
        self.assertEqual(step(e, 'level', 3), 6)               # Music Maker level 3
        step(e, 'activity', 'bluetooth')
        self.assertEqual(e.voices['announcement'].parts[0][0], 4)  # mode_bluetooth
        self.assertEqual(step(e, 'level', 1), 1)               # Bluetooth level 1 = Punk set
        self.assertEqual(step(e, 'announce', 'bluetooth_connected'), 7)

    def test_theme_change_and_missing_clips(self):
        e = engine()
        self.assertEqual(step(e, 'mode', 'punk', e.bank, None, ()), 1)
        e.voices.clear()
        self.assertIsNone(step(e, 'mode', 'house', e.bank, None, ()))  # No clip for House: silent.

    def test_same_level_is_not_announced_again(self):
        e = engine()
        step(e, 'level', 2)
        e.voices.clear()
        self.assertIsNone(step(e, 'level', 2))

    def test_announcement_plays_at_normal_speed_while_platter_bends(self):
        e = engine()
        e.announcements['level_keyboard_2'] = np.linspace(0, 1, 4000, dtype=np.float32)
        e.submit('platter', .9)
        step(e, 'level', 2)
        self.assertEqual(e.voices['announcement'].offset, 64)  # 64 frames consumed at speed 1.0

    def test_web_clear_all_in_music_maker(self):
        e = engine()
        e.maker.playing = True
        e.activity = 'maker'
        self.assertEqual(step(e, 'maker_action', 'clear'), 8)


class ModeButtonHoldTests(unittest.TestCase):
    def setUp(self):
        self._saved = sys.modules.get('gpiozero')
        sys.modules['gpiozero'] = types.SimpleNamespace(Button=FakeButton)
        FakeButton.pins = {}

    def tearDown(self):
        if self._saved is None:
            sys.modules.pop('gpiozero', None)
        else:
            sys.modules['gpiozero'] = self._saved

    def test_tap_changes_theme_on_release_and_hold_changes_mode(self):
        from djtable.__main__ import Controls
        engine_stub = SimpleNamespace(submit=lambda *command: True, activity='keyboard')
        with ExitStack() as stack:
            controls = Controls(stack, 30)
            button, t = FakeButton.pins[MODE_PIN], 0.0
            button.is_pressed = True
            while t < .2:
                controls.poll(t, engine_stub); t += .02
            self.assertEqual(controls.mode_presses, 0)  # Nothing yet: a tap acts on release.
            button.is_pressed = False
            for _ in range(3):
                controls.poll(t, engine_stub); t += .02
            self.assertEqual((controls.mode_presses, controls.activity_presses), (1, 0))
            button.is_pressed = True
            start = t
            while t < start + 5.2:
                controls.poll(t, engine_stub); t += .02
            self.assertEqual(controls.activity_presses, 1)  # Fires at 5 s, while still held.
            button.is_pressed = False
            for _ in range(3):
                controls.poll(t, engine_stub); t += .02
            self.assertEqual((controls.mode_presses, controls.activity_presses), (1, 1))  # No extra theme change.


if __name__ == '__main__':
    unittest.main()
