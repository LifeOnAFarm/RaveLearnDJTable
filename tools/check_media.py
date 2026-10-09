"""Read-only check of remix backings, prompt and optional Music Maker drum hits.

Run after copying files, before restarting audio. Does not open an audio device.
"""
import argparse
import json
from pathlib import Path
import sys
import wave

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from djtable.__main__ import read_config
from djtable.core import COLOURS, TONES
from djtable.modes import MODES


def check_wav(path, rate, maximum=60, mono=False):
    with wave.open(str(path), 'rb') as wav:
        channels, width, source_rate, frames, codec, _ = wav.getparams()
        if width != 2 or codec != 'NONE' or channels not in ((1,) if mono else (1, 2)):
            raise ValueError('Use PCM16 ' + ('mono' if mono else 'mono or stereo') + ' WAV')
        if source_rate != rate:
            raise ValueError(f'Use {rate} Hz for predictable sample loading')
        if not 0 < frames <= rate * maximum:
            raise ValueError(f'Expected more than zero and at most {maximum} seconds')
        # Bounded reads also detect truncated WAVs without loading a whole clip.
        remaining = frames
        while remaining:
            count = min(remaining, 8192)
            if len(wav.readframes(count)) != count * channels * width:
                raise ValueError('Truncated WAV')
            remaining -= count
        return frames / rate


def check(config, drum_root=None):
    errors, messages = [], []
    rate = config['sample_rate']
    def inspect(path, maximum=60, mono=False):
        try:
            seconds = check_wav(path, rate, maximum, mono)
            messages.append(f'OK {path}: {seconds:.3f}s')
        except (OSError, ValueError, wave.Error, EOFError) as exc:
            errors.append(f'{path}: {exc}')
    if 'backing_beats_dir' in config:
        base = Path(config['backing_beats_dir'])
        for mode in MODES:
            folder = base if mode == 'teenage_disco' else Path(config.get(f'{mode}_beats_dir', base.parent / f'{mode}_beats'))
            beats = sorted(folder.glob('[0-9][0-9]_*.wav'))
            if not beats: errors.append(f'{folder}: no numbered backing WAVs (for example 01_my_beat.wav)')
            for beat in beats: inspect(beat)
        inspect(config.get('record_prompt_path', base / 'Voicemail Sound Effect.wav'), maximum=10)
    else:
        messages.append('Remix backings disabled: no backing_beats_dir in config.')
    root = Path(drum_root) if drum_root else ROOT / 'assets/drums/music_maker'
    manifest = root / 'manifest.json'
    if not manifest.exists():
        messages.append('No custom drum manifest: generated fallback kits will be used.')
        return messages, errors
    try:
        if manifest.stat().st_size > 65536: raise ValueError('Manifest exceeds 64 KiB')
        value = json.loads(manifest.read_text(encoding='utf-8'))
        if value['sample_rate'] != rate: raise ValueError('Drum sample_rate must match config')
        kits = value['kits']
        if not isinstance(kits, dict) or set(kits) - set(TONES): raise ValueError('Invalid kit keys')
        for tone in TONES:
            kit = kits.get(tone, {})
            sounds = kit.get('sounds', {})
            if not isinstance(sounds, dict) or set(sounds) - set(COLOURS): raise ValueError('Invalid drum colour keys')
            for colour in COLOURS:
                if colour not in sounds:
                    messages.append(f'{tone}/{colour}: generated fallback hit (no custom assignment)')
                    continue
                path = (root / sounds[colour]).resolve()
                if not path.is_relative_to(root.resolve()): raise ValueError('Drum paths must stay inside their folder')
                inspect(path, maximum=2, mono=True)
    except (OSError, ValueError, KeyError, TypeError, AttributeError) as exc:
        errors.append(f'{manifest}: {exc}')
    return messages, errors


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--config', type=Path, default=ROOT / 'config.json')
    parser.add_argument('--drum-root', type=Path, help='Check a staged custom kit before copying it')
    args = parser.parse_args(argv)
    try:
        messages, errors = check(read_config(args.config), args.drum_root)
    except (OSError, ValueError, KeyError, TypeError) as exc:
        messages, errors = [], [f'Configuration: {exc}']
    for message in messages: print(message)
    for error in errors: print('ERROR ' + error)
    print(f'{len(errors)} media error(s). This checks files/formats, not loudness or audible quality.')
    return int(bool(errors))


if __name__ == '__main__':
    raise SystemExit(main())
