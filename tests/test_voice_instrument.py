import json
from http.server import ThreadingHTTPServer
from pathlib import Path
import threading
from types import SimpleNamespace
import unittest
from unittest.mock import patch
from urllib.error import HTTPError
from urllib.request import Request, urlopen

import numpy as np

from djtable.voice_instrument import CAPTURE_SECONDS

from djtable.activities import Activities
from djtable.core import COLOURS, Engine, TONES
from djtable.instruments import PENTATONIC, InstrumentVoice
from djtable.library import Library
from djtable.voice_instrument import VoiceInstrumentStore, VOICE_TONES, build_voice_patches, prepare_take, voice_character
from djtable.web import handler_for
from test_core import scratch_directory

RATE = 16000


def recording():
    t = np.arange(round(RATE*.8)) / RATE
    sound = .12*np.sin(2*np.pi*220*t) + .02*np.sin(2*np.pi*440*t)
    return np.concatenate((np.zeros(round(RATE*.2)), sound, np.zeros(round(RATE*.5)))).astype(np.float32)


class VoiceInstrumentTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.take = prepare_take(recording(), RATE)
        cls.patches = build_voice_patches(cls.take, RATE)

    def engine(self, prompt=True):
        sequences = {(tone, level, colour): (np.full(16000, .1, dtype=np.float32),)
                     for tone in TONES for level in (1, 2, 3) for colour in COLOURS}
        bank = SimpleNamespace(sequences=sequences, symbol_sequences=sequences,
                               songs=[np.full(RATE*3, .05, dtype=np.float32)])
        result = Engine(bank, RATE, volume=1, record_seconds=3, capture=True,
                        record_prompt=np.ones(128, dtype=np.float32)*.1 if prompt else None)
        result.voice_patches = self.patches
        return result

    def render(self, engine, count=128, microphone=None):
        output = np.zeros((count, 2), dtype=np.float32)
        engine.render(output, microphone)
        self.assertTrue(np.isfinite(output).all())
        self.assertLessEqual(float(np.abs(output).max()), 1)
        return output

    def test_trims_silence_levels_sound_and_rejects_invalid_takes(self):
        self.assertLess(len(self.take), len(recording()))
        self.assertGreater(len(self.take), .7*RATE)
        self.assertLessEqual(float(abs(self.take).max()), .651)
        self.assertEqual(float(self.take[0]), 0)
        self.assertEqual(float(self.take[-1]), 0)
        for invalid in (np.zeros(RATE), np.ones(RATE), np.full(RATE, np.nan), np.zeros(RATE*2)):
            with self.subTest(invalid=invalid[:2]), self.assertRaises(ValueError):
                prepare_take(invalid, RATE)

    def test_eight_relative_pitches_and_small_memory_budget(self):
        total = 0
        for (tone, colour), voice in self.patches.items():
            semitone = PENTATONIC[COLOURS.index(colour)]
            base = self.patches[tone, 'pink']
            reference = np.fft.rfftfreq(base.loop_end, 1/RATE)[np.argmax(abs(np.fft.rfft(base.data[:base.loop_end])))]
            sound = voice.data[:voice.loop_end]
            frequency = np.fft.rfftfreq(len(sound), 1/RATE)[np.argmax(abs(np.fft.rfft(sound)))]
            self.assertAlmostEqual(frequency, reference*2**(semitone/12), delta=6)
            total += voice.data.nbytes + voice.resample_data.nbytes
        self.assertEqual(len(self.patches), 24)
        self.assertLess(total, 8*1024*1024)

    def test_hold_bend_and_release_have_finite_bounded_output(self):
        for patch_value in self.patches.values():
            voice = InstrumentVoice(patch_value)
            for _ in range(100):
                output = np.zeros(512, dtype=np.float32)
                self.assertTrue(voice.mix(output, 2**(2/12)))
                self.assertTrue(np.isfinite(output).all())
                self.assertLessEqual(float(abs(output).max()), .651)
            voice.release()
            self.assertFalse(voice.mix(np.zeros(RATE, dtype=np.float32)))

    def test_atomic_persistence_and_failed_take_keeps_previous(self):
        with scratch_directory() as root:
            store = VoiceInstrumentStore(root, RATE)
            self.assertEqual(store.load(), ({}, 0))
            patches, seconds = store.create(recording())
            saved = store.path.read_bytes()
            with self.assertRaises(ValueError):
                store.create(np.zeros(RATE))
            self.assertEqual(saved, store.path.read_bytes())
            loaded, duration = VoiceInstrumentStore(root, RATE).load()
            self.assertEqual(set(loaded), set(patches))
            self.assertEqual(seconds, duration)
            np.testing.assert_allclose(loaded['piano', 'pink'].data, patches['piano', 'pink'].data, atol=1/32768)
            with patch('djtable.voice_instrument.save_wav_atomic', side_effect=OSError('disk full')):
                with self.assertRaises(OSError):
                    store.create(recording())
            self.assertEqual(saved, store.path.read_bytes())

    def test_voice_activity_keeps_learning_and_background_music(self):
        engine = self.engine()
        engine.submit('activity', 'voice')
        engine.submit('song')
        engine.submit('key', 'pink', 'piano', 3)
        self.render(engine)
        self.assertIsInstance(engine.voices['pink'], InstrumentVoice)
        self.assertIn('song', engine.voices)
        engine.submit('song')
        self.render(engine)
        self.assertNotIn('song', engine.voices)
        self.assertIn('pink', engine.voices)
        engine.submit('key', 'red', 'synth', 1)
        self.render(engine)
        self.assertTrue(engine.voices['red'].learning)
        engine.submit('key', 'red', 'synth', 2)
        self.render(engine)
        self.assertTrue(engine.learning_symbol)

    def test_capture_kind_and_length_are_frozen_and_switches_wait(self):
        engine = self.engine()
        engine.submit('activity', 'voice')
        engine.submit('level', 3)
        engine.submit('record')
        self.render(engine)
        self.assertEqual(engine.record_state, 'recording')
        self.assertEqual(engine.record_kind, 'voice')
        self.assertEqual(engine.record_limit, round(RATE*CAPTURE_SECONDS))
        engine.submit('activity', 'keyboard')
        engine.submit('level', 1)
        engine.submit('record')
        engine.submit('key', 'pink', 'synth', 3)
        self.render(engine, 128, np.ones((128, 1), dtype=np.float32))
        self.assertEqual(engine.activity, 'voice')
        self.assertEqual(engine.record_kind, 'voice')
        self.assertFalse(engine.voices)
        remaining = engine.record_limit-engine.record_frames
        self.render(engine, remaining, np.ones((remaining, 1), dtype=np.float32))
        self.assertEqual(engine.completed.popleft(), round(RATE*CAPTURE_SECONDS))
        self.assertEqual(engine.record_state, 'saving')
        engine.submit('voice_ready', self.patches, .8)
        self.render(engine)
        self.assertEqual(engine.record_state, 'playing')
        self.assertIn('voice_preview', engine.voices)
        self.assertNotIn('remix', engine.voices)
        self.render(engine, RATE*2)
        self.assertEqual(engine.record_state, 'idle')
        self.assertFalse(engine.voices)
        engine.submit('activity', 'keyboard')
        engine.submit('record')
        self.render(engine)
        self.assertEqual(engine.record_kind, 'remix')
        self.assertEqual(engine.record_limit, RATE*3)

    def test_levels_one_and_two_record_remixes_in_voice_activity(self):
        for level in (1, 2):
            engine = self.engine()
            engine.submit('activity', 'voice')
            engine.submit('level', level)
            engine.submit('record')
            self.render(engine)
            self.assertEqual(engine.record_kind, 'remix')
            self.assertEqual(engine.record_limit, RATE*3)

    def test_missing_or_failed_voice_never_replaces_working_take(self):
        engine = self.engine()
        engine.voice_patches = {}
        engine.submit('activity', 'voice')
        engine.submit('key', 'pink', 'piano', 3)
        self.assertFalse(self.render(engine).any())
        self.assertIn('Press Record', engine.voice_error)
        engine.voice_patches = self.patches
        engine.record_state, engine.record_kind = 'saving', 'voice'
        engine.submit('record_failed', 'quiet microphone')
        self.render(engine)
        self.assertIs(engine.voice_patches, self.patches)
        self.assertEqual(engine.record_state, 'idle')

    def test_theme_change_and_activity_switch_preserve_voice_and_music(self):
        engine = self.engine()
        engine.submit('activity', 'voice')
        engine.submit('song')
        engine.submit('key', 'pink', 'piano', 3)
        self.render(engine)
        engine.submit('activity', 'keyboard')
        self.render(engine)
        self.assertIn('song', engine.voices)
        self.assertTrue(engine.voices['pink'].released)
        engine.submit('mode', 'house', engine.bank, engine.record_prompt, ())
        self.render(engine)
        self.assertIs(engine.voice_patches, self.patches)

    def test_activity_web_api_checks_token_and_persists_independent_selection(self):
        with scratch_directory() as root:
            library = Library(root/'library')
            activities = Activities(root)
            server = ThreadingHTTPServer(('127.0.0.1', 0), handler_for(library))
            thread = threading.Thread(target=server.serve_forever)
            thread.start()
            base = f'http://127.0.0.1:{server.server_port}'
            try:
                with urlopen(base+'/api/activities') as response:
                    data = json.load(response)
                self.assertEqual(data['selected'], 'keyboard')
                def select(value, token):
                    req = Request(base+'/api/activity', data=json.dumps({'activity': value}).encode(),
                                  headers={'X-DJTable-CSRF': token}, method='POST')
                    with urlopen(req) as response:
                        return json.load(response)
                with self.assertRaises(HTTPError):
                    select('voice', 'bad')
                self.assertEqual(select('maker', data['csrf'])['selected'], 'maker')
                self.assertEqual(Activities(root).selected(), 'maker')
                with self.assertRaises(HTTPError):
                    select('invalid', data['csrf'])
                self.assertEqual(activities.selected(), 'maker')
                with urlopen(base+'/') as response:
                    self.assertIn('activity-select', response.read().decode())
            finally:
                server.shutdown(); server.server_close(); thread.join()

    def test_each_tone_chooses_its_voice_character(self):
        engine = self.engine()
        engine.submit('activity', 'voice')
        for tone in TONES:
            engine.submit('key', 'pink', tone, 3)
            self.render(engine)
            self.assertIs(engine.voices['pink'].patch, self.patches[tone, 'pink'])
        self.assertEqual(self.patches['high', 'pink'].loop_end, self.patches['piano', 'pink'].loop_end)
        self.assertGreater(self.patches['synth', 'pink'].loop_end, self.patches['piano', 'pink'].loop_end)

    def test_characters_change_waveform_even_before_pitch_or_speed(self):
        normal = voice_character(self.take, RATE, 'piano')
        robot = voice_character(self.take, RATE, 'high')
        monster = voice_character(self.take, RATE, 'synth')
        np.testing.assert_array_equal(normal, self.take)
        for changed in (robot, monster):
            self.assertEqual(len(changed), len(normal))
            self.assertLess(abs(float(np.corrcoef(normal, changed)[0,1])), .9)
            self.assertLessEqual(float(np.max(np.abs(changed))), .651)
            self.assertGreater(float(np.sqrt(np.mean(changed*changed))), .05)
        self.assertLess(abs(float(np.corrcoef(robot, monster)[0,1])), .9)

    def test_success_previews_once_at_original_pitch_and_song_can_stop_it(self):
        engine = self.engine()
        engine.record_state, engine.record_kind = 'saving', 'voice'
        engine.submit('voice_ready', self.patches, .8)
        engine.submit('platter', 1)
        output = self.render(engine)
        np.testing.assert_allclose(output[:, 0], self.patches['piano', 'pink'].data[:len(output)])
        self.assertTrue(engine.recording_status()['preview'])
        self.assertEqual(engine.saved_songs, ())
        engine.submit('key', 'pink', 'high', 3)
        self.render(engine)
        self.assertIn('voice_preview', engine.voices)
        engine.submit('song')
        self.render(engine)
        self.assertNotIn('voice_preview', engine.voices)
        self.assertNotIn('song', engine.voices)
        self.assertIn('pink', engine.voices)
        self.assertEqual(engine.record_state, 'idle')

    def test_capture_begins_in_callback_after_complete_prompt_and_beep(self):
        engine = self.engine()
        engine.record_prompt = np.array([.2, .2, .2, .2, 0, 0], dtype=np.float32)
        engine.submit('activity', 'voice')
        engine.submit('level', 3)
        engine.submit('record')
        self.render(engine, 4, np.ones((4, 1), dtype=np.float32))
        self.assertEqual(engine.record_frames, 0)
        self.assertEqual(engine.record_state, 'prompt')
        self.render(engine, 4, np.ones((4, 1), dtype=np.float32))
        self.assertEqual(engine.record_frames, 0)
        self.assertEqual(engine.record_state, 'recording')
        self.render(engine, 4, np.full((4, 1), .3, dtype=np.float32))
        np.testing.assert_allclose(engine.record_buffer[:4], .3)
        self.assertEqual(engine.record_frames, 4)


class SoftEndingTests(unittest.TestCase):
    def test_soft_word_ending_survives_the_trim(self):
        from djtable.voice_instrument import prepare_take
        rate = 16000
        rng = np.random.default_rng(0)
        loud = np.sin(np.arange(round(rate * .3)) * 2 * np.pi * 220 / rate) * .3          # "ye-"
        soft = rng.standard_normal(round(rate * .25)) * .3 * 10 ** (-26 / 20) * .7          # "...s", 26 dB quieter
        silence = np.zeros(round(rate * .2))
        take = prepare_take(np.concatenate([silence, loud, soft, silence]), rate)
        self.assertGreater(len(take), round(rate * (.3 + .2)))  # Most of the soft ending is kept.
