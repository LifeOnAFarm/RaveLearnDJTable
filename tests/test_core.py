from pathlib import Path
from types import SimpleNamespace
from contextlib import contextmanager
import shutil
import uuid
import unittest
from unittest.mock import patch
import wave

import numpy as np

from djtable.core import Debouncer, Engine, SampleBank, load_wav, save_wav_atomic, slider_position
from djtable.__main__ import read_config


@contextmanager
def scratch_directory():
    # Inherit workspace permissions: Windows sandbox cannot reopen directories
    # created with TemporaryDirectory's restrictive 0700 DACL.
    root = Path(__file__).resolve().parents[1] / 'data'
    root.mkdir(exist_ok=True)
    path = root / ('test-' + uuid.uuid4().hex)
    path.mkdir()
    try:
        yield path
    finally:
        assert path.resolve().parent == root.resolve()
        shutil.rmtree(path)


class EngineTests(unittest.TestCase):
    def setUp(self):
        choice = patch('djtable.core.random.choice', side_effect=lambda choices: choices[0])
        choice.start()
        self.addCleanup(choice.stop)
        self.bank = SimpleNamespace(sequences={
            ('piano', 2, 'pink'): (np.full(3, .1), np.full(2, .2), np.full(2, .3)),
            ('synth', 3, 'blue'): (np.full(12, .4),),
        }, songs=[np.full(20, .6), np.full(20, .7)])
        self.bank.symbol_sequences = dict(self.bank.sequences)
        self.engine = Engine(self.bank, rate=10, volume=.5, record_seconds=.5, capture=True)

    def render(self, count, source=None):
        result = np.empty((count, 2), dtype=np.float32)
        self.engine.render(result, source)
        np.testing.assert_array_equal(result[:, 0], result[:, 1])
        return result[:, 0]

    def test_sequence_crosses_buffer_boundaries_without_gaps(self):
        self.engine.submit('key', 'pink', 'piano', 2)
        actual = np.concatenate([self.render(4), self.render(5)])
        np.testing.assert_allclose(actual, [.05] * 3 + [.1] * 2 + [.15] * 2 + [0, 0])

    def test_learning_key_replaces_previous_sequence(self):
        self.engine.submit('key', 'pink', 'piano', 2)
        self.engine.submit('key', 'blue', 'synth', 3)
        self.render(4)
        self.engine.submit('key', 'pink', 'piano', 2)
        np.testing.assert_allclose(self.render(3), [.05] * 3)

    def test_level_three_overlaps_and_represses_only_same_key(self):
        self.bank.sequences['piano', 3, 'pink'] = (np.full(12, .1),)
        self.engine.submit('key', 'pink', 'piano', 3)
        self.engine.submit('key', 'blue', 'synth', 3)
        np.testing.assert_allclose(self.render(3), [.25] * 3)
        self.engine.submit('key', 'pink', 'piano', 3)
        np.testing.assert_allclose(self.render(3), [.25] * 3)

    def test_two_learning_keys_in_one_block_only_newest_plays(self):
        self.bank.sequences['synth', 1, 'blue'] = (np.full(12, .4),)
        self.engine.submit('key', 'pink', 'piano', 2)
        self.engine.submit('key', 'blue', 'synth', 1)
        np.testing.assert_allclose(self.render(3), [.2] * 3)

    def test_note_only_key_cuts_off_old_colour_speech(self):
        self.engine.submit('key', 'pink', 'piano', 2)
        self.render(4)
        self.engine.submit('key', 'blue', 'synth', 3)
        np.testing.assert_allclose(self.render(3), [.2] * 3)

    def test_volume_switch_applies_to_active_voice(self):
        self.engine.submit('key', 'blue', 'synth', 3)
        self.engine.submit('volume', 1)
        np.testing.assert_allclose(self.render(2), [.07] * 2)
        self.engine.submit('volume', 2)
        np.testing.assert_allclose(self.render(2), [.13] * 2)
        self.engine.submit('volume', 3)
        np.testing.assert_allclose(self.render(2), [.2] * 2)

    def test_keyboard_over_song_and_song_button_toggles(self):
        self.engine.submit('song')
        self.render(2)
        first = self.engine.song_index
        song = self.engine.voices['song']
        self.engine.submit('key', 'pink', 'piano', 2)
        self.assertTrue(np.all(self.render(2) > .05))
        self.assertIs(self.engine.voices['song'], song)
        self.engine.submit('song')
        self.render(1)
        self.assertNotIn('song', self.engine.voices)
        self.assertIn('pink', self.engine.voices)
        self.engine.submit('song')
        self.render(1)
        self.assertNotEqual(self.engine.song_index, first)
        self.assertIn('song', self.engine.voices)

    def test_record_timeout_mutes_selects_left_slot_and_replays(self):
        self.engine.submit('song')
        self.engine.submit('song')  # Stop the song before starting capture.
        self.engine.submit('record')
        source = np.column_stack((np.arange(8) / 10, np.ones(8)))
        np.testing.assert_array_equal(self.render(8, source), 0)
        self.assertEqual(self.engine.record_state, 'saving')
        self.assertEqual(self.engine.completed.popleft(), 5)
        np.testing.assert_allclose(self.engine.record_buffer, np.arange(5) / 10)
        self.engine.submit('key', 'pink', 'piano', 2)
        np.testing.assert_array_equal(self.render(2), 0)
        self.engine.submit('record_saved')
        np.testing.assert_allclose(self.render(6), [0, .05, .1, .15, .2, 0])

    def test_second_press_stops_and_repeat_recording_clears_old_voice(self):
        self.engine.submit('record')
        self.render(2, np.full((2, 2), .4))
        self.engine.submit('record')
        self.render(2, np.zeros((2, 2)))
        self.assertEqual(self.engine.completed.popleft(), 2)
        self.engine.submit('record_saved')
        np.testing.assert_allclose(self.render(1), [.2])
        self.engine.submit('record')
        np.testing.assert_array_equal(self.render(2, np.full((2, 2), .6)), 0)
        self.assertEqual(self.engine.record_frames, 2)

    def test_output_only_record_does_not_mute_playback(self):
        self.engine.capture = False
        self.engine.submit('song')
        self.engine.submit('record')
        np.testing.assert_allclose(self.render(1), [.3])

    def test_volume_cap_and_bounded_queue(self):
        self.bank.sequences['piano', 2, 'pink'] = (np.full(10, 2),)
        self.engine.submit('key', 'pink', 'piano', 2)
        np.testing.assert_allclose(self.render(3), [.5] * 3)
        for _ in range(64):
            self.assertTrue(self.engine.submit('song'))
        self.assertFalse(self.engine.submit('song'))
        self.assertEqual(self.engine.dropped_commands, 1)


