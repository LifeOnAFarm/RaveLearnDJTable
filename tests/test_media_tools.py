import json
from pathlib import Path
import unittest
import wave
from tools.check_media import check, check_wav
from test_core import scratch_directory


def wav(path, rate=8000, seconds=.1, channels=1):
    path.parent.mkdir(parents=True, exist_ok=True)
    with wave.open(str(path), 'wb') as out:
        out.setnchannels(channels); out.setsampwidth(2); out.setframerate(rate)
        out.writeframes(b'\x01\x00' * round(rate * seconds) * channels)


class MediaToolsTests(unittest.TestCase):
    def test_format_length_and_truncation(self):
        with scratch_directory() as root:
            p = root / 'hit.wav'; wav(p)
            self.assertAlmostEqual(check_wav(p, 8000, 2, True), .1)
            with self.assertRaises(ValueError): check_wav(p, 48000)
            with self.assertRaises(ValueError): check_wav(p, 8000, .05)
            wav(p, channels=2)
            with self.assertRaises(ValueError): check_wav(p, 8000, mono=True)
            p.write_bytes(p.read_bytes()[:-2])
            with self.assertRaises(ValueError): check_wav(p, 8000)

    def test_default_kits_and_numbered_backings(self):
        with scratch_directory() as root:
            config = {'sample_rate':8000, 'backing_beats_dir':root/'backing_beats', 'record_prompt_path':root/'prompt.wav'}
            wav(root/'prompt.wav')
            for folder in ('backing_beats','house_beats','punk_beats','baby_raver_beats'): wav(root/folder/'01_loop.wav')
            messages, errors = check(config, root/'drums')
            self.assertFalse(errors)
            self.assertTrue(any('fallback kits' in m for m in messages))
            (root/'house_beats/01_loop.wav').rename(root/'house_beats/loop.wav')
            self.assertTrue(any('no numbered' in e for e in check(config,root/'drums')[1]))

    def test_partial_custom_kit_and_path_escape(self):
        with scratch_directory() as root:
            wav(root/'piano/pink.wav')
            state={'sample_rate':8000,'kits':{'piano':{'sounds':{'pink':'piano/pink.wav'}}}}
            p=root/'manifest.json';p.write_text(json.dumps(state))
            messages,errors=check({'sample_rate':8000},root)
            self.assertFalse(errors);self.assertTrue(any('high/pink' in m for m in messages))
            state['kits']['piano']['sounds']['pink']='../escaped.wav';p.write_text(json.dumps(state))
            self.assertTrue(any('stay inside' in e for e in check({'sample_rate':8000},root)[1]))

    def test_bad_manifest_and_rate_mismatch(self):
        with scratch_directory() as root:
            for value in ([], {'sample_rate':48000,'kits':{}}, {'sample_rate':8000,'kits':{'other':{}}}):
                (root/'manifest.json').write_text(json.dumps(value))
                self.assertTrue(check({'sample_rate':8000},root)[1])
