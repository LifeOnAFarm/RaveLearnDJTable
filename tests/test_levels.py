import unittest
from types import SimpleNamespace

import numpy as np

from djtable.core import Engine
from djtable.instruments import build_pack
from djtable.remix import BEEP_HZ, remove_beep
from djtable.voice_instrument import level_take

RATE = 16000


def tone(hz, seconds, level):
    return (np.sin(2 * np.pi * hz * np.arange(round(RATE * seconds)) / RATE) * level).astype(np.float32)


class LevelTests(unittest.TestCase):
    def test_beep_is_notched_out_but_a_voice_band_tone_survives(self):
        beep = remove_beep(tone(BEEP_HZ, .5, .3), RATE)
        voice = remove_beep(tone(300, .5, .3), RATE)
        self.assertLess(np.sqrt(np.mean(beep[1000:-1000] ** 2)), .3 / np.sqrt(2) * .05)  # More than 26 dB down.
        self.assertGreater(np.sqrt(np.mean(voice[1000:-1000] ** 2)), .3 / np.sqrt(2) * .95)

    def test_music_does_not_dip_when_a_key_is_pressed(self):
        held, _ = build_pack(RATE)
        song = np.full(RATE * 3, .2, np.float32)
        engine = Engine(SimpleNamespace(instruments=held, sequences={}, songs=[song]), rate=RATE, volume=1.0)
        engine.submit('song')
        out = np.zeros((256, 2), np.float32); engine.render(out)
        before = float(np.mean(out[:, 0]))
        engine.voices['pink'] = SimpleNamespace(mix=lambda output, speed: True, learning=False)  # A silent "key".
        for _ in range(20):
            out = np.zeros((256, 2), np.float32); engine.render(out)
        self.assertAlmostEqual(float(np.mean(out[:, 0])), before, places=3)

    def test_quiet_saved_voice_takes_are_raised_on_load(self):
        quiet = tone(220, .5, .05)
        raised = level_take(quiet)
        self.assertAlmostEqual(float(np.sqrt(np.mean(raised ** 2))), .30, delta=.02)
        self.assertLessEqual(float(np.max(np.abs(raised))), .8)


if __name__ == '__main__':
    unittest.main()
