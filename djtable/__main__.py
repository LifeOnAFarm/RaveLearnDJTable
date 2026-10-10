import argparse
from concurrent.futures import ThreadPoolExecutor
from contextlib import ExitStack
import json
import logging
import math
from pathlib import Path
import queue
import signal
import sys
import threading
import time
import wave

import numpy as np

from .core import (COLOURS, TONES, KEY_PINS, SLIDER_PINS, MODE_PIN, Debouncer, Engine, SampleBank,
                   load_wav, save_wav_atomic, slider_position)


def read_config(path):
    path = Path(path).resolve()
    config = json.loads(path.read_text(encoding='utf-8'))
    for field, low, high in (('sample_rate', 16000, 96000), ('block_size', 0, 4096),
                             ('input_channels', 1, 2), ('mic_channel', 0, 1)):
        value = config[field]
        if type(value) is not int or not low <= value <= high:
            raise ValueError(f'{field} must be an integer in {low}..{high}')
    for field, low, high in (('volume', 0, 1.0), ('record_seconds', 0.1, 30), ('debounce_ms', 1, 100)):
        value = config[field]
        if type(value) not in (int, float) or not math.isfinite(value) or not low <= value <= high:
            raise ValueError(f'{field} must be in {low}..{high}')
    for flag in ('musical_keyboard', 'platter_enabled', 'mute_amp_on_switch'):
        if flag in config and type(config[flag]) is not bool:
            raise ValueError(f'{flag} must be true or false')
    if config.get('platter_direction', 1) not in (-1, 1):
        raise ValueError('platter_direction must be -1 or 1')
    if type(config.get('platter_bus', 1)) is not int or not 0 <= config.get('platter_bus', 1) <= 10:
        raise ValueError('Invalid platter bus')
    if type(config['capture_enabled']) is not bool:
        raise ValueError('capture_enabled must be true or false')
    if config['mic_channel'] >= config['input_channels']:
        raise ValueError('mic_channel must be less than input_channels')
    if not isinstance(config['songs'], list) or any(not isinstance(s, str) for s in config['songs']):
        raise ValueError('songs must be a list of WAV paths relative to sample_root')
    for field in ('sample_root', 'recording_path'):
        config[field] = (path.parent / config[field]).resolve()
    config['library_dir'] = (path.parent / config.get('library_dir', 'data/library')).resolve()
    if 'record_prompt_path' in config:
        config['record_prompt_path'] = (path.parent / config['record_prompt_path']).resolve()
    if 'backing_beats_dir' in config:
        config['backing_beats_dir'] = (path.parent / config['backing_beats_dir']).resolve()
        config['remix_dir'] = (path.parent / config.get('remix_dir', 'data/remixes')).resolve()
    for field in ('house_beats_dir', 'punk_beats_dir', 'baby_raver_beats_dir'):
        if field in config:
            config[field] = (path.parent / config[field]).resolve()
    return config


# BCM GPIO number -> Raspberry Pi 40-pin header position.
HEADER_PIN = {0: 27, 2: 3, 3: 5, 4: 7, 5: 29, 6: 31, 7: 26, 8: 24, 9: 21, 10: 19, 11: 23, 12: 32, 13: 33,
              14: 8, 15: 10, 16: 36, 17: 11, 18: 12, 19: 35, 20: 38, 21: 40, 22: 15, 23: 16, 24: 18,
              25: 22, 26: 37, 27: 13}


class _Input:
    """One pull-up input read straight through lgpio; a switch to ground is 'pressed'."""
    __slots__ = ('lgpio', 'chip', 'pin')

    def __init__(self, lgpio, chip, pin):
        self.lgpio, self.chip, self.pin = lgpio, chip, pin

    @property
    def is_pressed(self):
        return self.lgpio.gpio_read(self.chip, self.pin) == 0


def open_inputs(stack, mapping):
    """Claim every switch input. lgpio directly sets up in a fraction of the ~1.2 s that
    gpiozero takes at boot; gpiozero remains the fallback (other boards, tests)."""
    try:
        import lgpio
        chip = lgpio.gpiochip_open(0)
    except Exception:
        from gpiozero import Button
        return {name: stack.enter_context(Button(pin, pull_up=True, bounce_time=None))
                for name, pin in mapping.items()}
    stack.callback(lgpio.gpiochip_close, chip)
    for pin in mapping.values():
        lgpio.gpio_claim_input(chip, pin, lgpio.SET_PULL_UP)
        stack.callback(lgpio.gpio_free, chip, pin)
    return {name: _Input(lgpio, chip, pin) for name, pin in mapping.items()}


