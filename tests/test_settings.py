import json
from pathlib import Path
import unittest
from unittest.mock import patch
from djtable.settings import JsonReader
from djtable.library import atomic_json
from test_core import scratch_directory

class SettingsTests(unittest.TestCase):
    def test_unchanged_settings_are_read_once_and_atomic_replacement_refreshes(self):
        with scratch_directory() as root:
            path=root/'settings.json';atomic_json(path,{'value':'old'})
            reader=JsonReader(path)
            original=Path.read_text
            with patch.object(Path,'read_text',autospec=True,side_effect=original) as read:
                value=reader.read();value['value']='mutated'
                for _ in range(10):self.assertEqual(reader.read(),{'value':'old'})
                self.assertEqual(read.call_count,1)
                atomic_json(path,{'value':'new'})
                self.assertEqual(reader.read(),{'value':'new'})
                self.assertEqual(read.call_count,2)
            path.unlink();self.assertEqual(reader.read(),{})
            atomic_json(path,{'value':'back'});self.assertEqual(reader.read(),{'value':'back'})

    def test_invalid_settings_recover_on_file_change(self):
        with scratch_directory() as root:
            path=root/'settings.json';reader=JsonReader(path)
            for text in ('not JSON','[]','x'*65537):
                path.write_text(text);self.assertEqual(reader.read(),{})
            atomic_json(path,{'quantize':False});self.assertEqual(reader.read(),{'quantize':False})
