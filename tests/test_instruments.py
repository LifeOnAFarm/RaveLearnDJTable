import unittest
from types import SimpleNamespace
from unittest.mock import patch
from contextlib import ExitStack
import numpy as np
from djtable.instruments import build_pack, InstrumentVoice, PENTATONIC
from djtable.core import Engine, Voice, COLOURS
from djtable.platter import Motion
from djtable.__main__ import Controls


class InstrumentTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.rate = 16000
        cls.held, cls.short = build_pack(cls.rate)

    def test_all_patches_hold_and_release_with_finite_audio(self):
        for key, patch in self.held.items():
            with self.subTest(key=key):
                voice = InstrumentVoice(patch)
                out = np.zeros(self.rate * 3, dtype=np.float32)
                self.assertTrue(voice.mix(out, 1.12))
                self.assertTrue(np.isfinite(out).all())
                self.assertGreater(float(np.sqrt(np.mean(out[-self.rate:]**2))), .01)
                self.assertLess(float(abs(out).max()), .61)
                voice.release()
                tail = np.zeros(self.rate, dtype=np.float32)
                self.assertFalse(voice.mix(tail, .89))
                self.assertLess(float(abs(tail[0]-out[-1])), .4)
                self.assertFalse(np.any(tail[-100:]))

    def test_pentatonic_frequency_and_silent_end_of_short_notes(self):
        for index, colour in enumerate(COLOURS):
            voice = InstrumentVoice(self.held['piano', colour])
            out = np.zeros(self.rate*2, dtype=np.float32)
            voice.mix(out)
            frequency = np.fft.rfftfreq(self.rate,1/self.rate)[abs(np.fft.rfft(out[-self.rate:])).argmax()]
            expected = 261.625565 * 2**(PENTATONIC[index]/12)
            self.assertLess(abs(frequency/expected-1), .025)
            for tone in ('piano','high','synth'):
                self.assertFalse(np.any(self.short[tone,colour][-100:]))

    def test_neutral_direct_mix_matches_interpolation_through_wrap_and_release(self):
        for tone in ('piano','high','synth'):
            direct=InstrumentVoice(self.held[tone,'pink'])
            reference=InstrumentVoice(self.held[tone,'pink'])
            for count in (512,16000,4096,700):
                a=np.full(count,.1,dtype=np.float32);b=a.copy()
                self.assertEqual(direct.mix(a),reference.mix(b,1+1e-14))
                np.testing.assert_allclose(a,b,atol=2e-6)
            direct.release();reference.release()
            for count in (512,512,4096,512):
                a=np.full(count,.1,dtype=np.float32);b=a.copy()
                self.assertEqual(direct.mix(a),reference.mix(b,1+1e-14))
                np.testing.assert_allclose(a,b,atol=2e-6)

    def test_release_events_end_only_held_instruments(self):
        bank = SimpleNamespace(instruments=self.held, sequences={('piano',1,'pink'):(np.ones(100)*.1,np.ones(100)*.2)}, songs=[])
        engine = Engine(bank,rate=self.rate,volume=1)
        block=np.zeros((512,2),dtype=np.float32)
        engine.submit('key','pink','high',3)
        engine.submit('key','blue','piano',3)
        engine.render(block)
        engine.submit('key_up','pink')
        for _ in range(15):engine.render(block)
        self.assertNotIn('pink',engine.voices)
        self.assertIn('blue',engine.voices)
        engine.submit('release_keys')
        for _ in range(15):engine.render(block)
        self.assertFalse(engine.voices)
        engine.submit('key','pink','piano',1)
        engine.submit('key_up','pink')
        engine.render(block[:20])
        self.assertIn('pink',engine.voices)

    def test_retrigger_fades_existing_bent_waveform_without_starting_release(self):
        bank=SimpleNamespace(instruments=self.held,sequences={},songs=[])
        engine=Engine(bank,rate=self.rate,volume=1)
        block=np.zeros((128,2),dtype=np.float32)
        engine.submit('key','pink','synth',3)
        engine.submit('platter',1)
        engine.render(block)
        previous=engine.voices['pink']
        old_offset=previous.offset
        engine.submit('key','pink','synth',3)
        engine.render(block)
        self.assertFalse(previous.released)
        self.assertEqual(previous.cross_remaining,0)
        self.assertGreater(previous.offset,old_offset+len(block))
        self.assertIsNot(engine.voices['pink'],previous)
        self.assertTrue(np.isfinite(block).all())
        engine.render(block)
        self.assertFalse(engine.retrigger_tails)

    def test_platter_preserves_spoken_words_and_changes_song_duration(self):
        voice=Voice((np.arange(8,dtype=np.float32), np.arange(10,dtype=np.float32)+20),learning=True,bend_note=True)
        out=np.zeros(14,dtype=np.float32)
        voice.mix(out,2)
        np.testing.assert_array_equal(out[:4],[0,2,4,6])
        np.testing.assert_array_equal(out[4:],np.arange(10)+20)
        song=Voice((np.ones(100),))
        self.assertFalse(song.mix(np.zeros(67),1.5))
        self.assertEqual(song.part,1)

    def test_prompt_ignores_platter_and_stale_input_returns_to_normal(self):
        engine=Engine(SimpleNamespace(songs=[]),rate=1000,volume=1,capture=True,record_prompt=np.ones(100)*.2)
        engine.submit('platter',1)
        engine.submit('record')
        engine.render(np.zeros((50,2),dtype=np.float32))
        self.assertEqual(engine.voices['prompt'].offset,50)
        engine.render(np.zeros((50,2),dtype=np.float32))
        self.assertEqual(engine.record_state,'recording')
        for _ in range(30):engine.render(np.zeros((50,2),dtype=np.float32))
        self.assertLess(abs(engine.platter_value),.001)

    def test_chords_are_bounded_without_hard_clipping(self):
        engine=Engine(SimpleNamespace(instruments=self.held,sequences={},songs=[]),rate=self.rate,volume=1)
        for colour in COLOURS:engine.submit('key',colour,'high',3)
        out=np.zeros((self.rate*2,2),dtype=np.float32)
        engine.render(out)
        self.assertLess(float(abs(out).max()),.981)
        self.assertTrue(np.isfinite(out).all())