class Controls:
    def __init__(self, stack, debounce_ms, web_controls=None):
        mapping = dict(KEY_PINS, song=10, record=11, mode=MODE_PIN)
        mapping.update({f'{name}_{position}': pin for name, pins in SLIDER_PINS.items()
                        for position, pin in enumerate(pins, 1)})
        self.buttons = open_inputs(stack, mapping)
        self.pins = mapping
        self.grounded_at = {}  # Input name -> last time it read grounded, for the Admin pin table.
        seconds = debounce_ms / 1000
        self.debounce = {name: Debouncer(False, seconds) for name in (*COLOURS, 'song', 'record')}
        self.sliders = {name: Debouncer((False, False, False), seconds) for name in SLIDER_PINS}
        self.mode_button = Debouncer(False, seconds)
        self.mode_presses = 0  # Short presses: next theme. Main consumes these; Controls has no Modes access.
        self.activity_presses = 0  # 5-second holds: next keyboard mode.
        self.mode_down_at = None
        self.mode_held = False
        self.last_button = None  # (name, monotonic time) for the Admin hardware test.
        self.song_down_at = None
        self.bluetooth_requests = []  # 'play_pause' / 'next' for the phone; main forwards them.
        self.tone = self.level = 1
        self.sent_level = 1
        self.volume = self.sent_volume = 3
        self.web_controls = web_controls
        self.next_web_check = 0
        self.web_requests = {}
        self.overrides = {}
        # Web overrides are for testing: one saved before this start is not reapplied,
        # so the physical switches are in charge after every restart.
        if web_controls:
            for name, request in web_controls.read().items():
                if isinstance(request, dict) and isinstance(request.get('request'), str):
                    self.web_requests[name] = request['request']

    def poll(self, now, engine):
        previous = (self.tone, self.level)
        if self.web_controls and now >= self.next_web_check:
            for name, request in self.web_controls.read().items():
                if name not in SLIDER_PINS or not isinstance(request, dict): continue
                position, identifier = request.get('position'), request.get('request')
                if type(position) is int and position in (1, 2, 3) and isinstance(identifier, str) and identifier != self.web_requests.get(name):
                    self.web_requests[name] = identifier
                    self.overrides[name] = position
            self.next_web_check = now + .1
        for name in SLIDER_PINS:
            raw = tuple(self._read(f'{name}_{position}', now) for position in (1, 2, 3))
            moved = self.sliders[name].update(raw, now)
            if moved and sum(self.sliders[name].value) == 1:
                self.overrides.pop(name, None)
            position = self.overrides.get(name, slider_position(self.sliders[name].value, getattr(self, name)))
            setattr(self, name, position)
        if previous != (self.tone, self.level) and any(d.value for n, d in self.debounce.items() if n in COLOURS):
            engine.submit('release_keys')
        if self.sent_level != self.level and engine.submit('level', self.level):
            self.sent_level = self.level
        if self.volume != self.sent_volume and engine.submit('volume', self.volume):
            self.sent_volume = self.volume
        # Mode button: tap = next theme (on release); hold 5 s = next keyboard mode (fires while held).
        if self.mode_button.update(self._read('mode', now), now):
            if self.mode_button.value:
                self.mode_down_at, self.mode_held = now, False
                self.last_button = ('mode', now)
            else:
                if self.mode_down_at is not None and not self.mode_held:
                    self.mode_presses += 1
                self.mode_down_at = None
        if self.mode_down_at is not None and not self.mode_held and now - self.mode_down_at >= 5:
            self.mode_held = True
            self.activity_presses += 1
        for name, debounce in self.debounce.items():
            if debounce.update(self._read(name, now), now):
                if debounce.value:
                    self.last_button = (name, now)
                if name in COLOURS:
                    engine.submit('key', name, TONES[self.tone - 1], self.level) if debounce.value else engine.submit('key_up', name)
                elif getattr(engine, 'activity', 'keyboard') == 'maker':
                    engine.submit(name+'_button', debounce.value)
                elif getattr(engine, 'activity', 'keyboard') == 'bluetooth':
                    # Song: tap for play/pause on the phone, hold for the next track. Record is off.
                    if name == 'song' and debounce.value:
                        self.song_down_at = now
                    elif name == 'song' and self.song_down_at is not None:
                        self.bluetooth_requests.append('next' if now - self.song_down_at >= .8 else 'play_pause')
                        self.song_down_at = None
                elif debounce.value:
                    engine.submit(name)


    def status(self):
        return {name: {'position': getattr(self, name), 'pins': list(pins),
                       'source': 'web' if name in self.overrides else 'hardware',
                       'grounded': [i + 1 for i, active in enumerate(self.sliders[name].value) if active],
                       'valid': sum(self.sliders[name].value) == 1}
                for name, pins in SLIDER_PINS.items()}

    def _read(self, name, now):
        grounded = self.buttons[name].is_pressed
        if grounded:
            self.grounded_at[name] = now
        return grounded

    def pin_status(self, now):
        """Every input as [name, BCM, header pin, grounded now, seconds since last grounded]."""
        rows = []
        for name, pin in self.pins.items():
            seen = self.grounded_at.get(name)
            rows.append([name, pin, HEADER_PIN.get(pin), bool(self.buttons[name].is_pressed),
                         None if seen is None else round(now - seen, 1)])
        return rows

    def button_status(self, now):
        held = [name for name, debounce in self.debounce.items() if debounce.value]
        if self.mode_button.value:
            held.append('mode')
        last = None if self.last_button is None else {
            'name': self.last_button[0], 'seconds_ago': round(now - self.last_button[1], 1)}
        return {'held': held, 'last': last, 'pins': self.pin_status(now)}


