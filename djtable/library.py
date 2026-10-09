"""Persistent sample assignments shared by the web service and audio process."""
import json
import os
from pathlib import Path
import re
import threading
import uuid
import wave
import io

import numpy as np

from .core import COLOURS, TONES, SampleBank

SONG_GAIN = 10 ** (2.5 / 20)  # Songs sit about 3 dB under a key note (tools/level_report.py).

MAX_UPLOAD = 12 * 1024 * 1024
MAX_DECODED = 96 * 1024 * 1024  # Per mode; inactive song banks are not preloaded.
MAX_DISK = 96 * 1024 * 1024
SLOTS = tuple([f'keys/{tone}/{colour}.wav' for tone in TONES for colour in COLOURS]
              + [f'colours/{lang}/{colour}.wav' for lang in ('en', 'ga') for colour in COLOURS]
              + [f'symbols/{lang}/{colour}.wav' for lang in ('en', 'ga') for colour in COLOURS]
              + [f'beats/beat_{i}.wav' for i in range(4)] + ['scratch.wav'])
FILE_PATTERN = re.compile(r'^[a-f0-9]{32}\.wav$')


def atomic_json(path, value):
    path = Path(path)
    temporary = path.with_name(path.name + '.' + uuid.uuid4().hex + '.tmp')
    try:
        with temporary.open('x', encoding='utf-8') as out:
            json.dump(value, out, indent=2, ensure_ascii=False)
            out.write('\n')
            out.flush()
            os.fsync(out.fileno())
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


class Library:
    def __init__(self, root, rate=48000):
        self.root = Path(root)
        self.rate = rate
        self.root.mkdir(parents=True, exist_ok=True)
        self.uploads = self.root / 'uploads'
        self.uploads.mkdir(exist_ok=True)
        self.manifest = self.root / 'library.json'
        self.lock = threading.Lock()

    def stamp(self):
        try:
            stat = self.manifest.stat()
            return stat.st_mtime_ns, stat.st_size
        except FileNotFoundError:
            return None

    def path(self, filename):
        if not isinstance(filename, str) or not FILE_PATTERN.fullmatch(filename):
            raise ValueError('Invalid stored sample name')
        return self.uploads / filename

    def read(self):
        try:
            state = json.loads(self.manifest.read_text(encoding='utf-8'))
        except FileNotFoundError:
            return {'version': 1, 'songs': [], 'assignments': {}}
        if state.get('version') != 1 or not isinstance(state.get('songs'), list) or not isinstance(state.get('assignments'), dict):
            raise ValueError('Invalid sample library')
        if len(state['songs']) > 12 or set(state['assignments']) - set(SLOTS):
            raise ValueError('Invalid sample assignments')
        seen = set()
        for item in self.items(state):
            self.path(item['file'])
            if not isinstance(item.get('title'), str) or len(item['title']) > 100:
                raise ValueError('Invalid sample title')
            if not isinstance(item.get('decoded_bytes'), int) or not 0 < item['decoded_bytes'] <= MAX_DECODED:
                raise ValueError('Invalid sample size')
        for song in state['songs']:
            if song['file'] in seen:
                raise ValueError('Duplicate song')
            seen.add(song['file'])
        if sum(item['decoded_bytes'] for item in self.items(state)) > MAX_DECODED:
            raise ValueError('Sample library exceeds memory budget')
        return state

    @staticmethod
    def items(state):
        return state['songs'] + list(state['assignments'].values())

    def inspect(self, raw):
        if not 0 < len(raw) <= MAX_UPLOAD:
            raise ValueError('Choose a WAV file no larger than 12 MiB')
        try:
            with wave.open(io.BytesIO(raw), 'rb') as wav:
                channels, width, source_rate, frames, codec, _ = wav.getparams()
                if codec != 'NONE' or width != 2 or channels not in (1, 2):
                    raise ValueError('Use PCM 16-bit mono or stereo WAV')
                if not 8000 <= source_rate <= self.rate:
                    raise ValueError(f'Use a WAV sample rate between 8000 and {self.rate} Hz')
                if not frames or frames / source_rate > 60:
                    raise ValueError('Choose a sample longer than zero and at most 60 seconds')
                if len(wav.readframes(frames)) != frames * channels * width:
                    raise ValueError('The WAV file is truncated')
                return {'seconds': round(frames / source_rate, 3), 'rate': source_rate,
                        'channels': channels, 'decoded_bytes': round(frames * self.rate / source_rate) * 4}
        except (wave.Error, EOFError) as exc:
            raise ValueError('Use an uncompressed PCM 16-bit WAV file') from exc

    def upload(self, raw, title, slot='song'):
        if slot != 'song' and slot not in SLOTS:
            raise ValueError('Unknown destination')
        meta = self.inspect(raw)
        title = str(title).strip()[:100] or 'Untitled sample'
        with self.lock:
            state = self.read()
            if slot == 'song' and len(state['songs']) >= 12:
                raise ValueError('Playlist is full (12 songs); remove a song first')
            used = sum(p.stat().st_size for p in self.uploads.glob('*.wav'))
            if used + len(raw) > MAX_DISK:
                raise ValueError('Upload storage is full; remove an unused song or reset an assignment')
            filename = uuid.uuid4().hex + '.wav'
            item = dict(meta, title=title, file=filename)
            if slot == 'song':
                state['songs'].append(item)
            else:
                state['assignments'][slot] = item
            if sum(i['decoded_bytes'] for i in self.items(state)) > MAX_DECODED:
                raise ValueError('Sample memory is full; shorten or remove another sample first')
            target = self.path(filename)
            try:
                with target.open('xb') as out:
                    out.write(raw)
                    out.flush()
                    os.fsync(out.fileno())
                atomic_json(self.manifest, state)
            except Exception:
                target.unlink(missing_ok=True)
                raise
            self.prune(state)
            return state

    def change(self, action, value):
        with self.lock:
            state = self.read()
            if action == 'order':
                if not isinstance(value, list) or len(value) != len(state['songs']) or set(value) != {s['file'] for s in state['songs']}:
                    raise ValueError('Order must contain every current song exactly once')
                by_file = {s['file']: s for s in state['songs']}
                state['songs'] = [by_file[name] for name in value]
            elif action == 'remove':
                if value not in {s['file'] for s in state['songs']}:
                    raise ValueError('Song not found')
                state['songs'] = [s for s in state['songs'] if s['file'] != value]
            elif action == 'reset':
                if value not in SLOTS:
                    raise ValueError('Unknown sample slot')
                state['assignments'].pop(value, None)
            else:
                raise ValueError('Unknown action')
            atomic_json(self.manifest, state)
            self.prune(state)
            return state

    def prune(self, state):
        referenced = {item['file'] for item in self.items(state)}
        for path in self.uploads.glob('*.wav'):
            if FILE_PATTERN.fullmatch(path.name) and path.name not in referenced:
                path.unlink(missing_ok=True)


