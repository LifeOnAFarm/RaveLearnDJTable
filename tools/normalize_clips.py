"""Match clip loudness for DJTable using FFmpeg; keep originals unchanged.

Example: python tools/normalize_clips.py songs --output matched_songs
Requires Python 3.11+ and FFmpeg on PATH; no Python packages required.
"""
import argparse
import json
import math
from pathlib import Path
import shutil
import subprocess
import tempfile
import uuid
import wave

EXTENSIONS = {'.wav', '.mp3', '.flac', '.ogg', '.opus', '.m4a', '.aac', '.aif', '.aiff'}
TARGET = 'loudnorm=I=-16:TP=-1.5:LRA=9'


def run(ffmpeg, *arguments):
    result = subprocess.run([ffmpeg, '-hide_banner', '-nostdin', *map(str, arguments)],
                            capture_output=True, text=True, encoding='utf-8', errors='replace')
    if result.returncode:
        raise ValueError('FFmpeg failed: ' + result.stderr[-1500:])
    return result.stderr


def measure(ffmpeg, path):
    output = run(ffmpeg, '-i', path, '-map', '0:a:0', '-af', TARGET + ':print_format=json', '-f', 'null', '-')
    try:
        values = json.JSONDecoder().raw_decode(output[output.rfind('{'):])[0]
        for key in ('input_i', 'input_tp', 'input_lra', 'input_thresh', 'target_offset'):
            if not math.isfinite(float(values[key])):
                raise ValueError('Clip is silent or too short for reliable loudness measurement')
        return values
    except (KeyError, json.JSONDecodeError) as exc:
        raise ValueError('Could not read FFmpeg loudness measurements') from exc


def normalize(source, destination, ffmpeg='ffmpeg', start=0, duration=None):
    source, destination = Path(source).resolve(), Path(destination).resolve()
    if source == destination or destination.exists():
        raise ValueError(f'Will not overwrite {destination.name}; choose a new output folder')
    if not math.isfinite(start) or start < 0:
        raise ValueError('Start must be a finite number of seconds, zero or greater')
    if duration is not None and (not math.isfinite(duration) or not 1 <= duration <= 60):
        raise ValueError('Duration must be between 1 and 60 seconds')
    destination.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix='djtable-normalize-') as folder:
        decoded, prepared, matched = (Path(folder) / name for name in ('decoded.wav', 'prepared.wav', 'matched.wav'))
        # Decode at most 61 seconds, bounding temporary files even for long inputs.
        # A longer source is rejected unless the user explicitly selects a clip.
        run(ffmpeg, '-v', 'error', '-i', source, '-ss', start, '-t', duration or 61,
            '-map', '0:a:0', '-vn', '-map_metadata', '-1', '-ar', '48000', '-ac', '1',
            '-c:a', 'pcm_s16le', decoded)
        with wave.open(str(decoded), 'rb') as wav:
            seconds = wav.getnframes() / wav.getframerate()
        if not 1 <= seconds <= 60:
            raise ValueError('Choose a 1–60 second clip; use --start and --duration to select part of a longer song')
        # Measure the exact mono excerpt including its edge fades in both passes.
        run(ffmpeg, '-v', 'error', '-i', decoded, '-af',
            f'afade=t=in:d=0.01,afade=t=out:st={seconds-.015}:d=0.015',
            '-c:a', 'pcm_s16le', prepared)
        before = measure(ffmpeg, prepared)
        fields = [('measured_I', 'input_i'), ('measured_TP', 'input_tp'),
                  ('measured_LRA', 'input_lra'), ('measured_thresh', 'input_thresh'), ('offset', 'target_offset')]
        measurements = ':'.join(f'{name}={before[key]}' for name, key in fields)
        run(ffmpeg, '-v', 'error', '-i', prepared, '-af', TARGET + ':' + measurements + ':linear=true',
            '-map_metadata', '-1', '-ar', '48000', '-ac', '1', '-c:a', 'pcm_s16le', matched)
        after = measure(ffmpeg, matched)
        warning = None
        if abs(float(after['input_i']) + 16) > .5 or float(after['input_tp']) > -1.3:
            warning = 'Output is outside target tolerance; review this clip before using it'
        # Exclusive creation protects existing files even if another process creates
        # the destination while FFmpeg runs. Sources are never opened for writing.
        with destination.open('xb') as output, matched.open('rb') as incoming:
            shutil.copyfileobj(incoming, output)
    return {'source': source.name, 'output': destination.name, 'seconds': seconds,
            'input_lufs': float(before['input_i']), 'output_lufs': float(after['input_i']),
            'output_true_peak_dbtp': float(after['input_tp']), 'warning': warning}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('input', type=Path, help='One audio file or a folder (not recursive)')
    parser.add_argument('--output', required=True, type=Path, help='Separate destination folder')
    parser.add_argument('--kind', choices=('song', 'backing'), default='song', help='Backing files get 01_, 02_ prefixes')
    parser.add_argument('--start', type=float, default=0, help='Start offset in seconds')
    parser.add_argument('--duration', type=float, help='Explicitly extract this many seconds (1–60)')
    parser.add_argument('--ffmpeg', default='ffmpeg', help='FFmpeg executable name or path')
    args = parser.parse_args(argv)
    executable = shutil.which(args.ffmpeg)
    if not executable:
        parser.error('FFmpeg not found; install it and add it to PATH, or pass --ffmpeg')
    source = args.input.resolve()
    sources = sorted((p for p in source.iterdir() if p.is_file() and p.suffix.lower() in EXTENSIONS), key=lambda p: p.name.lower()) if source.is_dir() else [source]
    if not sources or any(not p.is_file() for p in sources):
        parser.error('No supported input files found')
    if args.output.resolve() == (source if source.is_dir() else source.parent):
        parser.error('Use a separate output folder so originals are preserved')
    if args.kind == 'backing' and len(sources) > 99:
        parser.error('A backing batch can contain at most 99 clips')
    names = [(f'{index:02d}_' if args.kind == 'backing' else '') + p.stem + '.wav' for index, p in enumerate(sources, 1)]
    if len({name.casefold() for name in names}) != len(names):
        parser.error('Two inputs have the same output name; rename them first')
    args.output.mkdir(parents=True, exist_ok=True)
    report = []
    for source, name in zip(sources, names):
        try:
            result = normalize(source, args.output / name, executable, args.start, args.duration)
            print(f'{name}: {result["seconds"]:.2f}s, {result["output_lufs"]:.1f} LUFS, {result["output_true_peak_dbtp"]:.1f} dBTP')
            if result['warning']:
                print('  WARNING:', result['warning'])
        except (OSError, ValueError, wave.Error) as exc:
            result = {'source': source.name, 'error': str(exc)}
            print(f'{source.name}: ERROR: {exc}')
        report.append(result)
    path = args.output / f'normalization-report-{uuid.uuid4().hex[:8]}.json'
    path.write_text(json.dumps(report, indent=2, ensure_ascii=False) + '\n', encoding='utf-8')
    print('Report:', path)
    return int(any(item.get('error') or item.get('warning') for item in report))


if __name__ == '__main__':
    raise SystemExit(main())
