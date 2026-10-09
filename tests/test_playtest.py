import importlib.util
from pathlib import Path
from types import SimpleNamespace
import unittest
from unittest.mock import patch
import numpy as np
from djtable.core import Engine, Voice
from test_core import scratch_directory


class PlaytestTests(unittest.TestCase):
    def engine(self):
        note = (np.ones(1000, dtype=np.float32)*.1,)
        bank = SimpleNamespace(songs=[np.ones(1000)*.2],
                               sequences={('synth', level, 'pink'): note for level in (1,2,3)},
                               symbol_sequences={('synth', level, 'pink'): note for level in (1,2)})
        return Engine(bank, rate=1000, saved_songs=(np.ones(1000)*.3,np.ones(1000)*.4))

    def command(self, engine, *command):
        engine.submit(*command)
        engine.render(np.zeros((20,2), dtype=np.float32))

    def test_platter_never_replays_remixes(self):
        e=self.engine()  # Remixes are one-and-done; saved songs are ignored by the platter.
        for value in (.02,.4,0,-.4,.9):
            self.command(e,'platter',value)
        self.assertFalse(e.voices)
        self.assertEqual(e.record_state,'idle')

    def test_busy_spin_does_not_queue_recording(self):
        for busy in ('key','song','prompt','recording','saving'):
            e=self.engine()
            if busy=='key':self.command(e,'key','pink','synth',3)
            elif busy=='song':self.command(e,'song')
            else:e.record_state=busy
            self.command(e,'platter',.5)
            self.assertNotIn('remix',e.voices)
            e.voices.clear();e.record_state='idle'
            self.command(e,'platter',.5)
            self.assertFalse(e.voices)

    def test_all_levels_play_over_remix_and_song_stop_keeps_keyboard(self):
        for level in (1,2,3):
            e=self.engine()
            e.record_state='saving'
            self.command(e,'remix_ready',np.ones(1000,np.float32)*.3,(),'beat',None)
            original=e.voices['remix']
            self.command(e,'key','pink','synth',level)
            self.command(e,'key','pink','synth',level)
            self.assertIs(e.voices['remix'],original)
            self.assertEqual(e.record_state,'playing')
            self.command(e,'song')
            self.assertNotIn('remix',e.voices)
            self.assertIn('pink',e.voices)

    def test_song_pool_excludes_remixes_and_empty_pool_is_silent(self):
        e=self.engine()
        self.command(e,'song')
        self.assertIs(e.voices['song'].parts[0],e.bank.songs[0])
        self.command(e,'song')
        e.bank.songs=[]
        self.command(e,'song')
        self.assertFalse(e.voices)


class NetworkHelperTests(unittest.TestCase):
    def setUp(self):
        spec=importlib.util.spec_from_file_location('network_helper',Path(__file__).parents[1]/'deploy/djtable-network.py')
        self.helper=importlib.util.module_from_spec(spec);spec.loader.exec_module(self.helper)

    def test_credentials_derive_psk_without_keyfile_injection(self):
        ssid,psk=self.helper.credentials({'ssid':'Room; [wifi]', 'password':'p@ssword=123'})
        self.assertEqual(ssid,'Room; [wifi]')
        self.assertEqual(len(psk),64)
        int(psk,16)
        for bad in ({'ssid':'x\n[connection]','password':'password'},
                    {'ssid':'x','password':'short'}, {'ssid':'é'*17,'password':'password'}):
            with self.assertRaises(ValueError):self.helper.credentials(bad)

    def test_status_distinguishes_wifi_hotspot_and_disconnection(self):
        for name,address,expected in [('ExampleWiFi','192.0.2.10/24','wifi'),
                                      ('DJTable-Hotspot','10.42.0.1/24','hotspot'),('--','','offline')]:
            with patch.object(self.helper,'nm',side_effect=[name,address]):
                self.helper.refresh()
            self.assertEqual(self.helper.state['mode'],expected)

    def test_failed_join_removes_only_candidate_and_restores_hotspot(self):
        with scratch_directory() as root:
            with patch.object(self.helper,'PROFILE_DIR',Path(root)), \
                 patch.object(self.helper.time,'sleep'), \
                 patch.object(self.helper,'nm',side_effect=['',RuntimeError('failed'),'']) as nm, \
                 patch.object(self.helper,'refresh',return_value=False), \
                 patch.object(self.helper,'hotspot') as hotspot:
                self.helper.state['busy']=True
                self.helper.connect('Test network','a'*64)
                hotspot.assert_called_once()
                self.assertFalse(self.helper.state['busy'])
                self.assertIn('Could not join',self.helper.state['error'])
                self.assertEqual(list(Path(root).iterdir()),[])
                self.assertEqual(nm.call_args_list[-1].args[:3],('connection','delete','uuid'))

    def test_successful_join_retains_private_profile_and_enables_autoconnect(self):
        with scratch_directory() as root:
            with patch.object(self.helper,'PROFILE_DIR',Path(root)), \
                 patch.object(self.helper.time,'sleep'), \
                 patch.object(self.helper,'nm',return_value='') as nm, \
                 patch.object(self.helper,'refresh'), \
                 patch.object(self.helper,'hotspot') as hotspot:
                self.helper.connect('Test network','a'*64)
                hotspot.assert_not_called()
                files=list(Path(root).iterdir())
                self.assertEqual(len(files),1)
                self.assertNotIn('Test network',files[0].read_text())
                self.assertIn('psk='+'a'*64,files[0].read_text())
                self.assertIn('connection.autoconnect',nm.call_args.args)
                self.assertFalse(self.helper.state['busy'])