class InputAndFileTests(unittest.TestCase):
    def test_bounce_requires_full_stable_period(self):
        state = Debouncer(False)
        self.assertFalse(state.update(True, 1))
        self.assertFalse(state.update(False, 1.01))
        self.assertFalse(state.update(True, 1.02))
        self.assertFalse(state.update(True, 1.04))
        self.assertTrue(state.update(True, 1.051))
        self.assertFalse(state.update(True, 2))
        self.assertTrue(state.value)

    def test_slider_truth_table_and_invalid_transition(self):
        for raw, expected in [((True, False, False), 1), ((False, True, False), 2), ((False, False, True), 3)]:
            self.assertEqual(slider_position(raw, 2), expected)
        for raw in ((False, False, False), (True, True, False), (True, True, True)):
            self.assertEqual(slider_position(raw, 3), 3)

    def test_atomic_wav_roundtrip_and_actual_resampling(self):
        with scratch_directory() as temp:
            path = Path(temp) / 'capture.wav'
            data = np.sin(np.arange(1600) * 2 * np.pi * 400 / 16000).astype(np.float32) * .3
            save_wav_atomic(path, data, 16000)
            converted = load_wav(path, 48000)
            self.assertEqual(len(converted), 4800)
            np.testing.assert_allclose(converted[::3], data, atol=1 / 32768)
            save_wav_atomic(path, np.zeros(20), 48000)
            self.assertEqual(len(load_wav(path, 48000)), 20)
            self.assertEqual(list(Path(temp).glob('*.tmp')), [])

    def test_missing_words_skip_but_missing_note_is_silent(self):
        with scratch_directory() as temp:
            root = Path(temp)
            save_wav_atomic(root / 'keys/piano/pink.wav', np.ones(3) * .2, 16000)
            with self.assertLogs(level='WARNING'):
                bank = SampleBank(root, 48000)
            self.assertEqual(len(bank.sequences['piano', 2, 'pink']), 1)
            self.assertEqual(bank.sequences['piano', 2, 'blue'], ())
            self.assertEqual(len(bank.errors), 55)

    def test_unsupported_wav_rejected(self):
        with scratch_directory() as temp:
            path = Path(temp) / 'bad.wav'
            with wave.open(str(path), 'wb') as wav:
                wav.setparams((1, 1, 16000, 0, 'NONE', ''))
                wav.writeframes(b'\x80' * 10)
            with self.assertRaises(ValueError):
                load_wav(path, 48000)

    def test_real_asset_pack_and_configuration(self):
        config = read_config(Path(__file__).resolve().parents[1] / 'config.json')
        if not (config['sample_root'] / 'keys').exists():
            self.skipTest('Optional starter assets absent; run tools/bootstrap_assets.py')
        bank = SampleBank(config['sample_root'], config['sample_rate'])
        self.assertEqual(bank.errors, [])
        self.assertEqual(len(bank.sequences), 72)
        self.assertEqual(len(bank.sequences['piano', 2, 'pink']), 2)


if __name__ == '__main__':
    unittest.main()