def load_bank(config, library, shared_library=None, include_songs=True):
    state = library.read()
    overrides = {slot: library.path(item['file']) for slot, item in state['assignments'].items()}
    if shared_library is not None:
        overrides.update({slot: shared_library.path(item['file'])
                          for slot, item in shared_library.read()['assignments'].items()
                          if slot.startswith(('colours/', 'symbols/'))})
    # Once a web manifest exists its ordered playlist is authoritative, including empty.
    songs = [library.path(s['file']) for s in state['songs']] if library.manifest.exists() else config['songs']
    if not include_songs:
        songs = []  # Fast start: keys and words first; songs load in the background.
    bank = SampleBank(config['sample_root'], config['sample_rate'], songs, overrides)
    if config.get('musical_keyboard', False):
        from .instruments import build_pack
        sound_mode = config.get('sound_mode', 'teenage_disco')
        held, short = build_pack(config['sample_rate'], sound_mode)
        bank.instruments = dict(held)
        # Custom key uploads remain authoritative; without loop metadata they
        # play once at their uploaded pitch. Built-ins have pentatonic sustain loops.
        for (tone, colour), patch in held.items():
            slot = f'keys/{tone}/{colour}.wav'
            if slot in overrides:
                bank.instruments.pop((tone, colour), None)
                continue
            for level in (1, 2):
                if tone == 'synth' and sound_mode == 'teenage_disco':
                    continue  # Keep the user's liked original short synth notes.
                for collection in (bank.sequences, bank.symbol_sequences):
                    old = collection[tone, level, colour]
                    collection[tone, level, colour] = (short[tone, colour], *old[1:])
    from .remix import level_clip
    for index, song in enumerate(bank.songs):
        # Imported songs already have measured, two-pass loudness matching.
        # Do not undo that balance with a second per-file RMS normalization.
        matched = library.manifest.exists() and state['songs'][index].get('loudness_lufs') == -16
        level = song.astype('float32') / 32768 if matched else level_clip(song.astype('float32') / 32768, target_rms=.20)
        bank.songs[index] = (np.tanh(level * SONG_GAIN / .95) * .95 * 32767).astype('int16')
    if bank.override_errors:
        raise ValueError('Sample library could not load: ' + '; '.join(bank.override_errors[:3]))
    return bank
