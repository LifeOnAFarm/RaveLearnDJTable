"""Preloaded sample mixer and callback-owned interaction state; no GPIO dependency."""
from collections import deque
from dataclasses import dataclass
from functools import lru_cache
import logging
import math
import os
import random
from pathlib import Path
import tempfile
import wave

import numpy as np

COLOURS = ('pink', 'red', 'orange', 'green', 'yellow', 'blue', 'purple', 'black')
TONES = ('piano', 'high', 'synth')
SYMBOLS = dict(zip(COLOURS, ('circle', 'heart', 'triangle', 'square', 'star', 'hexagon', 'moon', 'diamond')))
KEY_PINS = dict(zip(COLOURS, (5, 6, 12, 13, 16, 17, 22, 27)))
# Positions 1, 2, 3 in order, as wired on the DJTable PCB (slider contacts run high-to-low).
SLIDER_PINS = {'tone': (7, 24, 23), 'level': (8, 26, 25), 'volume': (15, 14, 9)}
MODE_PIN = 0  # Physical pin 27 (HAT ID_SD); each press selects the next Learning theme.
VOLUME_STEPS = (0.35, 0.65, 1.0)  # Fractions of the configured volume ceiling.
MUSIC_VOICES = ('song', 'remix', 'recording', 'voice_preview')


def load_wav(path, rate, pcm16=False):
    """Load PCM16 mono/stereo and resample once, retaining the original file.

    Linear interpolation is adequate for the initial 16k -> 48k bench pack.
    Downsampling is rejected rather than introducing unfiltered aliasing.
    """
    with wave.open(str(path), 'rb') as wav:
        channels, width, source_rate, frames, codec, _ = wav.getparams()
        if width != 2 or channels not in (1, 2) or codec != 'NONE' or not frames:
            raise ValueError(f'{path}: expected nonempty PCM16 mono/stereo WAV')
        if source_rate > rate:
            raise ValueError(f'{path}: preconvert {source_rate} Hz to {rate} Hz with an antialiasing resampler')
        raw = wav.readframes(frames)
        if len(raw) != frames * channels * width:
            raise ValueError(f'{path}: truncated PCM data')
    if pcm16 and channels == 1 and source_rate == rate:
        return np.frombuffer(raw, dtype='<i2')
    data = np.frombuffer(raw, dtype='<i2').reshape(-1, channels).mean(axis=1) / 32768.0
    if source_rate != rate:
        size = max(1, round(len(data) * rate / source_rate))
        data = np.interp(np.arange(size) * source_rate / rate, np.arange(len(data)), data)
    return (np.clip(data * 32768, -32768, 32767).astype('<i2') if pcm16 else np.asarray(data, dtype=np.float32))


@lru_cache(maxsize=64)
def _shared_key_sample(path, rate, modified_ns, size):
    """Share unchanged words/base notes across modes; never cache long songs."""
    data = load_wav(path, rate, pcm16=True)
    data.setflags(write=False)
    return data


