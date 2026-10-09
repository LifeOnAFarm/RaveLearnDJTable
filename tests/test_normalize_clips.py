import hashlib
from pathlib import Path
import shutil
import sys
import unittest
import wave

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from tools.normalize_clips import main, normalize
from test_core import scratch_directory


@unittest.skipUnless(shutil.which('ffmpeg'), 'FFmpeg required for normalizer integration tests')
class NormalizeTests(unittest.TestCase):
    def clip(self, path, amplitude=.1, seconds=4):
        rate = 8000
        data = (amplitude * np.sin(np.arange(round(seconds * rate)) * 2*np.pi*440/rate) * 32767).astype('<i2')
        with wave.open(str(path), 'wb') as output:
            output.setparams((1, 2, rate, len(data), 'NONE', ''))
            output.writeframes(data.tobytes())

    def test_quiet_and_loud_sources_match_and_originals_are_preserved(self):
        with scratch_directory() as root:
            levels = []
            for index, amplitude in enumerate((.02, .7)):
                source, target = root/f'original {index}.wav', root/f'matched {index}.wav'
                self.clip(source, amplitude)
                checksum = hashlib.sha256(source.read_bytes()).hexdigest()
                report = normalize(source, target)
                self.assertIsNone(report['warning'])
                self.assertLess(abs(report['output_lufs'] + 16), .5)
                self.assertLessEqual(report['output_true_peak_dbtp'], -1.3)
                self.assertEqual(checksum, hashlib.sha256(source.read_bytes()).hexdigest())
                levels.append(report['output_lufs'])
                with wave.open(str(target)) as wav:
                    self.assertEqual((wav.getnchannels(), wav.getsampwidth(), wav.getframerate()), (1, 2, 48000))
                    self.assertAlmostEqual(wav.getnframes()/48000, 4, places=2)
            self.assertLess(abs(levels[0] - levels[1]), .2)

    def test_long_source_requires_explicit_excerpt_and_never_overwrites(self):
        with scratch_directory() as root:
            source, target = root/'long.wav', root/'out.wav'
            self.clip(source, seconds=61)
            with self.assertRaisesRegex(ValueError, '1–60'):
                normalize(source, target)
            self.assertFalse(target.exists())
            report = normalize(source, target, start=10, duration=4)
            self.assertAlmostEqual(report['seconds'], 4)
            checksum = target.read_bytes()
            with self.assertRaisesRegex(ValueError, 'overwrite'):
                normalize(source, target, duration=4)
            self.assertEqual(checksum, target.read_bytes())

    def test_silence_is_reported_without_publishing_a_clip(self):
        with scratch_directory() as root:
            source = root/'silent.wav'
            self.clip(source, amplitude=0)
            self.assertEqual(main([str(source), '--output', str(root/'matched')]), 1)
            self.assertFalse((root/'matched/silent.wav').exists())
            self.assertEqual(len(list((root/'matched').glob('normalization-report-*.json'))), 1)

    def test_backing_cli_numbers_files_for_remix_loader(self):
        with scratch_directory() as root:
            source = root/'beat.wav'
            self.clip(source)
            self.assertEqual(main([str(source), '--kind', 'backing', '--output', str(root/'matched')]), 0)
            self.assertTrue((root/'matched/01_beat.wav').exists())
