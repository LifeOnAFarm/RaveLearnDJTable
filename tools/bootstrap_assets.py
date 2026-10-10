"""Build original starter audio locally; never overwrite an existing asset.

Run from the repository root with its Python environment. eSpeak NG is used
offline for English/Irish words. --no-speech is for development smoke tests.
"""
import argparse
import json
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from djtable.core import COLOURS, SYMBOLS, load_wav, save_wav_atomic
from djtable.instruments import build_pack, InstrumentVoice
from djtable.modes import MODES

IRISH = ('bándearg', 'dearg', 'oráiste', 'glas', 'buí', 'gorm', 'corcra', 'dubh')
SHAPES = ('ciorcal', 'croí', 'triantán', 'cearnóg', 'réalta', 'heicseagán', 'gealach', 'muileata')
RATE = 48000


def write(path, data):
    if not path.exists():
        save_wav_atomic(path, data, RATE)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--no-speech', action='store_true')
    args = parser.parse_args()
    speaker = shutil.which('espeak-ng')
    if not args.no_speech and not speaker:
        parser.error('Install espeak-ng first, or use --no-speech for a notes-only development build')
    instruments = ROOT / 'assets/instruments'
    instruments.mkdir(parents=True, exist_ok=True)
    samples = ROOT / 'assets/samples'
    for mode in MODES:
        held, short = build_pack(RATE, mode)
        archive = instruments / f'{mode}-{RATE}-v2.npz'
        if not archive.exists():
            values = {}
            for (tone, colour), patch in held.items():
                key = tone + '_' + colour
                values[key] = patch.data
                values[key + '_loop'] = np.array([patch.loop_start, patch.loop_end])
                values[key + '_short'] = short[tone, colour]
            np.savez_compressed(archive, **values)
            del values
        if mode == 'teenage_disco':
            for (tone, colour), data in short.items():
                write(samples / 'keys' / tone / f'{colour}.wav', data)
        # The admin page previews these files; they are not instrument inputs.
        preview_root = instruments if mode == 'teenage_disco' else instruments / mode
        for tone in ('piano', 'high', 'synth'):
            if (preview_root / f'{tone}.wav').exists():
                continue
            pieces = []
            for colour in COLOURS:
                patch = held[tone, colour]
                note = np.zeros(round(RATE * .5), dtype=np.float32)
                if patch.loop_start >= patch.loop_end:  # One-shot sample: no sustain loop.
                    clip = patch.data[:len(note)]
                    note[:len(clip)] = clip
                else:
                    voice = InstrumentVoice(patch)
                    split = round(RATE * .3)
                    voice.mix(note[:split])
                    voice.release()
                    voice.mix(note[split:])
                pieces.extend((note, np.zeros(round(RATE * .08), dtype=np.float32)))
            write(preview_root / f'{tone}.wav', np.concatenate(pieces))
        print('Prepared', mode, flush=True)
        # A Zero 2 W need not retain all four packs while generating files.
        build_pack.cache_clear()
        del held, short
    if speaker and not args.no_speech:
        with tempfile.TemporaryDirectory() as folder:
            temporary = Path(folder) / 'voice.wav'
            def say(word, language):
                subprocess.run([speaker, '-v', language, '-s', '140', '-w', str(temporary), '--stdin'],
                               input=word.encode('utf-8'), check=True)
                data = load_wav(temporary, RATE)
                data *= min(4, .8 / max(float(np.max(np.abs(data))), .001))
                return np.concatenate((data, np.zeros(round(.12 * RATE), dtype=np.float32)))
            for index, colour in enumerate(COLOURS):
                for group, language, word in (
                    ('colours', 'en', colour), ('colours', 'ga', IRISH[index]),
                    ('symbols', 'en', SYMBOLS[colour]), ('symbols', 'ga', SHAPES[index])):
                    target = samples / group / language / f'{colour}.wav'
                    if not target.exists():
                        write(target, say(word, language))
                    copy = ROOT / 'assets/speech' / group / language / target.name
                    copy.parent.mkdir(parents=True, exist_ok=True)
                    if not copy.exists():
                        shutil.copyfile(target, copy)
            catalogue = ROOT / 'assets/speech/manifest.json'
            if not catalogue.exists():
                words = [{'file': f'{group}/{lang}/{colour}.wav', 'word': word}
                         for index, colour in enumerate(COLOURS)
                         for group, lang, word in (
                             ('colours', 'en', colour), ('colours', 'ga', IRISH[index]),
                             ('symbols', 'en', SYMBOLS[colour]), ('symbols', 'ga', SHAPES[index]))]
                catalogue.write_text(json.dumps(words, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
            prompt = say('Record a message after the beep.', 'en')
            t = np.arange(round(.18 * RATE)) / RATE
            beep = .4 * np.sin(2 * np.pi * 882 * t) * np.sin(np.pi * np.arange(len(t)) / len(t))**2
            write(ROOT / 'assets/recording-prompt.wav', np.concatenate((prompt, beep)))
    # Six original percussion loops, no extracts from commercial recordings.
    for index, tempo in enumerate((110, 120, 130, 140, 150, 160), 1):
        length = round(16 * 60 / tempo * RATE)
        beat = np.zeros(length, dtype=np.float32)
        rng = np.random.default_rng(index)
        for step in range(32):
            start = round(step * 30 / tempo * RATE)
            count = min(round(.16 * RATE), length - start)
            t = np.arange(count) / RATE
            hit = rng.standard_normal(count) * np.exp(-t * 90) * .06
            if step % 2 == 0:
                hit += .5 * np.sin(2*np.pi*(48*t + 1.6*(1-np.exp(-t*35)))) * np.exp(-t*25)
            if step % 8 in (4,):
                hit += rng.standard_normal(count) * np.exp(-t*35) * .16
            beat[start:start+count] += hit
        for folder in ('backing_beats', 'house_beats', 'punk_beats', 'baby_raver_beats'):
            write(ROOT / 'assets' / folder / f'{index:02d}_starter_{tempo}.wav', beat)
    print('Starter assets ready. Existing files were preserved.')


if __name__ == '__main__':
    main()
