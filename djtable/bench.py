"""Silent PortAudio load check on the actual output device; optional concurrent microphone stream (not recorded).

Run with the DJTable service stopped. Exercises eight simultaneous voices and
retriggering while output volume is zero. Does not prove audible output/wiring.
"""
import argparse
from contextlib import ExitStack
from collections import deque
import math
import json
from pathlib import Path
import time
import sys

from .__main__ import read_config
from .core import COLOURS, TONES, Engine
from .library import Library, load_bank
from .audio import MicrophoneBridge


def main():
    import sounddevice as sd
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--config', default=str(Path(__file__).resolve().parents[1] / 'config.json'))
    parser.add_argument('--seconds', type=int, default=30)
    from .modes import MODES
    parser.add_argument('--mode', choices=tuple(MODES), default='teenage_disco')
    parser.add_argument('--activity', choices=('keyboard', 'voice', 'maker'), default='keyboard')
    parser.add_argument('--preload-modes', action='store_true', help='Retain all mode banks, as the live app does')
    args = parser.parse_args()
    if not 1 <= args.seconds <= 600:
        parser.error('--seconds must be 1..600')
    config = read_config(args.config)
    from .modes import Modes
    sys.setswitchinterval(.001)
    modes = Modes(config)
    _, bank, _ = modes.load(args.mode)
    if args.preload_modes:
        from .instruments import build_pack
        for mode in MODES:build_pack(config['sample_rate'], mode)
        # Exercise the bounded bank cache too, then release evicted banks.
        for mode in MODES:modes.load(mode)
        _, bank, _ = modes.load(args.mode)
    from .modes import trim_audio_heap
    trim_audio_heap()
    from .core import warm_audio_bank
    for _, (_, warm_bank, _) in modes.cache.values():
        warm_audio_bank(warm_bank, config['sample_rate'])
    if bank.errors:
        raise RuntimeError('Fix missing/invalid assets before running the bench check')
    engine = Engine(bank, config['sample_rate'], volume=0)
    if args.activity in ('voice', 'maker'):
        import numpy as np
        from .voice_instrument import prepare_take, build_voice_patches
        rate = config['sample_rate']
        t = np.arange(round(rate*1.5)) / rate
        take = prepare_take(.2*np.sin(2*np.pi*220*t)*(1+.3*np.sin(2*np.pi*4*t)), rate)
        engine.voice_patches = build_voice_patches(take, rate)
        engine.activity = 'voice'
    if args.activity == 'maker':
        from .music_maker import MakerBank, LoopSession, render_layer
        from .instruments import build_pack
        maker_bank = MakerBank(rate, build_pack(rate, 'teenage_disco')[0])
        engine.maker = LoopSession(rate, maker_bank)
        tracks = {}
        for level in (1, 2, 3):
            events = tuple((round(i*.5*rate), down, COLOURS[i%8], TONES[i%3]) for i in range(16) for down in (True,False))
            # Each held note lasts 0.25 seconds; drum releases are ignored.
            events = tuple((frame+(0 if down else round(rate*.25)),down,colour,tone) for frame,down,colour,tone in events)
            _, data = render_layer((level, events, engine.voice_patches, True), maker_bank, rate)
            tracks[level] = (data*32767).astype('<i2')
        engine.maker.set_tracks(tracks)
        engine.maker.playing = True
        engine.activity = 'maker'
        warm = np.zeros((512,2), dtype=np.float32)
        for level in (1,2,3):
            for colour in COLOURS: engine.submit('key',colour,'piano',level)
            for _ in range(8): engine.render(warm)
        engine.submit('release_keys')
        for _ in range(64): engine.render(warm)
    maximum_cpu = 0
    neutral_cpu = bend_cpu = 0
    neutral_status_blocks = 0
    presses = 0
    bridge = MicrophoneBridge(engine, max_frames=config['block_size'] or 4096, channels=config['input_channels'])
    status_events = []
    callback_times = deque(maxlen=256)
    import resource
    audio_origin = time.monotonic()
    def monitored_playback(output, frames, timing, status):
        began = time.monotonic()
        before = resource.getrusage(resource.RUSAGE_THREAD)
        if status and len(status_events) < 64:
            status_events.append({'seconds':round(time.monotonic()-audio_origin,3),'flags':str(status)})
        bridge.playback(output, frames, timing, status)
        after = resource.getrusage(resource.RUSAGE_THREAD)
        duration = time.monotonic()-began
        if duration > frames/config['sample_rate']*.5:
            callback_times.append((duration, began-audio_origin,
                                   after.ru_majflt-before.ru_majflt, after.ru_minflt-before.ru_minflt))
    with ExitStack() as stack:
        if config['capture_enabled']:
            stack.enter_context(sd.InputStream(device=config['input_device'], channels=config['input_channels'],
                dtype='float32', samplerate=config['sample_rate'], blocksize=config['block_size'],
                latency=.03, callback=bridge.capture))
        stream = stack.enter_context(sd.OutputStream(device=config['output_device'], channels=2, dtype='float32',
                         samplerate=config['sample_rate'], blocksize=config['block_size'],
                         latency=config.get('output_latency', .03),
                         callback=monitored_playback))
        start = time.monotonic()
        next_press = start
        while time.monotonic() - start < args.seconds:
            if not stream.active:
                raise RuntimeError('Audio callback stopped')
            elapsed = time.monotonic()-start
            engine.submit('platter', 0 if elapsed < args.seconds/2 else math.sin(elapsed*3))
            if time.monotonic() >= next_press:
                if args.activity != 'maker' and 'song' not in engine.voices:
                    engine.submit('song')
                for colour in COLOURS:
                    engine.submit('key', colour, TONES[(presses//3)%3], 1+presses%3 if args.activity == 'maker' else 3)
                presses += 1
                next_press += 0.4
            maximum_cpu = max(maximum_cpu, stream.cpu_load)
            if elapsed < args.seconds/2:
                neutral_cpu = max(neutral_cpu, stream.cpu_load)
                neutral_status_blocks = engine.status_count
            else:bend_cpu = max(bend_cpu, stream.cpu_load)
            time.sleep(0.005)
        result = dict(drum_samples=engine.maker.bank.drum_samples if engine.maker else 0, seconds=args.seconds, key_presses=presses * 8, activity=args.activity,
                      modes_cached=list(modes.cache), cached_audio_mib=round(modes.cache_bytes()/1048576,1),
                      songs_loaded=len(bank.songs), sample_rate=config['sample_rate'], block_size=config['block_size'],
                      output_device=config['output_device'], latency_seconds=stream.latency,
                      max_callback_cpu_fraction=maximum_cpu, neutral_cpu=neutral_cpu, bend_cpu=bend_cpu,
                      status_blocks=engine.status_count, neutral_status_blocks=neutral_status_blocks, dropped_commands=engine.dropped_commands,
                      status_events=list(status_events),
                      slowest_callbacks=[dict(milliseconds=round(duration*1000,3), seconds=round(at,3), major_faults=major, minor_faults=minor)
                                          for duration, at, major, minor in sorted(callback_times, reverse=True)[:10]],
                      input_status_blocks=bridge.input_status_count, input_dropped_blocks=bridge.dropped_blocks,
                      output_muted=True, physical_audio_verified=False)
    print(json.dumps(result, indent=2))
    return int(bool(engine.status_count or engine.dropped_commands or bridge.input_status_count or bridge.dropped_blocks))


if __name__ == '__main__':
    raise SystemExit(main())
