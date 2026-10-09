import unittest
from types import SimpleNamespace

import numpy as np

from djtable.core import Engine

RATE = 8000
SCRATCHES = tuple(np.full(400, i + 1, np.float32) for i in range(3))


def engine():
    e = Engine(SimpleNamespace(instruments={}, sequences={}, songs=[np.full(RATE * 5, .1, np.float32)]), rate=RATE, volume=1.0)
    e.scratch_samples = SCRATCHES
    return e


def spin(e, value):
    e.submit('platter', value)
    e.render(np.zeros((64, 2), np.float32))
    voice = e.voices.get('scratch')
    return None if voice is None else int(voice.parts[0][0])


class ScratchTests(unittest.TestCase):
    def test_spin_plays_a_scratch_and_must_slow_down_before_the_next(self):
        e = engine()
        self.assertIsNone(spin(e, .1))       # Below the trigger threshold.
        first = spin(e, .4)
        self.assertIn(first, (1, 2, 3))
        e.voices.clear()
        self.assertIsNone(spin(e, .5))       # Still spinning: no new scratch.
        spin(e, 0.0)                          # Slow down: re-armed.
        second = spin(e, -.4)                 # Either direction.
        self.assertIn(second, (1, 2, 3))
        self.assertNotEqual(first, second)    # Never the same one twice in a row.

    def test_only_in_learning_when_nothing_else_plays(self):
        for setup in ('maker', 'bluetooth', 'song', 'key', 'recording', 'no samples'):
            e = engine()
            if setup in ('maker', 'bluetooth'):
                e.activity = setup
            elif setup == 'song':
                e.submit('song')
            elif setup == 'key':
                e.voices['pink'] = SimpleNamespace(mix=lambda out, speed: True, learning=False)
            elif setup == 'recording':
                e.record_state = 'saving'
            else:
                e.scratch_samples = ()
            e.submit('platter', .6)
            while e.commands:
                e._command(e.commands.popleft())
            with self.subTest(setup=setup):
                self.assertNotIn('scratch', e.voices)

    def test_scratch_plays_at_normal_speed_while_the_platter_turns(self):
        e = engine()
        spin(e, .9)
        self.assertEqual(e.voices['scratch'].offset, 64)  # 64 frames at speed 1.0 despite the spin.


if __name__ == '__main__':
    unittest.main()
