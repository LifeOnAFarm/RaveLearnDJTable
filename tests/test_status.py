import time
import unittest
from unittest.mock import patch
import numpy as np
from djtable.core import SampleBank, TONES, COLOURS
from djtable.status import publish, read_status
from test_library import scratch_directory
from pathlib import Path


class StatusTests(unittest.TestCase):
    def test_each_level_uses_only_its_language_for_every_tone(self):
        def sample(path, rate, **options):
            value = 2 if 'colours/en' in Path(path).as_posix() else 3 if 'colours/ga' in Path(path).as_posix() else 1
            return np.array([value], dtype=np.float32)
        with scratch_directory() as root:
            for folder in [f'keys/{t}' for t in TONES] + [f'{kind}/{lang}' for kind in ('colours','symbols') for lang in ('en','ga')]:
                directory=root/folder;directory.mkdir(parents=True)
                for colour in COLOURS:(directory/f'{colour}.wav').touch()
            with patch('djtable.core.load_wav', side_effect=sample):
                bank = SampleBank(root, 48000)
        for tone in TONES:
            for level, expected in ((1, [1, 2]), (2, [1, 3]), (3, [1])):
                self.assertEqual([int(p[0]) for p in bank.sequences[tone, level, 'pink']], expected)

    def test_status_missing_fresh_stale_and_broken(self):
        with scratch_directory() as root:
            path = Path(root) / 'status.json'
            self.assertFalse(read_status(path)['online'])
            sliders = {'tone': {'position': 1}, 'level': {'position': 3}, 'volume': {'position': 1}}
            publish(sliders, .15, path)
            self.assertEqual(read_status(path)['sliders'], sliders)
            self.assertTrue(read_status(path)['online'])
            with patch('djtable.status.time.time', return_value=time.time() + 10):
                self.assertFalse(read_status(path)['online'])
            path.write_text('{')
            self.assertFalse(read_status(path)['online'])
