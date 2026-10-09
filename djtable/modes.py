"""Independent sound libraries with a byte-bounded shared sample cache."""
from collections import OrderedDict
from pathlib import Path
import json
import sys
import ctypes

from .library import Library, atomic_json, load_bank
from .settings import JsonReader
import numpy as np

CACHE_BYTES = 80 * 1024 * 1024


def trim_audio_heap():
    """Return freed loader buffers to Linux, never from the audio callback."""
    if sys.platform.startswith('linux'):
        trim = getattr(ctypes.CDLL(None), 'malloc_trim', None)
        if trim is not None:
            trim.argtypes = [ctypes.c_size_t]
            trim.restype = ctypes.c_int
            trim(0)

MODES = {
    'teenage_disco': {'name': 'Teenage Disco', 'tones': ['Electric piano', 'Meows', 'Synth']},
    'house': {'name': 'House', 'tones': ['House chords', 'Chord stabs', 'Deep bass']},
    'punk': {'name': 'Punk', 'tones': ['Clean guitar', 'Crunch guitar', 'Power chord']},
    'baby_raver': {'name': 'Baby Raver', 'tones': ['Quacky duck', 'Meowing cat', 'Bouncy robot']},
}


class Modes:
    def __init__(self, config):
        self.config = config
        self.root = Path(config['library_dir']).parent
        self.selection = self.root / 'mode.json'
        self._selection_reader = JsonReader(self.selection)
        self.cache = OrderedDict()
        self.libraries = {mode: Library(config['library_dir'] if mode == 'teenage_disco'
                                       else self.root / f'{mode}_library', config['sample_rate'])
                          for mode in MODES}

    def selected(self):
        try:
            mode = self._selection_reader.read()['mode']
            return self.validate('house' if mode == 'dank' else mode)  # Dank was renamed House.
        except (OSError, ValueError, KeyError, TypeError):
            return 'teenage_disco'

    @staticmethod
    def validate(mode):
        if not isinstance(mode, str) or mode not in MODES:
            raise ValueError('Choose a listed music mode')
        return mode

    def select(self, mode):
        atomic_json(self.selection, {'mode': self.validate(mode)})

    def library(self, mode):
        return self.libraries[self.validate(mode)]

    def configuration(self, mode):
        self.validate(mode)
        config = dict(self.config, sound_mode=mode)
        if mode != 'teenage_disco':
            config['songs'] = []
            if 'backing_beats_dir' in config:
                config['backing_beats_dir'] = Path(config.get(f'{mode}_beats_dir', Path(config['backing_beats_dir']).parent / f'{mode}_beats'))
                config['remix_dir'] = self.root / f'{mode}_remixes'
                # All modes share the existing friendly prompt.
                config.setdefault('record_prompt_path', Path(self.config['backing_beats_dir']) / 'Voicemail Sound Effect.wav')
        return config

    def stamp(self, mode):
        # Words remain shared; a word replacement in Disco also refreshes House.
        return self.library(mode).stamp(), self.library('teenage_disco').stamp()

    def load(self, mode, songs=True):
        """Load a theme. songs=False is the fast start-up path: keys, words and prompt
        only, never cached, so the full theme is loaded (and cached) afterwards."""
        stamp = self.stamp(mode)
        if songs and mode in self.cache and self.cache[mode][0] == stamp:
            self.cache.move_to_end(mode)
            from .core import prime_audio_buffers
            prime_audio_buffers(self.cache[mode][1])
            return self.cache[mode][1]
        config = self.configuration(mode)
        bank = load_bank(config, self.library(mode), shared_library=self.library('teenage_disco'), include_songs=songs)
        remixes = self.cache[mode][1][2] if mode in self.cache else None
        if remixes is None and 'backing_beats_dir' in config:
            from .remix import RemixStore
            remixes = RemixStore(config['backing_beats_dir'], config['remix_dir'], config['sample_rate'],
                                 prompt_path=config.get('record_prompt_path'))
        result = mode, bank, remixes
        if not songs:
            return result
        self.cache[mode] = (stamp, result)
        self.cache.move_to_end(mode)
        while len(self.cache) > 1 and self.cache_bytes() > CACHE_BYTES:
            self.cache.popitem(last=False)
        trim_audio_heap()
        from .core import prime_audio_buffers
        prime_audio_buffers(result)
        return result

    def cache_bytes(self):
        """Count shared arrays once, including remixes and interpolation data."""
        seen = set()
        def size(value):
            if id(value) in seen:
                return 0
            seen.add(id(value))
            if isinstance(value, np.ndarray):
                if isinstance(value.base, np.ndarray):
                    return size(value.base)
                return value.nbytes
            if isinstance(value, dict):
                return sum(size(item) for item in value.values())
            if isinstance(value, (list, tuple)):
                return sum(size(item) for item in value)
            if hasattr(value, '__dict__') and not isinstance(value, Path):
                return size(vars(value))
            return 0
        return sum(size(result) for _, result in self.cache.values())
