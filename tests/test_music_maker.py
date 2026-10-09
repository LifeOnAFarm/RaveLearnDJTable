import unittest
import json
from types import SimpleNamespace
from unittest.mock import patch
import numpy as np
from test_core import scratch_directory
from djtable.music_maker import LoopSession, LayerStore, MakerBank, render_layer
from djtable.instruments import build_pack
from djtable.core import Engine, SampleBank, save_wav_atomic, Voice

class MusicMakerTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.rate=8000
        cls.bank=MakerBank(cls.rate,build_pack(cls.rate,'teenage_disco',prepared=False)[0])

    def tick(self,session,frames):
        for i in range(0,frames,80): session.advance(min(80,frames-i))

    def test_tap_voice_and_hold_countin_then_bounded_capture(self):
        s=LoopSession(self.rate,self.bank)
        s.button('record',True,3,{})
        self.tick(s,1600)
        self.assertTrue(s.button('record',False,3,{}))
        s.button('record',True,1,{})
        self.tick(s,3500)
        self.assertEqual(s.state,'counting')
        self.tick(s,16080)
        self.assertEqual(s.state,'capturing')
        s.event(True,'pink','piano')
        self.tick(s,64080)
        self.assertEqual(s.state,'preparing')
        self.assertEqual(len(s.jobs),1)
        self.assertFalse(s.button('record',False,1,{}))

    def test_empty_take_does_not_replace_and_level_stop_releases(self):
        s=LoopSession(self.rate,self.bank)
        s.state='capturing';s.clock=800;s.start=0
        s.finish()
        self.assertFalse(s.jobs)
        s.state='capturing';s.event(True,'pink','piano');s.finish()
        self.assertTrue(any(not e[1] and e[2]=='pink' for e in s.jobs[0][1][1]))

    def test_song_tap_and_clear_only_on_release(self):
        s=LoopSession(self.rate,self.bank)
        s.button('song',True,2,{})
        self.tick(s,800)
        s.button('song',False,2,{})
        self.assertTrue(s.playing)
        s.button('song',True,2,{})
        self.tick(s,20000)
        self.assertFalse(s.jobs)
        self.assertTrue(s.song_held)
        s.button('song',False,3,{})
        self.assertEqual(list(s.jobs),[('clear_layer',2)])
        self.assertTrue(s.playing)

    def test_five_second_hold_clears_all_without_intermediate_clear(self):
        s=LoopSession(self.rate,self.bank)
        s.playing=True
        s.button('song',True,1,{})
        self.tick(s,self.rate*5+80)
        self.assertTrue(s.clear_all_armed)
        self.assertFalse(s.jobs)
        s.button('song',False,1,{})
        self.assertEqual(list(s.jobs),[('clear',None)])
        self.assertFalse(s.playing)
        self.assertEqual(s.position,0)
        self.assertFalse(s.clear_all_armed)

    def test_layer_clear_preserves_other_layers_and_undo_restores(self):
        with scratch_directory() as root:
            store=LayerStore(root,self.rate)
            data=np.full(self.rate*8,.2,dtype=np.float32)
            store.apply('save',(1,data));store.apply('save',(2,data))
            self.assertEqual(set(store.apply('clear_layer',1)),{2})
            self.assertEqual(set(store.apply('clear_layer',1)),{2})
            self.assertEqual(set(store.apply('undo')),{1,2})

    def test_shared_phase_speed_and_recording_mutes_replaced_layer(self):
        s=LoopSession(self.rate,self.bank)
        track=(np.sin(np.arange(self.rate*8)*.02)*10000).astype('<i2')
        s.set_tracks({1:track,2:track})
        s.playing=True
        out=np.zeros(80,dtype=np.float32)
        s.mix(out,1.5)
        self.assertEqual(s.position,120)
        s.state='capturing';s.record_level=1;s.position=0
        out.fill(0);s.mix(out,1.5)
        self.assertEqual(s.position,80)
        np.testing.assert_allclose(out,track[:80]/32768*.65,atol=1e-6)

    def test_render_layer_has_duration_drums_and_quantize(self):
        request=(1,((321,True,'pink','piano'),(1200,False,'pink','')),{},True)
        level,out=render_layer(request,self.bank,self.rate)
        self.assertEqual(level,1);self.assertEqual(len(out),self.rate*8)
        self.assertTrue(out.any());self.assertTrue(np.isfinite(out).all())
        self.assertGreater(np.max(np.abs(out)),.05)
        _,drum=render_layer((2,((0,True,'pink','piano'),),{},False),self.bank,self.rate)
        self.assertGreater(np.max(np.abs(drum)),.1)
        self.assertFalse(drum[self.rate:].any())

    def test_atomic_save_restart_replace_undo_clear(self):
        with scratch_directory() as root:
            store=LayerStore(root,self.rate)
            a=np.full(self.rate*8,.2,dtype=np.float32)
            b=np.full(self.rate*8,.3,dtype=np.float32)
            store.apply('save',(1,a));store.apply('save',(2,b))
            restart=LayerStore(root,self.rate)
            self.assertEqual(set(restart.load()),{1,2})
            restart.apply('save',(1,b))
            tracks=restart.apply('undo')
            self.assertAlmostEqual(tracks[1][0]/32768,.2,places=3)
            self.assertEqual(set(tracks),{1,2})
            self.assertEqual(restart.apply('clear'),{})
            self.assertEqual(set(restart.apply('undo')),{1,2})

    def test_failed_manifest_keeps_previous_layers(self):
        with scratch_directory() as root:
            store=LayerStore(root,self.rate)
            a=np.full(self.rate*8,.2,dtype=np.float32)
            store.apply('save',(1,a))
            with patch('djtable.music_maker.atomic_json',side_effect=OSError('disk full')):
                with self.assertRaises(OSError):store.apply('save',(2,a))
            self.assertEqual(set(store.load()),{1})

    def test_combined_loop_matches_individual_layers_at_speed_and_wrap(self):
        s=LoopSession(self.rate,self.bank)
        tracks={i:(np.sin(np.arange(s.length)*(.01*i))*10000).astype('<i2') for i in (1,2,3)}
        s.set_tracks(tracks);s.playing=True
        for speed in (1,.65,1.5):
            s.position=s.length-10.25
            positions=(np.arange(128)*speed+s.position)%s.length
            expected=sum(np.interp(positions,np.arange(s.length+1),np.append(v.astype(float)/32768,v[0]/32768))*.65 for v in tracks.values())
            output=np.zeros(128,dtype=np.float32);s.mix(output,speed)
            np.testing.assert_allclose(output,expected,atol=2e-6)

    def test_quantize_keeps_short_held_notes_audible(self):
        class ShortVoice:
            released=False
            def release(self):self.released=True
            def mix(self,out,speed):
                if not self.released:out+=.25
                return not self.released
        bank=SimpleNamespace(drums={},voice=lambda *args:ShortVoice())
        _,out=render_layer((1,((321,True,'pink','piano'),(340,False,'pink','')),{},True),bank,self.rate)
        self.assertGreaterEqual(np.count_nonzero(out),round(self.rate*.01))

    def test_cymbal_tail_wraps_more_than_half_a_second(self):
        hit=np.full(self.rate*2,.1,dtype=np.float32)
        bank=SimpleNamespace(drums={('piano','black'):hit},voice=lambda *args:Voice((hit,)))
        _,out=render_layer((2,((self.rate*8-800,True,'black','piano'),),{},False),bank,self.rate)
        self.assertAlmostEqual(out[self.rate],.1,places=5)
        self.assertEqual(out[self.rate*2],0)

    def test_bad_loop_manifest_and_audio_format_have_clear_errors(self):
        import wave
        with scratch_directory() as root:
            folder=root/'music_maker';folder.mkdir()
            for value in ([],{}, {'layers':{},'undo':[]}):
                (folder/'layers.json').write_text(json.dumps(value))
                with self.assertRaises(ValueError):LayerStore(root,self.rate).load()
            with wave.open(str(folder/'stereo.wav'),'wb') as wav:
                wav.setnchannels(2);wav.setsampwidth(2);wav.setframerate(self.rate)
                wav.writeframes(np.zeros(self.rate*8*2,dtype='<i2').tobytes())
            (folder/'layers.json').write_text(json.dumps({'layers':{'1':'stereo.wav'}}))
            with self.assertRaisesRegex(ValueError,'mono PCM16'):LayerStore(root,self.rate).load()

    def test_custom_drum_loading_and_bad_slot_fallback(self):
        with scratch_directory() as root:
            data=np.full(400,.25,dtype=np.float32)
            save_wav_atomic(root/'kits/pink.wav',data,self.rate)
            save_wav_atomic(root/'outside.wav',data,self.rate)
            (root/'kits/manifest.json').write_text(json.dumps({'sample_rate':self.rate,'kits':{'piano':{'name':'Test kit','sounds':{'pink':'pink.wav','red':'../outside.wav'}}}}))
            with self.assertLogs(level='WARNING'):
                bank=MakerBank(self.rate,self.bank.melody,root/'kits')
            self.assertEqual(bank.drum_samples,1)
            self.assertEqual(bank.drum_names['piano'],'Test kit')
            np.testing.assert_allclose(bank.drums['piano','pink'],data,atol=1e-4)
            self.assertEqual(len(bank.drum_errors),1)
            self.assertGreater(len(bank.drums['piano','red']),400)

    def test_wrong_rate_custom_kit_keeps_generated_sounds(self):
        with scratch_directory() as root:
            (root/'manifest.json').write_text(json.dumps({'sample_rate':48000,'kits':{}}))
            bank=MakerBank(self.rate,self.bank.melody,root)
            self.assertEqual(bank.drum_samples,0)
            self.assertFalse(bank.drum_errors)

    def test_maker_routes_levels_without_learning_words(self):
        engine=Engine(SimpleNamespace(sequences={}, songs=[]),self.rate)
        engine.maker=LoopSession(self.rate,self.bank)
        engine.submit('activity','maker')
        out=np.zeros((80,2),dtype=np.float32)
        for level in (1,2):
            engine.submit('key','pink','piano',level);engine.render(out)
            self.assertTrue(out.any())
            engine.submit('key_up','pink');engine.render(out)
        engine.submit('song');engine.render(out)
        self.assertTrue(engine.maker.playing)
        engine.submit('activity','keyboard');engine.render(out)
        self.assertFalse(engine.maker.playing)

if __name__=='__main__':unittest.main()
