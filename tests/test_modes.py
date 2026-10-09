import json
import threading
import unittest
from unittest.mock import patch
from pathlib import Path
from types import SimpleNamespace
from urllib.request import Request, urlopen
from urllib.error import HTTPError
from http.server import ThreadingHTTPServer

import numpy as np

from djtable.__main__ import read_config
from djtable.core import Engine, COLOURS, save_wav_atomic, Voice
from djtable.instruments import build_pack, InstrumentVoice
from djtable.library import load_bank
from djtable.modes import Modes
from djtable.web import handler_for
from test_core import scratch_directory
from test_library import wav_bytes


class ModeTests(unittest.TestCase):
    def test_pcm16_playback_matches_float_with_and_without_pitch_shift(self):
        data=(np.sin(np.arange(2000)*.13)*28000).astype('int16')
        for speed in (1.0, .7, 1.4):
            a=Voice((data,));b=Voice((data.astype('float32')/32768,))
            for _ in range(12):
                x=np.zeros(256,dtype=np.float32);y=x.copy()
                self.assertEqual(a.mix(x,speed),b.mix(y,speed))
                np.testing.assert_allclose(x,y,atol=1e-7)

    def config(self, root):
        config=read_config(Path(__file__).parents[1]/'config.json')
        config['library_dir']=root/'library'
        # This unit test must not depend on the developer's external sample pack.
        config['sample_root']=root/'samples'
        note=config['sample_root']/'keys/piano/pink.wav'
        note.parent.mkdir(parents=True,exist_ok=True)
        note.write_bytes(wav_bytes())
        config.pop('backing_beats_dir',None)
        return config

    def test_fast_start_loads_keys_without_songs_and_is_not_cached(self):
        with scratch_directory() as root:
            modes=Modes(self.config(root))
            modes.library('teenage_disco').upload(wav_bytes(160),'Disco song')
            mode,bank,remixes=modes.load('teenage_disco',songs=False)
            self.assertEqual(len(bank.songs),0)
            self.assertTrue(any(bank.sequences.values()))  # Keys and words are ready.
            self.assertNotIn('teenage_disco',modes.cache)
            self.assertEqual(len(modes.load('teenage_disco')[1].songs),1)  # The full load still has songs.

    def test_libraries_persist_independently_and_words_are_shared(self):
        with scratch_directory() as root:
            modes=Modes(self.config(root))
            self.assertEqual(modes.selected(),'teenage_disco')
            modes.library('teenage_disco').upload(wav_bytes(160),'Disco song')
            modes.library('house').upload(wav_bytes(320),'House song')
            modes.library('teenage_disco').upload(wav_bytes(640),'Shared English','colours/en/pink.wav')
            for mode,frames in [('teenage_disco',480),('house',960)]:
                modes.select(mode)
                self.assertEqual(Modes(self.config(root)).selected(),mode)
                _,bank,_=modes.load(mode)
                self.assertIs(modes.load(mode)[1],bank)
                self.assertEqual(bank.songs[0].dtype,np.dtype('int16'))
                self.assertEqual(len(bank.songs[0]),frames)
                self.assertEqual(len(bank.sequences['piano',1,'pink'][1]),1920)
            with self.assertRaises(ValueError):modes.select('../escape')

    def test_atomic_switch_clears_old_voices_and_protects_capture(self):
        note=(np.full(1000,.1,dtype=np.float32),)
        old=SimpleNamespace(songs=list(note),sequences={('piano',1,'pink'):note},symbol_sequences={})
        new=SimpleNamespace(songs=[np.full(1000,.2)],sequences={},symbol_sequences={})
        engine=Engine(old,rate=1000)
        out=np.zeros((10,2),dtype=np.float32)
        for state in ('prompt','recording','saving'):
            engine.record_state=state
            engine.submit('mode','house',new,None,())
            engine.render(out)
            self.assertIs(engine.bank,old)
        engine.record_state='idle'
        engine.submit('song');engine.render(out)
        engine.submit('mode','house',new,None,());engine.render(out)
        self.assertIs(engine.bank,new)
        self.assertFalse(engine.voices)
        self.assertEqual(engine.mode,'house')
        self.assertIsNone(engine.last_learning_key)
        engine.submit('song');engine.render(out)
        self.assertIs(engine.voices['song'].parts[0],new.songs[0])

    def test_four_modes_are_isolated_and_cache_is_bounded(self):
        with scratch_directory() as root:
            modes=Modes(self.config(root))
            for index, mode in enumerate(modes.libraries):
                modes.library(mode).upload(wav_bytes(160*(index+1)), mode)
                modes.select(mode)
                _,bank,_=modes.load(mode)
                self.assertEqual(len(bank.songs[0]),480*(index+1))
                self.assertLessEqual(modes.cache_bytes(),224*1024*1024)
                self.assertEqual(Modes(self.config(root)).selected(),mode)
            self.assertEqual(len(modes.cache),4)
            self.assertEqual(len(modes.load('teenage_disco')[1].songs[0]),480)
            with patch('djtable.modes.CACHE_BYTES',1):
                modes.library('punk').upload(wav_bytes(80),'Another song')
                modes.load('punk')
            self.assertEqual(set(modes.cache),{'punk'})

    def test_new_modes_have_separate_beat_and_remix_paths(self):
        with scratch_directory() as root:
            config=self.config(root)
            config['backing_beats_dir']=root/'assets/backing_beats'
            modes=Modes(config)
            for mode in ('punk','baby_raver'):
                settings=modes.configuration(mode)
                self.assertEqual(settings['backing_beats_dir'],root/'assets'/f'{mode}_beats')
                self.assertEqual(settings['remix_dir'],root/f'{mode}_remixes')
                self.assertEqual(settings['record_prompt_path'],config.get('record_prompt_path',config['backing_beats_dir']/'Voicemail Sound Effect.wav'))

    def test_new_patches_sustain_bend_release_without_clipping(self):
        for mode in ('punk','baby_raver'):
            held,short=build_pack(48000,mode)
            for key,patch in held.items():
                voice=InstrumentVoice(patch)
                output=np.zeros(96000,dtype=np.float32)
                self.assertTrue(voice.mix(output,.89))
                self.assertTrue(np.isfinite(output).all())
                self.assertLessEqual(float(np.max(np.abs(output))),.86)  # Punk is raised 3.5 dB and soft-limited below .85.
                voice.release()
                self.assertFalse(voice.mix(np.zeros(24000,dtype=np.float32)))
                self.assertGreater(float(np.sqrt(np.mean(short[key]**2))),.01)
            for tone in ('high','synth'):
                self.assertFalse(np.allclose(short['piano','pink'],short[tone,'pink']))

    def test_loop_interpolation_matches_virtual_endpoint_without_full_copy(self):
        from djtable.instruments import Patch
        data=np.array([0,.1,.2,.3,.8,.4,0],dtype=np.float32)
        patch=Patch(data,2,4,48000)
        voice=InstrumentVoice(patch)
        got,_=voice._read(3.25,4,.2,True)
        positions=np.array([3.25,3.45,3.65,3.85])
        virtual=data.astype('float64');virtual[4]=data[2]
        np.testing.assert_allclose(got,np.interp(positions,np.arange(len(data)),virtual),atol=1e-7)
        self.assertIs(patch.loop_data,patch.resample_data)
        self.assertTrue(patch.grid.flags.writeable)
        self.assertTrue(patch.grid.flags.c_contiguous)
        from djtable.instruments import sample_grid
        self.assertTrue(np.shares_memory(sample_grid(40000),sample_grid(45000)))

    def test_house_chords_and_bass_sustain_stabs_ring_out(self):
        held,short=build_pack(48000,'house')
        if not all(p.loop_start==len(p.data) for (tone,_),p in held.items() if tone=='high'):
            self.skipTest('House sample pack not installed (starter House is synthesised)')
        def play(tone,colour,hold_blocks):
            engine=Engine(SimpleNamespace(instruments=held,sequences={},songs=[]),rate=48000,volume=1.0)
            engine.submit('key',colour,tone,3)
            levels,blocks=[],0
            while blocks<600:
                if blocks==hold_blocks: engine.submit('key_up',colour)
                out=np.zeros((512,2),dtype=np.float32);engine.render(out);blocks+=1
                self.assertTrue(np.isfinite(out).all());self.assertLessEqual(float(np.max(np.abs(out))),.86)
                levels.append(float(np.sqrt(np.mean(out[:,0]**2))))
                if blocks>hold_blocks and colour not in engine.voices and not engine.retrigger_tails: break
            return levels,blocks
        for (tone,colour),patch in held.items():
            with self.subTest(tone=tone,colour=colour):
                self.assertEqual(len(short[tone,colour]),31200)
                if tone=='high':  # Stab: a tap still rings out fully.
                    self.assertEqual(patch.loop_start,len(patch.data))
                    _,blocks=play(tone,colour,0)
                    self.assertGreater(blocks*512,.8*len(patch.data))
                else:  # Chords and bass: held for ~1.5 s at a steady level, then a clean finish.
                    self.assertLess(patch.loop_start,patch.loop_end)
                    levels,blocks=play(tone,colour,140)
                    sustained=levels[100:140]
                    self.assertGreater(min(sustained),.02)
                    self.assertLess(max(sustained)/min(sustained),2.0)
                    self.assertLess(blocks,600)
        # Three distinct sound slots, not renamed copies.
        for a,b in [('piano','high'),('high','synth'),('piano','synth')]:
            self.assertFalse(np.allclose(short[a,'pink'],short[b,'pink']))

    def test_web_selection_and_explicit_upload_destination(self):
        with scratch_directory() as root:
            modes=Modes(self.config(root))
            server=ThreadingHTTPServer(('127.0.0.1',0),handler_for(modes.library('teenage_disco'),modes.config['sample_root'],modes))
            thread=threading.Thread(target=server.serve_forever);thread.start()
            base=f'http://127.0.0.1:{server.server_port}'
            def get(path):
                with urlopen(base+path) as response:return json.load(response)
            def post(path,data,token):
                req=Request(base+path,data=data,headers={'X-DJTable-CSRF':token},method='POST')
                with urlopen(req) as response:return json.load(response)
            try:
                token=get('/api/modes')['csrf']
                with self.assertRaises(HTTPError):post('/api/mode',b'{"mode":"house"}','bad')
                post('/api/mode',b'{"mode":"house"}',token)
                self.assertEqual(get('/api/library')['mode'],'house')
                # A page opened before the selection changed still uploads to
                # its explicitly named library, never whichever mode wins a race.
                post('/api/upload?mode=teenage_disco&slot=song&title=Disco',wav_bytes(),token)
                self.assertEqual(len(get('/api/library?mode=house')['songs']),0)
                self.assertEqual(len(get('/api/library?mode=teenage_disco')['songs']),1)
                post('/api/upload?mode=house&slot=colours/en/pink.wav&title=Shared',wav_bytes(),token)
                self.assertIn('colours/en/pink.wav',get('/api/library?mode=house')['assignments'])
                self.assertIn('colours/en/pink.wav',get('/api/library?mode=teenage_disco')['assignments'])
                with self.assertRaises(HTTPError):get('/api/library?mode=invalid')
            finally:
                server.shutdown();server.server_close();thread.join()


if __name__=='__main__':unittest.main()
