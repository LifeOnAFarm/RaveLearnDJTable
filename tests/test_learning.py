import unittest
from types import SimpleNamespace
from pathlib import Path
import numpy as np
from djtable.core import Engine, SampleBank, TONES, COLOURS, SYMBOLS, load_wav


class LearningTests(unittest.TestCase):
    def setUp(self):
        colour, symbol = {}, {}
        for tone in TONES:
            for level in (1, 2, 3):
                for key in COLOURS:
                    colour[tone, level, key] = (np.array([.1]), np.array([.2 if level == 1 else .3])) if level != 3 else (np.array([.1]),)
                    symbol[tone, level, key] = (np.array([.1]), np.array([.4 if level == 1 else .5])) if level != 3 else (np.array([.1]),)
        self.engine = Engine(SimpleNamespace(sequences=colour, symbol_sequences=symbol, songs=[np.array([.1])]), volume=.5)

    def press(self, key, level=1, tone='piano'):
        self.engine.submit('key', key, tone, level)
        out = np.empty((2, 2), np.float32)
        self.engine.render(out)
        return out[:, 0]

    def test_alternates_resets_on_different_key_and_preserves_language(self):
        for level, word, shape in ((1, .1, .2), (2, .15, .25)):
            self.engine.last_learning_key = None
            for expected in (word, shape, word, shape):
                np.testing.assert_allclose(self.press('pink', level), [.05, expected])
            np.testing.assert_allclose(self.press('blue', level), [.05, word])
            np.testing.assert_allclose(self.press('pink', level), [.05, word])

    def test_tone_and_volume_are_independent_and_note_only_resets(self):
        self.press('orange', 2)
        self.engine.submit('volume', 1)
        np.testing.assert_allclose(self.press('orange', 2, 'synth'), np.array([.05, .25]) * .35)
        self.press('orange', 3)
        np.testing.assert_allclose(self.press('orange', 1), np.array([.05, .1]) * .35)

    def test_song_resets_to_colour(self):
        self.press('red')
        self.engine.submit('song')
        np.testing.assert_allclose(self.press('red'), [.1, .1])
        self.assertFalse(self.engine.learning_symbol)

    def test_full_speech_pack_and_symbol_mapping(self):
        root = Path(__file__).resolve().parents[1] / 'assets/speech'
        files = list(root.rglob('*.wav'))
        if not files:
            self.skipTest('Optional speech pack absent; run tools/bootstrap_assets.py for integration check')
        self.assertEqual(len(files), 32)
        self.assertEqual(SYMBOLS['orange'], 'triangle')
        self.assertEqual(SYMBOLS['black'], 'diamond')
        for path in files:
            audio = load_wav(path, 48000)
            self.assertGreater(len(audio), 4800)
            self.assertLess(len(audio), 48000 * 5)
            self.assertGreater(np.max(np.abs(audio)), .03)
            self.assertLess(np.max(np.abs(audio)), 1)
