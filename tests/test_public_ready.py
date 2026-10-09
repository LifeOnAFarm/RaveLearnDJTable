import unittest
import threading
from pathlib import Path
from types import SimpleNamespace
from http.server import ThreadingHTTPServer
from urllib.request import urlopen
import numpy as np
from djtable.instruments import build_pack, InstrumentVoice
from djtable.core import Engine, COLOURS
from djtable.library import Library
from djtable.web import handler_for
from test_core import scratch_directory


class PublicReadyTests(unittest.TestCase):
    def test_neutral_fast_path_matches_interpolation_across_wraps(self):
        held,_=build_pack(16000)
        for key,patch in held.items():
            with self.subTest(key=key):
                fast,slow=InstrumentVoice(patch),InstrumentVoice(patch)
                a=np.zeros(512,dtype=np.float32);b=a.copy()
                for i in range(50):
                    if i==40:fast.release();slow.release()
                    a.fill(0);b.fill(0)
                    fast.mix(a,1);slow.mix(b,1+1e-12)
                    np.testing.assert_allclose(a,b,atol=1e-6)

    def test_repress_tail_is_bounded_and_recording_clears_it(self):
        held,_=build_pack(16000)
        engine=Engine(SimpleNamespace(instruments=held,sequences={},songs=[]),rate=16000,capture=True)
        out=np.zeros((128,2),dtype=np.float32)
        for _ in range(30):
            engine.submit('key','pink','synth',3);engine.render(out)
            self.assertLessEqual(len(engine.retrigger_tails),8)
            self.assertTrue(np.isfinite(out).all())
        engine.submit('record');engine.render(out)
        self.assertFalse(engine.retrigger_tails)
        self.assertFalse(np.any(out))

    def test_simple_home_and_admin_are_separate(self):
        with scratch_directory() as root:
            server=ThreadingHTTPServer(('127.0.0.1',0),handler_for(Library(root)))
            thread=threading.Thread(target=server.serve_forever);thread.start()
            try:
                base=f'http://127.0.0.1:{server.server_port}'
                with urlopen(base+'/') as response:home=response.read().decode()
                with urlopen(base+'/admin') as response:admin=response.read().decode()
                with urlopen(base+'/upload.js') as response:script=response.read().decode()
                with urlopen(base+'/app.js') as response:admin_script=response.read().decode()
                self.assertIn('<h1>Home</h1>',home)
                self.assertIn('Add a song',home)
                self.assertIn('/api/controls',admin_script)
                self.assertNotIn('slider-debug',home)
                self.assertIn('slider-debug',admin)
                self.assertIn('slot:',script)
                self.assertIn('X-DJTable-CSRF',script)
            finally:
                server.shutdown();server.server_close();thread.join()
