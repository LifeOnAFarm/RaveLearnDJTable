from pathlib import Path
from types import SimpleNamespace
import unittest
from unittest.mock import patch

import numpy as np

from djtable.core import Engine, load_wav, save_wav_atomic
from djtable.remix import RemixStore, make_remix, level_clip
from test_core import scratch_directory


class RemixTests(unittest.TestCase):
    def test_prompt_capture_protected_and_keyboard_over_remix(self):
        bank = SimpleNamespace(sequences={('piano',3,'pink'):(np.ones(20,dtype=np.float32)*.2,)}, songs=[])
        engine = Engine(bank, rate=100, record_seconds=.1, volume=.5, capture=True,
                        record_prompt=np.ones(6, dtype=np.float32) * .2)
        output = np.zeros((4, 2), dtype=np.float32)
        inp = np.full((4, 2), .4, dtype=np.float32)
        engine.submit('record')
        engine.render(output, inp)
        self.assertEqual(engine.record_state, 'prompt')
        self.assertEqual(engine.record_frames, 0)
        engine.submit('record')  # Cannot restart prompt or stop recording early.
        engine.submit('key', 'pink', 'piano', 1)
        engine.render(output, inp)
        self.assertEqual(engine.record_state, 'recording')
        self.assertEqual(engine.record_frames, 0)
        for _ in range(3):
            engine.submit('record')
            engine.render(output, inp)
        self.assertEqual(engine.record_state, 'saving')
        self.assertEqual(engine.completed.popleft(), 10)
        np.testing.assert_allclose(engine.record_buffer, .4)
        np.testing.assert_array_equal(output, 0)
        remix = np.ones(10, dtype=np.float32) * .3
        engine.submit('remix_ready', remix, (remix,), 'test beat', None)
        engine.render(output, inp)
        self.assertEqual(engine.record_state, 'playing')
        engine.submit('key', 'pink', 'piano', 3)
        engine.render(output, inp)
        self.assertEqual(engine.record_state, 'playing')
        self.assertIn('remix', engine.voices)
        self.assertIn('pink', engine.voices)
        self.assertGreater(float(output.mean()), .1)
        engine.submit('song')
        engine.render(output)
        self.assertNotIn('remix', engine.voices)
        self.assertNotIn('song', engine.voices)

    def test_only_song_stops_remix(self):
        for command in ('song','record'):
            engine=Engine(SimpleNamespace(songs=[]),rate=100,capture=True,
                          record_prompt=np.ones(30)*.1)
            engine.record_state='saving'
            engine.submit('remix_ready',np.ones(100)*.2,(),'test',None)
            out=np.zeros((4,2),dtype=np.float32)
            engine.render(out)
            engine.submit(command)
            engine.render(out)
            self.assertEqual('remix' in engine.voices, command != 'song')
            self.assertEqual(engine.record_state,'idle' if command=='song' else 'playing')
            self.assertNotIn('song',engine.voices)

    def test_failure_unlocks_and_retains_previous_songs(self):
        saved = (np.ones(5),)
        engine = Engine(SimpleNamespace(songs=[]), saved_songs=saved)
        engine.record_state = 'saving'
        engine.submit('record_failed', 'silent microphone')
        engine.render(np.zeros((2, 2), dtype=np.float32))
        self.assertEqual(engine.record_state, 'idle')
        self.assertEqual(engine.record_error, 'silent microphone')
        self.assertIs(engine.saved_songs, saved)

    def test_pitch_repeats_duration_loop_and_peak(self):
        rate = 8000
        voice = .2 * np.sin(2 * np.pi * 300 * np.arange(3 * rate) / rate)
        result = make_remix(voice, np.zeros(rate // 2), rate)
        self.assertEqual(len(result), 16 * rate)
        self.assertTrue(np.isfinite(result).all())
        self.assertLessEqual(np.max(np.abs(result)), .95)
        for offset in (1, 4.5, 8, 11.5):
            segment = result[int((offset + .1) * rate):int((offset + 1.1) * rate)]
            frequency = np.fft.rfftfreq(len(segment), 1 / rate)[np.abs(np.fft.rfft(segment)).argmax()]
            self.assertAlmostEqual(frequency, 600, delta=2)
        self.assertFalse(np.any(result[:rate]))
        self.assertFalse(np.any(result[14 * rate:]))
        looped = make_remix(voice, np.full(rate // 2, .1), rate)
        self.assertGreater(float(looped[15 * rate:15 * rate + 100].mean()), .20)

    def test_clip_leveling_lifts_quiet_prompt_and_bounds_peaks(self):
        t = np.arange(8000) / 8000
        quiet = .04 * np.sin(2 * np.pi * 300 * t)
        result = level_clip(quiet)
        self.assertGreater(float(np.sqrt(np.mean(result**2))), .19)
        self.assertLessEqual(float(abs(level_clip(np.array([0., 10., -10.]))).max()), .95)
        np.testing.assert_array_equal(level_clip(np.zeros(100)), 0)

    def test_silence_rejected(self):
        with self.assertRaisesRegex(ValueError, 'silent'):
            make_remix(np.zeros(100), np.ones(100), 8000)

    def test_subsonic_rumble_and_faint_noise_do_not_become_saved_speech(self):
        rate = 8000
        time = np.arange(3 * rate) / rate
        rumble = .01 * np.sin(2 * np.pi * 5 * time)
        noise = np.random.default_rng(3).normal(0, .00003, len(time))
        with self.assertRaisesRegex(ValueError, 'too weak'):
            make_remix(rumble + noise, np.ones(rate), rate)

    def test_speech_survives_rumble_filter_and_repeated_processing(self):
        rate = 8000
        time = np.arange(3 * rate) / rate
        for frequency in (300, 600):
            recording = .1 * np.sin(2 * np.pi * 5 * time) + .02 * np.sin(2 * np.pi * frequency * time)
            result = make_remix(recording, np.zeros(rate), rate)
            segment = result[int(1.2*rate):int(2.2*rate)]
            power = abs(np.fft.rfft(segment)) ** 2
            frequencies = np.fft.rfftfreq(len(segment), 1/rate)
            self.assertAlmostEqual(frequencies[power.argmax()], frequency*2.0, delta=2)
            self.assertLess(power[frequencies < 100].sum()/power.sum(), .001)

    def test_quiet_microphone_gets_useful_gain_without_clipping(self):
        rate = 8000
        time = np.arange(3 * rate) / rate
        quiet_voice = .0003 * np.sin(2 * np.pi * 500 * time)
        result = make_remix(quiet_voice, np.zeros(rate), rate)
        speech = result[int(1.1*rate):int(2.1*rate)]
        self.assertGreater(float(np.sqrt(np.mean(speech**2))), .1)
        self.assertLessEqual(float(np.max(np.abs(result))), .95)

    def test_remixes_are_one_and_done(self):
        with scratch_directory() as root:
            root = Path(root)
            beats = root / 'beats'
            save_wav_atomic(beats / '01_beat.wav', np.ones(100) * .2, 8000)
            save_wav_atomic(beats / 'Voicemail Sound Effect.wav', np.ones(100) * .2, 8000)
            store = RemixStore(beats, root / 'saved', 8000)
            voice = np.concatenate([np.zeros(2000), np.sin(np.arange(4000) * .2) * .1, np.zeros(2000)])
            for _ in range(3):
                remix, songs, _, error = store.create(voice)
            self.assertEqual((songs, error), ((), None))
            self.assertEqual(len(remix), 16 * 8000)
            self.assertFalse(list((root / 'saved').glob('remix-*.wav')))  # Remixes are not kept.
            restarted = RemixStore(beats, root / 'saved', 8000)
            self.assertEqual(restarted.songs, ())
            with patch('djtable.remix.save_wav_atomic', side_effect=OSError('disk full')):
                with self.assertLogs(level='ERROR'):  # Only the dry diagnostic take is written.
                    remix, songs, _, error = store.create(voice)
            self.assertEqual(len(remix), 16 * 8000)  # Still plays from RAM.
            self.assertIsNone(error)

    def test_all_six_actual_backings_render(self):
        root = Path(__file__).resolve().parents[2] / 'backing_beats'
        if not root.exists():
            root = Path(__file__).resolve().parents[1] / 'assets/backing_beats'
        paths = sorted(root.glob('[0-9][0-9]_*.wav'))
        if not paths:
            self.skipTest('Optional backing pack absent; run tools/bootstrap_assets.py for integration check')
        self.assertEqual(len(paths), 6)
        rate = 48000
        voice = np.sin(np.arange(3 * rate) * 2 * np.pi * 300 / rate) * .15
        for path in paths:
            with self.subTest(beat=path.name):
                output = make_remix(voice, load_wav(path, rate), rate)
                self.assertEqual(len(output), 16 * rate)
                self.assertLessEqual(np.max(np.abs(output)), .950001)


if __name__ == '__main__':
    unittest.main()