def console_reader(events):
    print('Commands: pink/red/orange/green/yellow/blue/purple/black; tone 1..3; level 1..3; volume 1..3; up pink (release a held key); song; record; quit', flush=True)
    try:
        for line in iter(input, None):
            events.put(line.strip().lower())
    except EOFError:
        events.put('quit')


def simulate(engine, destination, rate):
    """Deterministic audible render; no audio device, GPIO or microphone needed."""
    output = np.zeros((rate * 8, 2), dtype=np.float32)
    for start in range(0, len(output), 256):
        if start == 0:
            engine.submit('key', 'pink', 'piano', 2)
            engine.submit('key', 'blue', 'synth', 3)
        if start == (rate // 256) * 256:
            engine.submit('key', 'pink', 'high', 1)
        engine.render(output[start:start + 256])
    save_wav_atomic(destination, output[:, 0], rate)
    logging.info('Simulation written to %s', Path(destination).resolve())


def run(config, console):
    # The loader shares Python's GIL with the 10.7 ms audio callback. Yield
    # more often than the default 5 ms while parsing uncached sample archives.
    sys.setswitchinterval(.001)
    import sounddevice as sd
    from .modes import Modes
    modes = Modes(config)
    active_mode = modes.selected()
    # Fast start: keys and words now; the main loop then loads the full theme (songs)
    # in the background, because no library stamp has been recorded yet.
    library_stamp = None
    active_mode, bank, remixes = modes.load(active_mode, songs=False)
    # Other themes' instrument packs load in the background once sound is running.
    from .instruments import build_pack
    from .modes import trim_audio_heap
    trim_audio_heap()
    from .core import warm_audio_bank
    warm_audio_bank(bank, config['sample_rate'])
    if not any(bank.sequences.values()):
        raise ValueError('No playable keys found; check sample_root')
    engine = Engine(bank, config['sample_rate'], config['volume'], config['record_seconds'],
                    config['capture_enabled'], config['mic_channel'],
                    record_prompt=remixes.prompt if remixes else None,
                    saved_songs=remixes.songs if remixes else ())
    engine.mode = active_mode
    scratches = sorted((Path(__file__).resolve().parents[1] / 'assets/scratch').glob('*.wav'))
    engine.scratch_samples = tuple(load_wav(path, config['sample_rate']) for path in scratches)  # Platter spins in Learning.
    from .activities import Activities
    from .voice_instrument import VoiceInstrumentStore
    activities = Activities(modes.root)
    voice_store = VoiceInstrumentStore(modes.root, config['sample_rate'])
    engine.activity = activities.selected()
    try:
        engine.voice_patches, engine.voice_seconds = voice_store.load()
    except (OSError, ValueError, EOFError, wave.Error) as exc:
        logging.exception('Could not load the saved voice instrument')
        engine.voice_error = str(exc)
    from .music_maker import MakerBank, LoopSession, LayerStore, render_layer
    from .instruments import build_pack
    maker_bank = MakerBank(config['sample_rate'], build_pack(config['sample_rate'], 'teenage_disco')[0])
    # Spoken announcements (theme, keyboard mode, level, Bluetooth, Music Maker clears);
    # a missing clip is simply silent. File name = event name, e.g. theme_punk.wav.
    for clip in sorted((Path(__file__).resolve().parents[1] / 'assets/announcements').glob('*.wav')):
        try:
            engine.announcements[clip.stem] = load_wav(clip, config['sample_rate'])
        except (OSError, ValueError, EOFError, wave.Error) as exc:
            logging.warning('Announcement skipped: %s', exc)
    engine.maker = LoopSession(config['sample_rate'], maker_bank)
    layer_store = LayerStore(modes.root, config['sample_rate'])
    try:
        engine.maker.set_tracks(layer_store.load())
    except (OSError, ValueError, EOFError, wave.Error) as exc:
        logging.exception('Could not load Music Maker layers')
        engine.maker.error = str(exc)
    maker_future = None
    maker_request = activities.maker_settings().get('request')
    engine.maker.quantize = activities.maker_settings().get('quantize', True)
    sent_quantize = engine.maker.quantize
    def prepare_layers(action, payload):
        if action == 'render':
            payload = render_layer(payload, maker_bank, config['sample_rate'])
            action = 'save'
        tracks = layer_store.apply(action, payload)
        prepared = LoopSession(config['sample_rate'], maker_bank)
        prepared.set_tracks(tracks)
        return tracks, prepared.prepared
    quit_event = threading.Event()
    for sig in (signal.SIGINT, signal.SIGTERM):
        signal.signal(sig, lambda *_: quit_event.set())
    events = queue.Queue(maxsize=64)
    tone = level = 1
    future = None
    future_kind = None
    reload_future = None
    pending_bank = None
    loading_stamp = None
    mode_error = None
    applying = False
    # Stopping the stream makes the voiceHAT driver pull SD_MODE (BCM4) low,
    # shutting the MAX98357A down while a new mode loads from the SD card.
    mute_on_switch = config.get('mute_amp_on_switch', True)
    switch_muted = False
    muted_at = 0
    next_status = 0
    next_library_check = 0
    next_activity_check = 0
    last_report = time.monotonic()
    with ExitStack() as stack:
        worker = stack.enter_context(ThreadPoolExecutor(max_workers=1))
        from .settings import WebControls
        controls = None if console else Controls(stack, config['debounce_ms'], WebControls(config['library_dir'].parent))
        platter = None
        next_platter = 0
        if config.get('platter_enabled', True):
            from .platter import Platter
            platter = stack.enter_context(Platter(config.get('platter_bus', 1), config.get('platter_direction', 1)))
        options = dict(samplerate=config['sample_rate'], blocksize=config['block_size'],
                       dtype='float32', latency=config.get('output_latency', .03))
        sd.check_output_settings(device=config['output_device'], channels=2,
                                 dtype='float32', samplerate=config['sample_rate'])
        input_stream = None
        bridge = None
        if config['capture_enabled']:
            sd.check_input_settings(device=config['input_device'], channels=config['input_channels'],
                                    dtype='float32', samplerate=config['sample_rate'])
            if config.get('independent_input', False):
                from .audio import MicrophoneBridge
                bridge = MicrophoneBridge(engine, max_frames=config['block_size'] or 4096, channels=config['input_channels'])
                input_options = dict(options, latency=.03)
                input_stream = stack.enter_context(sd.InputStream(
                    **input_options, device=config['input_device'],
                    channels=config['input_channels'], callback=bridge.capture))
                stream = sd.OutputStream(**options, device=config['output_device'], channels=2,
                                         callback=bridge.playback)
            else:
                stream = sd.Stream(**options, device=(config['input_device'], config['output_device']),
                                   channels=(config['input_channels'], 2),
                                   callback=lambda inp, out, frames, timing, status: engine.render(out, inp, status))
        else:
            stream = sd.OutputStream(**options, device=config['output_device'], channels=2,
                                     callback=lambda out, frames, timing, status: engine.render(out, status=status))
        stack.enter_context(stream)
        from .bluetooth import BluetoothAudio, BluetoothManager
        bluetooth = BluetoothManager(BluetoothAudio(config['sample_rate']))
        engine.bluetooth_audio = bluetooth.audio
        bluetooth.start()
        def warm_other_packs():
            # Fast start: these are only needed for theme switches and Bluetooth play-along
            # (Level 1/2/3 = Punk / Teenage Disco / House instruments).
            for other_mode in modes.libraries:
                build_pack(config['sample_rate'], other_mode)
            engine.bluetooth_instruments = {level: build_pack(config['sample_rate'], name)[0]
                                            for level, name in ((1, 'punk'), (2, 'teenage_disco'), (3, 'house'))}
        packs_pending = True  # Queued after the active theme's songs, which matter sooner.
        bluetooth_device = None
        logging.info('Audio running: rate=%s, latency=%s, capture=%s', config['sample_rate'], stream.latency, engine.capture)
        if console:
            threading.Thread(target=console_reader, args=(events,), daemon=True).start()
        try:
            while not quit_event.is_set():
                if not stream.active and not switch_muted:
                    raise RuntimeError('Audio callback stopped unexpectedly; see preceding error')
                if input_stream is not None and not input_stream.active:
                    raise RuntimeError('Microphone stream stopped unexpectedly')
                if bridge is not None and bridge.input_stalled():
                    raise RuntimeError('Microphone supplied no audio for three seconds; restarting audio')
                if controls:
                    controls.poll(time.monotonic(), engine)
                    if controls.mode_presses:
                        presses, controls.mode_presses = controls.mode_presses, 0
                        # Themes only affect Learning; capture/processing stay protected.
                        if engine.activity == 'keyboard' and engine.record_state in ('idle', 'playing') and future is None:
                            from .modes import MODES
                            order = list(MODES)
                            choice = order[(order.index(modes.selected()) + presses) % len(order)]
                            modes.select(choice)  # Same path as the web page, so the amp mute applies.
                            logging.info('Mode button: selected %s', choice)
                    if controls.activity_presses:
                        controls.activity_presses = 0
                        if engine.record_state in ('idle', 'playing') and future is None:
                            from .activities import ACTIVITIES
                            order = list(ACTIVITIES)
                            choice = order[(order.index(engine.activity) + 1) % len(order)] if engine.activity in order else order[0]
                            activities.select(choice)
                            logging.info('Mode button held: keyboard mode %s', choice)
                if platter and not switch_muted and time.monotonic() >= next_platter:
                    engine.submit('platter', platter.status()['value'])
                    next_platter = time.monotonic() + .02
                for _ in range(64):
                    try:
                        line = events.get_nowait()
                    except queue.Empty:
                        break
                    if line in COLOURS:
                        engine.submit('key', line, TONES[tone - 1], level)
                    elif line.startswith('up ') and line[3:] in COLOURS:
                        engine.submit('key_up', line[3:])
                    elif line in ('song', 'record'):
                        if line == 'record' and not engine.capture:
                            logging.warning('Recording disabled; configure and verify duplex audio first')
                        elif line == 'song' and not bank.songs and not engine.saved_songs:
                            logging.warning('No songs configured')
                        engine.submit(line)
                    elif line in ('quit', 'exit'):
                        quit_event.set()
                    elif line in ('tone 1', 'tone 2', 'tone 3'):
                        tone = int(line[-1])
                    elif line in ('level 1', 'level 2', 'level 3'):
                        level = int(line[-1])
                        engine.submit('release_keys')
                        engine.submit('level', level)
                    elif line in ('activity keyboard', 'activity voice', 'activity maker'):
                        activities.select(line.split()[1])
                    elif line in ('volume 1', 'volume 2', 'volume 3'):
                        engine.submit('volume', int(line[-1]))
                    else:
                        logging.warning('Unknown command: %s', line)
                engine.maker.retired.clear()  # Free old track buffers outside PortAudio.
                if engine.maker.jobs and maker_future is None:
                    action, payload = engine.maker.jobs.popleft()
                    maker_future = worker.submit(prepare_layers, action, payload)
                if maker_future is not None and maker_future.done():
                    try: maker_completion = ('maker_ready', *maker_future.result())
                    except Exception as exc:
                        logging.exception('Music Maker processing failed')
                        maker_completion = ('maker_failed', str(exc))
                    if engine.submit(*maker_completion): maker_future = None
                if engine.completed and future is None:
                    count = engine.completed.popleft()
                    # Callback freezes this buffer until main submits record_saved.
                    if count:
                        future_kind = engine.record_kind
                        if future_kind == 'voice':
                            future = worker.submit(voice_store.create, engine.record_buffer[:count])
                        else:
                            future = (worker.submit(remixes.create, engine.record_buffer[:count]) if remixes else
                                      worker.submit(save_wav_atomic, config['recording_path'],
                                                    engine.record_buffer[:count], config['sample_rate']))
                    if not count:
                        engine.submit('record_failed', 'No audio captured')
                if future is not None and future.done():
                    try:
                        result = future.result()
                        completion = (('voice_ready', *result) if future_kind == 'voice' else
                                      ('remix_ready', *result) if remixes else ('record_saved',))
                    except Exception as exc:
                        logging.exception('Recording processing failed')
                        completion = ('record_failed', str(exc))
                    if engine.submit(*completion):
                        future = None
                now = time.monotonic()
                if now >= next_activity_check:
                    settings = activities.maker_settings()
                    quantize = settings.get('quantize', True)
                    if quantize != sent_quantize and engine.submit('maker_settings', quantize): sent_quantize = quantize
                    if settings.get('request') != maker_request and engine.activity == 'maker' and not engine.maker.busy() and engine.record_state in ('idle', 'playing'):
                        if not settings.get('action') or engine.submit('maker_action', settings['action']): maker_request = settings.get('request')
                    selected_activity = activities.selected()
                    if engine.activity != selected_activity and engine.record_state in ('idle', 'playing'):
                        engine.submit('activity', selected_activity)
                    next_activity_check = now + .1
                bluetooth.wanted = engine.activity == 'bluetooth'
                if bluetooth.device and bluetooth.device != bluetooth_device:
                    engine.submit('announce', 'bluetooth_connected')
                bluetooth_device = bluetooth.device
                if controls and controls.bluetooth_requests:
                    bluetooth.requests.extend(controls.bluetooth_requests)
                    controls.bluetooth_requests.clear()
                if bluetooth.timed_out:
                    bluetooth.timed_out = False
                    logging.info('Bluetooth: no phone connected; returning to Learning')
                    activities.select('keyboard')
                if controls and now >= next_status:
                    # RAM-backed runtime file; no SD writes and no work in the callback.
                    try:
                        from .status import publish
                        publish(controls.status(), config['volume'] * engine.volume_factor, recording=engine.recording_status(),
                                mode={'active': engine.mode, 'requested': modes.selected(), 'error': mode_error},
                                activity=engine.activity_status(),
                                buttons=controls.button_status(now),
                                platter=platter.status() if platter else None,
                                bluetooth=bluetooth.status(),
                                keyboard={'musical': config.get('musical_keyboard', False),
                                          'bend_semitones': round(2*engine.platter_value, 2),
                                          'playback_speed': round(1+.5*engine.platter_value, 2)})
                    except OSError:
                        logging.warning('Could not publish slider status')
                    next_status = now + 0.5
                if reload_future is not None and reload_future.done():
                    try:
                        pending_bank = reload_future.result()
                        mode_error = None
                    except Exception as exc:
                        mode_error = str(exc)
                        logging.exception('Library reload failed; retaining previous samples')
                    reload_future = None
                if pending_bank is not None:
                    selected, new_bank, new_remixes = pending_bank
                    if applying and engine.bank is new_bank:
                        if selected == active_mode:
                            pending_bank = (selected, new_bank, remixes)
                        active_mode, bank, remixes = pending_bank
                        library_stamp = loading_stamp
                        pending_bank = None
                        applying = False
                        logging.info('Mode/library ready: %s, %s songs', active_mode, len(bank.songs))
                        if packs_pending:
                            packs_pending = False
                            worker.submit(warm_other_packs)
                    elif not engine.commands and selected != modes.selected():
                        pending_bank = None  # Discard stale loads after rapid selections.
                        applying = False
                    elif engine.activity != 'maker' and engine.record_state in ('idle', 'playing') and future is None and not engine.commands:
                        # A capture that raced the previous submit may have rejected
                        # the switch. Retry only after capture has safely finished.
                        if selected == engine.mode:
                            applying = engine.submit('bank', new_bank)
                        else:
                            applying = engine.submit('mode', selected, new_bank,
                                                      new_remixes.prompt if new_remixes else None,
                                                      new_remixes.songs if new_remixes else ())
                if engine.activity != 'maker' and now >= next_library_check and reload_future is None and pending_bank is None:
                    selected = modes.selected()
                    stamp = modes.stamp(selected)
                    if selected != active_mode or stamp != library_stamp:
                        if (mute_on_switch and selected != active_mode and not switch_muted
                                and engine.record_state in ('idle', 'playing') and future is None):
                            stream.stop()
                            switch_muted, muted_at = True, now
                        loading_stamp = stamp
                        reload_future = worker.submit(modes.load, selected)
                    next_library_check = now + .1
                if switch_muted and (reload_future is None or now - muted_at > 10):
                    # The callback is stopped, so queue the switch now: the first
                    # callback applies it before mixing and the amp wakes silent.
                    if pending_bank is not None and not applying and pending_bank[0] != engine.mode:
                        selected, new_bank, new_remixes = pending_bank
                        # Callback is stopped, so main may safely drop stale notes
                        # and platter updates that would only be cleared by 'mode'.
                        kept = [c for c in engine.commands if c[0] not in ('key', 'key_up', 'platter')]
                        engine.commands.clear()
                        engine.commands.extend(kept)
                        applying = engine.submit('mode', selected, new_bank,
                                                 new_remixes.prompt if new_remixes else None,
                                                 new_remixes.songs if new_remixes else ())
                    if pending_bank is None or applying or now - muted_at > 10:
                        stream.start()
                        switch_muted = False
                        logging.info('Amp unmuted after %.2fs mode switch', now - muted_at)
                if now - last_report >= 10:
                    logging.info('Audio cpu=%.3f status_blocks=%s dropped_commands=%s record=%s',
                                 stream.cpu_load, engine.status_count, engine.dropped_commands, engine.record_state)
                    if bluetooth.audio.running:
                        logging.info('Bluetooth stream underruns=%s', bluetooth.audio.underruns)
                    if bridge:
                        logging.info('Microphone input_status_blocks=%s dropped_blocks=%s',
                                     bridge.input_status_count, bridge.dropped_blocks)
                    last_report = now
                quit_event.wait(0.005)
        finally:
            bluetooth.close()  # Radio off and helper released before exit.
            # Stop the callback before reading a partially recorded buffer.
            if not stream.stopped:
                stream.stop()
            if input_stream is not None:
                input_stream.stop()
            if engine.record_state in ('recording', 'saving') and engine.record_frames and future is None:
                worker.submit(save_wav_atomic, config['recording_path'],
                              engine.record_buffer[:engine.record_frames], config['sample_rate'])


def main():
    parser = argparse.ArgumentParser(description='Pi DJTable bench prototype')
    parser.add_argument('--config', default=str(Path(__file__).resolve().parents[1] / 'config.json'))
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument('--list-devices', action='store_true')
    mode.add_argument('--check-assets', action='store_true')
    mode.add_argument('--simulate', metavar='OUTPUT_WAV')
    mode.add_argument('--console', action='store_true', help='Use text commands instead of GPIO')
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO, format='%(asctime)s %(levelname)s %(message)s')
    try:
        if args.list_devices:
            import sounddevice as sd
            print(sd.query_devices())
            return 0
        config = read_config(args.config)
        if args.check_assets or args.simulate:
            bank = SampleBank(config['sample_root'], config['sample_rate'], config['songs'])
            if args.check_assets:
                logging.info('Asset check: %s errors, %s songs', len(bank.errors), len(bank.songs))
                return int(bool(bank.errors))
            if not any(bank.sequences.values()):
                raise ValueError('No playable key samples')
            simulate(Engine(bank, config['sample_rate'], config['volume']), args.simulate, config['sample_rate'])
        else:
            run(config, args.console)
        return 0
    except (OSError, ValueError, KeyError, ImportError, RuntimeError) as exc:
        logging.error('%s', exc)
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
