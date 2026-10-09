import sys
import types
import unittest
from contextlib import ExitStack
from types import SimpleNamespace

from djtable.core import MODE_PIN


class FakeButton:
    pins = {}

    def __init__(self, pin, pull_up=True, bounce_time=None):
        self.pin, self.is_pressed = pin, False
        FakeButton.pins[pin] = self

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


class ModeButtonTests(unittest.TestCase):
    def setUp(self):
        self._saved = sys.modules.get('gpiozero')
        sys.modules['gpiozero'] = types.SimpleNamespace(Button=FakeButton)
        FakeButton.pins = {}

    def tearDown(self):
        if self._saved is None:
            sys.modules.pop('gpiozero', None)
        else:
            sys.modules['gpiozero'] = self._saved

    def test_debounced_presses_are_counted_once(self):
        from djtable.__main__ import Controls
        engine = SimpleNamespace(submit=lambda *command: True, activity='keyboard')
        with ExitStack() as stack:
            controls = Controls(stack, 30)
            button = FakeButton.pins[MODE_PIN]
            self.assertEqual(MODE_PIN, 0)
            now = 0.0
            for pressed in (True,) * 3 + (False,) * 3 + (True,) * 3 + (False,) * 3:
                button.is_pressed = pressed
                controls.poll(now, engine)
                now += 0.02  # Three 20 ms polls per state: seen for 40 ms, past the 30 ms debounce.
            self.assertEqual(controls.mode_presses, 2)
            self.assertEqual(controls.button_status(now)['last']['name'], 'mode')
            FakeButton.pins[10].is_pressed = True  # Song button, held for the hardware test.
            for step in range(3):
                controls.poll(now + step * .02, engine)
            status = controls.button_status(now + .05)
            self.assertEqual(status['held'], ['song'])
            self.assertEqual(status['last']['name'], 'song')
            FakeButton.pins[10].is_pressed = False
            for step in range(3):
                controls.poll(now + .06 + step * .02, engine)
            now += .2
            # A 10 ms bounce shorter than the debounce window is ignored.
            controls.mode_presses = 0
            button.is_pressed = True
            controls.poll(now, engine)
            button.is_pressed = False
            controls.poll(now + .01, engine)
            controls.poll(now + .1, engine)
            self.assertEqual(controls.mode_presses, 0)

    def test_slider_positions_follow_pcb_wiring(self):
        from djtable.__main__ import Controls
        engine = SimpleNamespace(submit=lambda *command: True, activity='keyboard')
        with ExitStack() as stack:
            controls = Controls(stack, 30)
            FakeButton.pins[7].is_pressed = True  # PCB: BCM7 is Tone position 1.
            FakeButton.pins[9].is_pressed = True  # PCB: BCM9 is Volume position 3.
            for step in range(3):
                controls.poll(step * .02, engine)
            self.assertEqual((controls.tone, controls.volume), (1, 3))
            self.assertEqual({name: s['pins'] for name, s in controls.status().items()},
                             {'tone': [7, 24, 23], 'level': [8, 26, 25], 'volume': [15, 14, 9]})



class DirectInputTests(unittest.TestCase):
    def test_lgpio_inputs_claim_pull_ups_read_ground_as_pressed_and_release(self):
        from djtable.__main__ import open_inputs
        log, levels = [], {5: 0, 6: 1}
        fake = types.SimpleNamespace(
            SET_PULL_UP=32,
            gpiochip_open=lambda n: log.append(('open', n)) or 7,
            gpio_claim_input=lambda chip, pin, flags: log.append(('claim', pin, flags)),
            gpio_read=lambda chip, pin: levels[pin],
            gpio_free=lambda chip, pin: log.append(('free', pin)),
            gpiochip_close=lambda chip: log.append(('close', chip)))
        saved = sys.modules.get('lgpio'); sys.modules['lgpio'] = fake
        try:
            with ExitStack() as stack:
                inputs = open_inputs(stack, {'pink': 5, 'red': 6})
                self.assertEqual((inputs['pink'].is_pressed, inputs['red'].is_pressed), (True, False))
                self.assertIn(('claim', 5, 32), log)
            self.assertEqual(log[-1], ('close', 7))
            self.assertIn(('free', 6), log)
        finally:
            if saved is None:
                sys.modules.pop('lgpio', None)
            else:
                sys.modules['lgpio'] = saved

if __name__ == '__main__':
    unittest.main()