class PlatterTests(unittest.TestCase):
    def test_wrap_direction_stop_jitter_and_disconnect(self):
        motion=Motion()
        self.assertEqual(motion.update(4090,0),0)
        self.assertGreater(motion.update(20,.02),0)
        self.assertLess(motion.update(4080,.04),0)
        for i in range(1,50):motion.update(4080+i%2,.04+i*.02)
        self.assertLess(abs(motion.value),.001)
        self.assertEqual(motion.update(None,2),0)
        self.assertEqual(motion.update(1000,3),0)
        self.assertEqual(motion.update(2000,4),0)

    def test_gpio_release_and_slider_change_release_held_keys(self):
        class Button:
            def __init__(self,*args,**kwargs):self.is_pressed=False
            def __enter__(self):return self
            def __exit__(self,*args):pass
        with patch.dict('sys.modules',{'gpiozero':SimpleNamespace(Button=Button)}),ExitStack() as stack:
            controls=Controls(stack,30)
            events=[]
            engine=SimpleNamespace(submit=lambda *args:events.append(args) or True)
            controls.buttons['level_3'].is_pressed=True
            controls.buttons['pink'].is_pressed=True
            controls.poll(1,engine);controls.poll(1.04,engine)
            self.assertIn(('key','pink','piano',3),events)
            controls.buttons['tone_2'].is_pressed=True
            controls.poll(2,engine);controls.poll(2.04,engine)
            self.assertIn(('release_keys',),events)
            controls.buttons['pink'].is_pressed=False
            controls.poll(3,engine);controls.poll(3.04,engine)
            self.assertEqual(events[-1],('key_up','pink'))