def save_wav_atomic(path, data, rate):
    """Called by a worker, never the audio callback. Preserve last good recording."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(prefix=path.name + '.', suffix='.tmp', dir=path.parent)
    try:
        with os.fdopen(fd, 'wb') as handle:
            with wave.open(handle, 'wb') as wav:
                wav.setnchannels(1)
                wav.setsampwidth(2)
                wav.setframerate(rate)
                wav.writeframes((np.clip(data, -1, 32767 / 32768) * 32768).astype('<i2').tobytes())
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
        if os.name == 'posix':
            directory = os.open(path.parent, os.O_RDONLY | os.O_DIRECTORY)
            try:
                os.fsync(directory)
            finally:
                os.close(directory)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


class SampleBank:
    def __init__(self, root, rate, songs=(), overrides=None):
        self.sequences = {}
        self.symbol_sequences = {}
        self.songs = []
        self.errors = []
        self.override_errors = []
        root = Path(root)
        overrides = overrides or {}

        def read(relative, pcm16=False):
            try:
                path = Path(overrides.get(str(relative), root / relative))
                if pcm16:
                    return load_wav(path, rate, pcm16=True)
                stat = path.stat()
                return _shared_key_sample(str(path.resolve()), rate, stat.st_mtime_ns, stat.st_size)
            except (OSError, ValueError, wave.Error, EOFError) as exc:
                self.errors.append(str(exc))
                if str(relative) in overrides or Path(relative).is_absolute():
                    self.override_errors.append(str(exc))
                logging.warning('Sample skipped: %s', exc)
                return None

        words = {(lang, colour): read(f'colours/{lang}/{colour}.wav')
                 for lang in ('en', 'ga') for colour in COLOURS}
        symbols = {(lang, colour): read(f'symbols/{lang}/{colour}.wav')
                   for lang in ('en', 'ga') for colour in COLOURS}
        for tone in TONES:
            for colour in COLOURS:
                note = read(f'keys/{tone}/{colour}.wav')
                for level in (1, 2, 3):
                    parts = [] if note is None else [note]
                    if parts and level != 3:
                        parts += [words['en' if level == 1 else 'ga', colour]]
                    self.sequences[tone, level, colour] = tuple(p for p in parts if p is not None)
                    symbol_parts = [] if note is None else [note]
                    if symbol_parts and level != 3:
                        symbol_parts.append(symbols['en' if level == 1 else 'ga', colour])
                    self.symbol_sequences[tone, level, colour] = tuple(p for p in symbol_parts if p is not None)
        for song in songs:
            sample = read(song, pcm16=True)
            if sample is not None:
                self.songs.append(sample)


@dataclass
class Voice:
    parts: tuple
    part: int = 0
    offset: int = 0
    learning: bool = False
    bend_note: bool = False

    def mix(self, output, speed=1.0):
        cursor = 0
        while cursor < len(output) and self.part < len(self.parts):
            data = self.parts[self.part]
            scale = 1 / 32768 if data.dtype == np.dtype('int16') else 1.0
            step = speed if not self.learning or (self.bend_note and self.part == 0) else 1.0
            count = min(len(output) - cursor, max(0, int(np.ceil((len(data)-self.offset)/step))))
            if step == 1.0 and float(self.offset).is_integer():
                offset = int(self.offset)
                output[cursor:cursor + count] += data[offset:offset + count] * scale
            else:
                positions = self.offset + np.arange(count) * step
                index = positions.astype(np.int64)
                fraction = positions-index
                output[cursor:cursor + count] += (data[index]*(1-fraction)
                                                + data[np.minimum(index+1, len(data)-1)]*fraction) * scale
            cursor += count
            self.offset += count * step
            if self.offset >= len(data):
                self.part += 1
                self.offset = 0
        return self.part < len(self.parts)


class Engine:
    """CPython SPSC deques bridge main loop and callback without waiting on locks.

    submit() has ONE producer (the main loop). All state/voice changes belong to
    render(). This is a bench prototype, not a hard real-time DSP implementation.
    """
    def __init__(self, bank, rate=48000, volume=0.15, record_seconds=5, capture=False, mic_channel=0,
                 record_prompt=None, saved_songs=()):
        self.bank = bank
        self.rate = rate
        self.platter_target = self.platter_value = 0.0
        self.platter_frames = 0
        self.keyboard_gain = 1.0
        self.music_gain = 1.0
        self.retrigger_tails = []
        self.volume = volume
        self.volume_factor = 1.0
        self.capture = capture
        self.mic_channel = mic_channel
        self.commands = deque()
        self.completed = deque()
        self.voices = {}
        self.song_index = -1
        self.remix_index = -1
        self.platter_armed = True
        self.record_state = 'idle'
        self.record_buffer = np.zeros(round(rate * record_seconds), dtype=np.float32)
        self.record_frames = 0
        self.status_count = 0
        self.dropped_commands = 0
        self.last_learning_key = None
        self.learning_symbol = False
        self.record_prompt = record_prompt
        self.saved_songs = saved_songs
        self.record_error = None
        self.record_beat = None
        self.mode = 'teenage_disco'
        self.activity = 'keyboard'
        self.maker = None
        # Bluetooth mode: phone stream (set by main) and Level -> instrument set.
        self.bluetooth_audio = None
        self.bluetooth_instruments = {}
        self.announcements = {}  # name -> clip, from assets/announcements (set by main).
        # Platter: a spin in Learning with nothing playing plays a random scratch sample.
        self.scratch_samples = ()
        self.scratch_index = -1
        self.platter_armed = True
        self.level = 1
        self.voice_patches = {}
        self.voice_seconds = 0.0
        self.voice_error = None
        self.record_kind = 'remix'
        self.record_limit = len(self.record_buffer)
        # Allocate outside PortAudio. Large offline renders are chunked below.
        self._frames = np.arange(4096, dtype=np.float64)
        self._ramp = np.empty(4096, dtype=np.float64)
        self._tail = np.empty(4096, dtype=np.float32)

    def _gain_ramp(self, start, end, count):
        ramp = self._ramp[:count]
        np.multiply(self._frames[:count], (end-start)/max(1, count-1), out=ramp)
        ramp += start
        return ramp

    def recording_status(self):
        return dict(state=self.record_state, capture_enabled=self.capture,
                    saved_count=len(self.saved_songs), beat=self.record_beat, error=self.record_error,
                    kind=self.record_kind, seconds=self.record_limit/self.rate,
                    preview='voice_preview' in self.voices)

    def activity_status(self):
        return dict(active=self.activity, level=self.level, ready=bool(self.voice_patches),
                    seconds=round(self.voice_seconds, 2), error=self.voice_error,
                    maker=self.maker.status() if self.maker else None)

    def submit(self, *command):
        if len(self.commands) >= 64:
            self.dropped_commands += 1
            return False
        self.commands.append(command)
        return True

    def finish_recording(self):
        self.record_state = 'saving'
        self.completed.append(self.record_frames)

    def _play_key(self, colour, patch):
        """Start a held instrument note, or a one-shot sample (loop markers at the end)."""
        from .instruments import InstrumentVoice
        previous = self.voices.get(colour)
        if previous is not None and not getattr(previous, 'learning', False):
            self.retrigger_tails.append([previous, round(self.rate*.012)])
            self.retrigger_tails = self.retrigger_tails[-8:]
        one_shot = patch.loop_start >= len(patch.data)
        self.voices[colour] = Voice((patch.data,)) if one_shot else InstrumentVoice(patch)

    def _announce(self, name):
        clip = self.announcements.get(name)
        if clip is not None:
            self.voices['announcement'] = Voice((clip,))  # A newer announcement replaces an older one.

    def _command(self, command):
        kind, *args = command
        if kind == 'maker_ready':
            self.maker.retired.append((self.maker.tracks, self.maker.prepared))
            self.maker.tracks, self.maker.prepared = args
            self.maker.state, self.maker.error = 'idle', None
            return
        if kind == 'maker_failed':
            self.maker.state, self.maker.error = 'idle', args[0]
            return
        if kind == 'maker_settings':
            self.maker.quantize = bool(args[0])
            return
        if kind == 'announce':
            self._announce(args[0])
            return
        if kind == 'maker_action':
            if self.maker and not self.maker.busy() and self.record_state in ('idle', 'playing'):
                if args[0] == 'toggle': self.maker.playing = not self.maker.playing
                elif args[0] in ('clear', 'undo'):
                    if args[0] == 'clear':
                        self.maker.playing, self.maker.position = False, 0
                        self._announce('maker_all_deleted')
                    self.maker.jobs.append((args[0], None))
                    self.maker.state = 'preparing'
            return
        if kind in ('record_button', 'song_button'):
            if self.activity == 'maker' and self.record_state == 'idle':
                queued = len(self.maker.jobs)
                if self.maker.button(kind.split('_')[0], args[0], self.level, self.voice_patches):
                    self._command(('record',))
                for action, _ in list(self.maker.jobs)[queued:]:
                    if action in ('clear', 'clear_layer'):
                        self._announce('maker_all_deleted' if action == 'clear' else 'maker_layer_deleted')
            return
        if kind == 'level':
            if self.level != args[0]:
                # Bluetooth levels choose an instrument set, announced by its theme name.
                sets = {1: 'theme_punk', 2: 'theme_teenage_disco', 3: 'theme_house'}
                self._announce(sets[args[0]] if self.activity == 'bluetooth' else f'level_{self.activity}_{args[0]}')
            if self.maker and self.activity == 'maker' and self.level != args[0]: self.maker.finish()
            self.level = args[0]
            return
        if kind == 'activity':
            if self.record_state not in ('idle', 'playing') or args[0] not in ('keyboard', 'voice', 'maker', 'bluetooth') or (self.maker and self.maker.busy()):
                return  # Main retries when this capture/processing has finished.
            if self.activity != args[0]:
                previous_activity = self.activity
                self.activity = args[0]
                if self.maker:
                    self.maker.playing = False
                    self.maker.record_down = self.maker.song_down = None
                    self.maker.song_held = self.maker.clear_all_armed = False
                if {'maker', 'bluetooth'} & {previous_activity, self.activity}:
                    self.voices.clear()
                    self.retrigger_tails.clear()
                self._announce('mode_' + self.activity)
                for name in COLOURS if self.level == 3 else ():
                    voice = self.voices.get(name)
                    if hasattr(voice, 'release'):
                        voice.release()
                    else:
                        self.voices.pop(name, None)
                self.last_learning_key = None
            return
        if kind == 'mode':
            if self.activity == 'maker': return
            if self.record_state not in ('idle', 'playing'):
                return  # Main retries after capture/processing completes.
            self.mode, self.bank, self.record_prompt, self.saved_songs = args
            self.voices.clear()
            self.retrigger_tails.clear()
            self.last_learning_key = None
            self.learning_symbol = False
            self.song_index = self.remix_index = -1
            self.record_state = 'idle'
            self.record_error = self.record_beat = None
            self.platter_armed = False  # Require a fresh spin after mode selection.
            self._announce('theme_' + self.mode)
            return
        if kind == 'platter':
            value = float(args[0])
            self.platter_target = float(np.clip(value, -1, 1)) if np.isfinite(value) else 0.0
            self.platter_frames = 0
            magnitude = abs(self.platter_target)
            if magnitude < .03:
                self.platter_armed = True  # Slow down or stop before the next scratch.
            elif magnitude > .15 and self.platter_armed:
                self.platter_armed = False  # Consume the spin even while busy.
                if (self.activity == 'keyboard' and self.record_state == 'idle' and not self.voices
                        and not self.retrigger_tails and self.scratch_samples):
                    choices = [i for i in range(len(self.scratch_samples)) if i != self.scratch_index] or [0]
                    self.scratch_index = random.choice(choices)
                    self.voices['scratch'] = Voice((self.scratch_samples[self.scratch_index],))
            return
        if kind == 'key_up':
            if self.activity == 'maker': self.maker.event(False, args[0])
            voice = self.voices.get(args[0])
            if hasattr(voice, 'release'):
                voice.release()
            return
        if kind == 'release_keys':
            if self.activity == 'maker':
                for colour in COLOURS: self.maker.event(False, colour)
            for voice in self.voices.values():
                if hasattr(voice, 'release'):
                    voice.release()
            return
        if kind == 'volume':
            self.volume_factor = VOLUME_STEPS[args[0] - 1]
            return
        if kind == 'bank':
            if self.activity == 'maker': return
            self.bank = args[0]
            self.song_index = -1
            return  # Existing voices may finish using the previous sample data.
        if kind == 'record_saved':
            if self.record_state == 'saving':
                self.record_state = 'idle'
                if self.record_frames:
                    self.voices['recording'] = Voice((self.record_buffer[:self.record_frames],))
            return
        if kind == 'remix_ready':
            if self.record_state == 'saving':
                sample, _, self.record_beat, self.record_error = args  # One-and-done: nothing kept for replay.
                self.song_index = -1
                self.voices['remix'] = Voice((sample,))
                self.record_state = 'playing'
            return
        if kind == 'record_failed':
            if self.record_state == 'saving':
                self.record_error = args[0]
                if self.record_kind == 'voice':
                    self.voice_error = args[0]
                self.record_state = 'idle'
            return
        if kind == 'voice_ready':
            if self.record_state == 'saving' and self.record_kind == 'voice':
                self.voice_patches, self.voice_seconds = args
                self.voice_error = self.record_error = None
                # A single normal-pitch preview confirms the successful save.
                # It never joins the saved remix or random-song libraries.
                patch = self.voice_patches['piano', 'pink']
                self.voices['voice_preview'] = Voice((patch.data[:patch.loop_end],))
                self.record_state = 'playing'
            return
        if kind in ('song', 'record') and self.activity == 'bluetooth':
            return  # Song is play/pause on the phone (handled by main); no recording over phone music.
        if kind == 'song' and self.activity == 'maker':
            if self.record_state in ('idle', 'playing'): self.maker.playing = not self.maker.playing
            return
        if kind == 'song' and any(name in self.voices for name in MUSIC_VOICES):
            for name in MUSIC_VOICES:
                self.voices.pop(name, None)
            if self.record_state == 'playing':
                self.record_state = 'idle'
            return  # A stop press never starts another song.
        if kind == 'record' and (self.record_state == 'playing' or 'song' in self.voices):
            return  # Only Song stops music; capture remains protected.
        if kind == 'record':
            if self.activity == 'maker':
                if self.level != 3 or self.maker.busy(): return
                self.maker.playing = False
            if not self.capture:
                self.record_error = 'Microphone capture is not configured yet'
                return
            if self.record_state == 'idle':
                self.record_kind = 'voice' if self.activity in ('voice', 'maker') and self.level == 3 else 'remix'
                from .voice_instrument import CAPTURE_SECONDS
                self.record_limit = min(len(self.record_buffer), round(self.rate*CAPTURE_SECONDS)) if self.record_kind == 'voice' else len(self.record_buffer)
                if self.record_kind == 'voice':
                    self.voice_error = None
            if self.record_prompt is not None:
                if self.record_state != 'idle':
                    return
                self.voices.clear()
                self.retrigger_tails.clear()
                self.last_learning_key = None
                self.record_frames = 0
                self.record_error = None
                self.record_beat = None
                self.voices['prompt'] = Voice((self.record_prompt,))
                self.record_state = 'prompt'
                return
            if self.record_state == 'saving':
                return
            if self.record_state == 'recording':
                self.finish_recording()
            else:
                self.voices.clear()
                self.retrigger_tails.clear()
                self.last_learning_key = None
                self.record_frames = 0
                self.record_state = 'recording'
            return
        if self.record_state not in ('idle', 'playing'):
            return  # Keys/songs are ignored during capture and save, never queued for later.
        if kind == 'key':
            colour, tone, level = args
            self.level = level
            if self.activity == 'maker':
                if self.maker.state == 'counting': return
                voice = self.maker.bank.voice(level, tone, colour, self.voice_patches)
                if voice is None:
                    self.voice_error = 'Tap Record at Level 3 to capture a voice first'
                    return
                previous = self.voices.get(colour)
                if hasattr(previous, 'release'):
                    self.retrigger_tails.append([previous, round(self.rate*.012)])
                    self.retrigger_tails = self.retrigger_tails[-8:]
                self.voices[colour] = voice
                self.maker.event(True, colour, tone)
                return
            if self.activity == 'bluetooth':
                # Play along: sustained instruments, the set chosen by the Level slider.
                patch = self.bluetooth_instruments.get(level, {}).get((tone, colour))
                if patch is not None:
                    self._play_key(colour, patch)
                return
            sequences = self.bank.sequences
            if level in (1, 2):
                for name in tuple(self.voices):
                    if name not in MUSIC_VOICES:
                        del self.voices[name]
                self.retrigger_tails.clear()
                self.learning_symbol = not self.learning_symbol if colour == self.last_learning_key else False
                self.last_learning_key = colour
                if self.learning_symbol:
                    sequences = self.bank.symbol_sequences
            else:
                self.last_learning_key = None
                self.learning_symbol = False
                for name in tuple(self.voices):
                    if self.voices[name].learning:
                        del self.voices[name]
            instruments = getattr(self.bank, 'instruments', {})
            voice_activity = level == 3 and self.activity == 'voice'
            if voice_activity and (tone, colour) not in self.voice_patches:
                self.voice_error = 'Press Record and make a short sound after the beep'
                return
            if level == 3 and (voice_activity or (tone, colour) in instruments):
                # Fade the current waveform directly (a short retrigger tail), then start the new note.
                self._play_key(colour, self.voice_patches[tone, colour] if voice_activity else instruments[tone, colour])
            else:
                self.voices[colour] = Voice(sequences[tone, level, colour], learning=level != 3, bend_note=True)
        elif kind == 'song' and self.bank.songs:
            self.last_learning_key = None
            songs = self.bank.songs
            choices = [i for i in range(len(songs)) if i != self.song_index] or [0]
            self.song_index = random.choice(choices)
            self.voices['song'] = Voice((songs[self.song_index],))

    def render(self, output, input_data=None, status=False):
        if len(output) > len(self._frames):
            for start in range(0, len(output), len(self._frames)):
                end = start + len(self._frames)
                self.render(output[start:end], None if input_data is None else input_data[start:end],
                            status if start == 0 else False)
            return
        output.fill(0)
        if status:
            self.status_count += 1
        for _ in range(64):
            if not self.commands:
                break
            self._command(self.commands.popleft())
        if self.activity == 'maker': self.maker.advance(len(output))
        self.platter_frames += len(output)
        target = self.platter_target if self.platter_frames < self.rate * .25 else 0.0
        self.platter_value += (target-self.platter_value) * (1-math.exp(-len(output)/(self.rate*.07)))
        if abs(self.platter_value) < .0001 and target == 0:
            self.platter_value = 0.0
        if self.record_state == 'recording':
            if input_data is not None:
                count = min(len(input_data), self.record_limit - self.record_frames)
                self.record_buffer[self.record_frames:self.record_frames + count] = input_data[:count, self.mic_channel]
                self.record_frames += count
                if self.record_frames == self.record_limit:
                    self.finish_recording()
            return
        if self.record_state == 'saving':
            return
        phone = self.bluetooth_audio if self.activity == 'bluetooth' and self.bluetooth_audio and self.bluetooth_audio.ready() else None
        if self.record_state == 'idle' and not self.voices and not self.retrigger_tails and phone is None and not (self.activity == 'maker' and (self.maker.playing or self.maker.busy() or self.maker.click_voice)):
            self.keyboard_gain = self.music_gain = 1.0
            return  # Silent blocks need no mix ramps, clipping or channel copies.
        mono = output[:, 0]
        music = output[:, 1]
        if self.activity == 'maker': self.maker.mix(music, 1+.5*self.platter_value)
        streaming = phone is not None and phone.read(music)
        instrument_count = sum(hasattr(v, 'release') for v in self.voices.values())
        gain_target = 1 / max(1, instrument_count)**.5
        gain_start = self.keyboard_gain
        self.keyboard_gain += (gain_target-self.keyboard_gain) * (1-math.exp(-len(output)/(self.rate*.025)))
        note_speed = 1.0 if self.activity == 'maker' and self.maker.state in ('counting', 'capturing') else 2**(2*self.platter_value/12)
        music_speed = 1+.5*self.platter_value
        for name in tuple(self.voices):
            voice = self.voices[name]
            speed = 1.0 if name in ('prompt', 'voice_preview', 'announcement', 'scratch') else (music_speed if name in MUSIC_VOICES else note_speed)
            if self.activity == 'maker' and self.maker.state in ('counting', 'capturing') and name in COLOURS: speed = 1
            if not voice.mix(music if name in MUSIC_VOICES else mono, speed):
                del self.voices[name]
        remaining_tails = []
        for tail, remaining in self.retrigger_tails:
            count = min(len(mono), remaining)
            scratch = self._tail[:count]
            scratch.fill(0)
            tail.mix(scratch, note_speed)
            fade = self._ramp[:count]
            np.subtract(remaining, self._frames[:count], out=fade)
            fade /= max(1, round(self.rate*.012))
            scratch *= fade
            mono[:count] += scratch
            if remaining > count:
                remaining_tails.append([tail, remaining-count])
        self.retrigger_tails = remaining_tails
        if instrument_count:
            mono *= self._gain_ramp(gain_start, self.keyboard_gain, len(mono))
            # A soft knee only catches loud chord peaks; single notes retain level.
            loud = np.abs(mono) > .8
            mono[loud] = np.sign(mono[loud]) * (.8 + .18*np.tanh((np.abs(mono[loud])-.8)/.18))
        # Keep the song out of keyboard chord gain; gently duck it while keys
        # sound, then recover smoothly. No additional full-size mix allocation.
        keyboard_active = any(name in COLOURS for name in self.voices) or bool(self.retrigger_tails)
        # Music (songs, remixes, Bluetooth, loops) is not ducked under keys, so the two blend.
        mono += music
        if streaming or any(name in self.voices for name in MUSIC_VOICES) or (self.activity == 'maker' and self.maker.playing):
            loud = np.abs(mono) > .8
            mono[loud] = np.sign(mono[loud]) * (.8 + .18*np.tanh((np.abs(mono[loud])-.8)/.18))
        # Saturate before applying the volume cap, including with eight loud keys.
        np.clip(mono, -1, 1, out=mono)
        mono *= self.volume * self.volume_factor
        output[:, 1] = mono
        if self.record_state == 'prompt' and 'prompt' not in self.voices:
            self.record_state = 'recording'  # Capture begins in the next callback, after the beep.
        elif self.record_state == 'playing' and not any(name in self.voices for name in ('remix', 'voice_preview')):
            self.record_state = 'idle'


def warm_audio_bank(bank, rate):
    """Exercise lazy NumPy/mixer paths before PortAudio starts its deadlines.

    No hardware output, recording or filesystem writes. First-note and first-
    bend setup must happen here, not when a child presses a key.
    """
    prime_audio_buffers(bank)
    engine = Engine(bank, rate, volume=0)
    block = np.zeros((512, 2), dtype=np.float32)
    for tone in TONES:
        for colour in COLOURS:
            engine.submit('key', colour, tone, 3)
        engine.submit('song')
        for bend in (0, 1, -1):
            engine.submit('platter', bend)
            for _ in range(4):engine.render(block)
        engine.submit('release_keys')
        for _ in range(32):engine.render(block)


def prime_audio_buffers(*roots):
    """Touch each audio memory page in the loader, not on its first note/song.

    Loading other banks can evict earlier pages on a small Pi. A bounded cache
    makes room; this restores the selected bank before giving it to playback.
    """
    seen = set()
    def touch(value):
        if id(value) in seen:return
        seen.add(id(value))
        if isinstance(value, np.ndarray):
            if value.size:
                value.ravel()[::max(1,4096//value.itemsize)].sum()
                value.ravel()[-1].item()
        elif isinstance(value, dict):
            for item in value.values():touch(item)
        elif isinstance(value, (tuple,list)):
            for item in value:touch(item)
        elif hasattr(value,'__dict__') and not isinstance(value,Path):
            touch(vars(value))
    for root in roots:touch(root)


class Debouncer:
    def __init__(self, initial, seconds=0.030):
        self.value = self.candidate = initial
        self.since = 0.0
        self.seconds = seconds

    def update(self, raw, now):
        if raw != self.candidate:
            self.candidate, self.since = raw, now
        if raw != self.value and now - self.since >= self.seconds:
            self.value = raw
            return True
        return False


def slider_position(contacts, previous):
    """One of three separate contacts closes to GND; invalid gaps retain state."""
    if len(contacts) == 3 and sum(contacts) == 1:
        return contacts.index(True) + 1
    return previous
