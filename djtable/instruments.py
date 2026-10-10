"""Offline-built instrument samples; lightweight looping voices at playback time.

The meow is an original formant-synthesized cat voice, not a downloaded recording.
Internal 'high' slot remains compatible with existing upload assignments.
"""
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path
import numpy as np

DIATONIC = (0, 2, 4, 5, 7, 9, 11, 12)
PENTATONIC = (0, 2, 4, 7, 9, 12, 14, 16)
NOTE_NAMES = ('C4', 'D4', 'E4', 'G4', 'A4', 'C5', 'D5', 'E5')
MODE_GAIN = {'punk': 10 ** (3.5 / 20)}  # Matches Punk to the other themes (tools/level_report.py).


@dataclass(frozen=True)
class Patch:
    data: np.ndarray
    loop_start: int
    loop_end: int
    rate: int
    grid: np.ndarray = field(init=False, repr=False)
    resample_data: np.ndarray = field(init=False, repr=False)
    loop_data: np.ndarray = field(init=False, repr=False)

    def __post_init__(self):
        # np.interp's native loop avoids Python-side index/fraction temporaries.
        # Supply float64 buffers once so it never converts the whole sample in
        # the callback. Separate loop endpoint preserves fractional wrap continuity.
        object.__setattr__(self, 'grid', sample_grid(len(self.data)))
        object.__setattr__(self, 'resample_data', self.data.astype(np.float64))
        # Correct the single loop-edge interval in _read instead of retaining
        # another full float64 copy of every patch for that one endpoint.
        object.__setattr__(self, 'loop_data', self.resample_data)


@lru_cache(maxsize=8)
def _grid_storage(count):
    # Keep the array writable even though callers treat it as immutable.
    # NumPy 2.2 on the Pi otherwise copies the whole grid inside np.interp
    # on every 512-frame block, rather than just interpolating those frames.
    return np.arange(count, dtype=np.float64)


def sample_grid(count):
    # Patches need different prefix lengths, not separate copies of 0,1,2,...
    # Power-of-two backing arrays bound retained storage across sample rates.
    return _grid_storage(1 << (count - 1).bit_length())[:count]


@lru_cache(maxsize=64)
def frame_positions(count):
    return np.arange(count,dtype=np.float64)


def _build(tone, semitone, rate, mode='teenage_disco'):
    if mode == 'punk':
        semitone -= 12  # Bass register, with harmonics audible on small speakers.
    frequency = 261.625565 * 2 ** (semitone / 12)
    # Exact integer periods make the sustain boundary phase-continuous.
    period = max(8, round(rate / frequency))
    frequency = rate / period
    attack = period * max(1, round(.28 * frequency))
    loop = 2 * period * max(1, round(.45 * frequency / 2))
    release = round(rate * (.28 if tone == 'high' else .20))
    end = attack + loop
    t = np.arange(end + release) / rate
    phase = 2 * np.pi * frequency * t
    if mode == 'punk':
        # Plucked-string harmonic decay and a quieter sustain bed. All partials
        # stay below Nyquist; crunch comes from harmonic weights, not clipping.
        data = np.zeros(len(t))
        intervals = ((1, 1.0), (1.5, .65), (2, .35)) if tone == 'synth' else ((1, 1.0),)
        for ratio, gain in intervals:
            for h in range(1, min(28, int(rate*.38/(frequency*ratio))) + 1):
                pick = np.sin(h*np.pi*.22)
                weight = pick / h**(1.8 if tone == 'piano' else 1.1)
                envelope = .20 + .80*np.exp(-t*(2.0+h*.65))
                data += gain*weight*envelope*np.sin(h*phase*ratio + .07*h)
        if tone != 'piano':
            data += .35*np.sin(phase) + .16*np.sin(3*phase)
    elif mode == 'baby_raver' and tone != 'high':
        data = np.zeros(len(t))
        if tone == 'piano':
            # Nasal, opening quack formant with a soft repeated wobble.
            formant = 900 + 450*np.exp(-t*12) + 90*np.sin(2*np.pi*5*t)
            for h in range(1, min(24, int(rate*.38/frequency)) + 1):
                weight = (.18/h + np.exp(-.5*((h*frequency-formant)/300)**2)/h**.3)
                data += weight*np.sin(h*phase)
            data *= .75 + .25*np.cos(2*np.pi*5*t)
        else:
            # Bouncy robot/toy voice: rounded odd harmonics, talking formant.
            for h in range(1, min(20, int(rate*.38/frequency)) + 1, 2):
                data += np.sin(h*phase)/h**1.6 * (1+.35*np.sin(2*np.pi*7*t+h*.5))
            data += .3*np.sin(2*phase)*np.exp(-t*7)
    elif tone == 'piano':
        # Tine-style electric piano: bright strike settles to a warm fundamental.
        brightness = 1.3 * np.exp(-t * 13) + .12
        data = np.sin(phase + brightness * np.sin(2 * phase))
        data += .13 * np.sin(3 * phase) * np.exp(-t * 8)
        data *= .60 + .40 * np.exp(-t * 5)
    elif tone == 'high':
        # 'Mee' attack opens to 'aa'; on release the formants close to 'ow'.
        opening = np.clip(t / .20, 0, 1)
        closing = np.clip((t - end / rate) / .22, 0, 1)
        f1 = (450 + 550 * opening) * (1 - closing) + 450 * closing
        f2 = (2600 - 1000 * opening) * (1 - closing) + 850 * closing
        data = np.zeros(len(t))
        for harmonic in range(1, min(24, int(rate * .38 / frequency))):
            hz = harmonic * frequency
            amplitude = (.16 / harmonic + 1.3 * np.exp(-.5*((hz-f1)/260)**2)
                         + .65 * np.exp(-.5*((hz-f2)/380)**2)) / harmonic**.35
            data += amplitude * np.sin(harmonic * phase)
    else:
        # Same vibrato, detuned saws and sub oscillator as sd_prep's learning
        # synth. Generate at its original 16 kHz then interpolate, preserving
        # the familiar timbre while the sustain/release remain musical.
        source_rate = 16000
        original_frequency = 261.625565 * 2 ** (semitone / 12)
        source_t = np.arange(int(np.ceil(len(t)*source_rate/rate))+2) / source_rate
        phase_a = np.cumsum(original_frequency * (1 + .006*np.sin(2*np.pi*5*source_t)) / source_rate)
        phase_b = original_frequency * 1.01 * (source_t + 1/source_rate)
        phase_sub = original_frequency * .5 * (source_t + 1/source_rate)
        source = ((2*(phase_a % 1)-1)*.48 + (2*(phase_b % 1)-1)*.20
                  + np.sin(2*np.pi*phase_sub)*.22)*.82
        data = np.interp(t, source_t, source)
    # Crossfade a short overlap into a repeating sustain. Handles the synth sub
    # oscillator and residual piano envelope without a discontinuity.
    cross = min(2 * period * max(1, round(.025 * frequency / 2)), loop // 4)
    data[end-cross:end] = (data[end-cross:end] * np.linspace(1, 0, cross)
                          + data[attack:attack+cross] * np.linspace(0, 1, cross))
    loop_start = attack + cross
    data[:round(rate*.008)] *= np.linspace(0, 1, round(rate*.008))
    data[end:] *= np.linspace(1, 0, release)**1.5
    peak = max(float(abs(data).max()), .001)
    rms = max(float(np.sqrt(np.mean(data[attack:end]**2))), .001)
    data *= min(.60 / peak, .22 / rms)
    return Patch(data.astype(np.float32), loop_start, end, rate)


@lru_cache(maxsize=4)
def build_pack(rate, mode='teenage_disco', prepared=True):
    from .core import COLOURS, TONES
    archive = Path(__file__).resolve().parents[1] / 'assets/instruments' / f'{mode}-{rate}-v2.npz'
    if prepared and archive.exists():
        held, short = {}, {}
        with np.load(archive, allow_pickle=False) as saved:
            for tone in TONES:
                for colour in COLOURS:
                    key = tone+'_'+colour
                    start, end = saved[key+'_loop']
                    gain = MODE_GAIN.get(mode, 1.0)
                    data, note = saved[key], saved[key+'_short']
                    if gain != 1.0:  # Soft-limited so the louder patch keeps its peaks in range.
                        data = (.85 * np.tanh(data * gain / .85)).astype(np.float32)
                        note = (.85 * np.tanh(note * gain / .85)).astype(np.float32)
                    held[tone, colour] = Patch(data, int(start), int(end), rate)
                    short[tone, colour] = note
        return held, short
    if mode == 'house':
        return _house_pack(rate)
    held, short = {}, {}
    for tone in TONES:
        for index, colour in enumerate(COLOURS):
            held[tone, colour] = _build(tone, PENTATONIC[index], rate, mode)
            patch = _build(tone, DIATONIC[index], rate, mode)
            voice = InstrumentVoice(patch)
            result = np.zeros(round(rate * .65), dtype=np.float32)
            split = round(rate * .32)
            voice.mix(result[:split])
            voice.release()
            voice.mix(result[split:])
            short[tone, colour] = result
    return held, short



# House: original synthesised sounds in F minor (no samples), laid out like a sample
# keyboard. Tone 1 plays a different chord on every key and Tone 3 a deep bass, both
# sustained while held; Tone 2 is a short chord stab that always rings out (one-shot).
HOUSE_STEPS = (0, 3, 5, 7, 10, 12, 15, 17)  # F minor pentatonic: F Ab Bb C Eb F Ab Bb
HOUSE_CHORDS = ((0, 3, 7, 10), (3, 7, 10, 14), (5, 8, 12, 15), (7, 10, 14, 17),  # Fm7 Abmaj7 Bbm7 Cm7
                (8, 12, 15, 19), (10, 14, 17, 20), (12, 15, 19, 22), (15, 19, 22, 26))  # Dbmaj7 Eb7 Fm7 Abmaj7
HOUSE_LOUDNESS = .228  # Teenage Disco instruments, measured as below.


def _house_loudness(x, rate):
    """RMS above ~150 Hz over the first 0.6 s: roughly what a small speaker plays."""
    body = x[:round(rate * .6)]
    hz = np.fft.rfftfreq(len(body), 1 / rate)
    weight = (hz / 150) ** 4 / (1 + (hz / 150) ** 4)
    return float(np.sqrt(np.mean(np.fft.irfft(np.fft.rfft(body) * weight, n=len(body)) ** 2)))


def _house_organ(freqs, t, rate, decay):
    """Classic house organ/piano: a bright strike over a drawbar-like sustain."""
    data = np.zeros(len(t))
    for index, f in enumerate(freqs):
        phase = 2 * np.pi * f * t * (1 + .0007 * (index - 1.5))  # Slight spread across the voices.
        for h, gain in ((1, 1.0), (2, .55), (3, .3), (4, .22), (6, .12), (8, .08)):
            if h * f < rate * .4:
                data += gain * np.sin(h * phase) * (.55 + .45 * np.exp(-t * decay * h ** .5))
    return data / len(freqs)


def _house_sustain(data, rate, start, size):
    """Loop data[start:start+size] seamlessly at a steady level; returns (data, start, end)."""
    window = max(1, round(rate * .02))
    env = np.sqrt(np.convolve(data * data, np.ones(window) / window, 'same'))
    end, cross = start + size, int(size * .4)
    gain = np.clip(env[start] / np.maximum(env, 1e-5), 1, 4)
    gain = np.convolve(gain, np.ones(480) / 480, 'same')
    data = data.copy()
    data[start - cross:end] *= gain[start - cross:end]
    data[end:] *= gain[end]  # The release continues from the held level.
    ramp = np.linspace(0, 1, cross)
    data[end - cross:end] = data[end - cross:end] * (1 - ramp) + data[start - cross:start] * ramp
    return data, start, end


@lru_cache(maxsize=2)
def _house_pack(rate):
    from .core import COLOURS
    f = 174.614  # F3
    held, short = {}, {}
    for index, colour in enumerate(COLOURS):
        step = HOUSE_STEPS[index]
        sounds = {}
        # Tone 1, House chords: 2.5 s, held at the level just after the strike.
        t = np.arange(round(rate * 2.5)) / rate
        chord = _house_organ([f * 2 ** (n / 12) for n in HOUSE_CHORDS[index]], t, rate, 6)
        chord *= np.exp(-t * .5)
        sounds['piano'] = _house_sustain(chord, rate, round(rate * .14), round(rate * .3))
        # Tone 2, Chord stabs: a minor-seventh stab, short and punchy, never looped.
        t = np.arange(round(rate * .55)) / rate
        stab = _house_organ([f * 2 ** ((step + n) / 12) for n in (0, 3, 7, 10)], t, rate, 14)
        stab *= np.exp(-t * 7) * (1 - np.exp(-t * 900))
        sounds['high'] = (stab, len(stab), len(stab))
        # Tone 3, Deep bass from F2: sine body with a little upper harmonic so small
        # speakers can hear it; the loop is a whole number of wave cycles.
        bass_f = f / 2 * 2 ** (step / 12)
        t = np.arange(round(rate * .95)) / rate
        phase = 2 * np.pi * bass_f * t
        bass = (np.sin(phase) + .45 * np.sin(2 * phase) * (.6 + .4 * np.exp(-t * 9))
                + .2 * np.sin(3 * phase) * np.exp(-t * 6) + .1 * np.sin(4 * phase) * np.exp(-t * 12))
        bass *= (.7 + .3 * np.exp(-t * 5)) * np.exp(-t * 1.2)
        period = rate / bass_f
        sounds['synth'] = _house_sustain(bass, rate, round(rate * .1), int(round(max(1, round(rate * .12 / period)) * period)))
        for tone, (data, start, end) in sounds.items():
            attack = round(rate * .003)
            data[:attack] *= np.linspace(0, 1, attack)
            tail = round(rate * .03)
            data[-tail:] *= np.linspace(1, 0, tail) ** 2
            target = HOUSE_LOUDNESS * (10 ** (2 / 20) if tone == 'synth' else 1)  # Bass +2 dB.
            for _ in range(3):  # Match loudness; a soft limiter rounds off the strike peaks.
                data = data * (target / max(_house_loudness(data, rate), 1e-6))
                data = .85 * np.tanh(data / .85)
            data = data.astype(np.float32)
            held[tone, colour] = Patch(data, start, end, rate)
            note = np.zeros(round(rate * .65), np.float32)  # Levels 1/2: the note before the word.
            head = data[:len(note)].copy()
            fade = min(len(head), round(rate * .06))
            head[-fade:] *= np.linspace(1, 0, fade)
            note[:len(head)] = head
            short[tone, colour] = note
    return held, short


class InstrumentVoice:
    learning = False

    def __init__(self, patch):
        self.patch = patch
        self.offset = 0.0
        self.released = False
        self.old_offset = 0.0
        self.cross_remaining = 0
        self.frames = 0

    def release(self):
        if not self.released:
            self.released = True
            self.old_offset = self.offset
            self.offset = float(self.patch.loop_end)
            self.cross_remaining = round(self.patch.rate * .02)

    def _read(self, start, count, speed, loop):
        if speed == 1.0 and float(start).is_integer():
            # Most playback is neutral: slice samples instead of allocating
            # interpolation positions, index and fraction arrays for every voice.
            result = np.zeros(count, dtype=np.float32)
            cursor, offset = 0, int(start)
            end = self.patch.loop_end if loop else len(self.patch.data)
            while cursor < count:
                if offset >= end:
                    if not loop:
                        break
                    offset = self.patch.loop_start + (offset-end) % (end-self.patch.loop_start)
                size = min(count-cursor, end-offset)
                result[cursor:cursor+size] = self.patch.data[offset:offset+size]
                cursor += size
                offset += size
            return result, float(offset)
        positions = start + frame_positions(count) * speed
        if loop:
            over = positions >= self.patch.loop_end
            positions[over] = self.patch.loop_start + (positions[over] - self.patch.loop_end) % (self.patch.loop_end-self.patch.loop_start)
        data = np.interp(positions, self.patch.grid,
                         self.patch.loop_data if loop else self.patch.resample_data,
                         left=0, right=0)
        if loop and start + (count - 1) * speed > self.patch.loop_end - 1:
            edge = positions > self.patch.loop_end - 1
            data[edge] += ((positions[edge] - (self.patch.loop_end - 1))
                          * (self.patch.data[self.patch.loop_start] - self.patch.data[self.patch.loop_end]))
        following = start + count * speed
        if loop and following >= self.patch.loop_end:
            following = self.patch.loop_start + (following-self.patch.loop_end) % (self.patch.loop_end-self.patch.loop_start)
        return data, following

    def mix(self, output, speed=1.0):
        # A lost physical release must not sustain a note forever.
        self.frames += len(output)
        if self.frames > self.patch.rate * 30:
            self.release()
        if speed == 1.0 and self.offset.is_integer() and not self.cross_remaining:
            # Add neutral samples directly, including wraps and silent release tails.
            # No temporary per-voice waveform is needed for this common path.
            cursor, offset = 0, int(self.offset)
            end = len(self.patch.data) if self.released else self.patch.loop_end
            while cursor < len(output):
                if offset >= end:
                    if self.released: break
                    offset = self.patch.loop_start + (offset-end) % (end-self.patch.loop_start)
                count = min(len(output)-cursor, end-offset)
                output[cursor:cursor+count] += self.patch.data[offset:offset+count]
                cursor += count
                offset += count
            self.offset = float(offset)
            return not self.released or self.offset < len(self.patch.data)-1
        data, self.offset = self._read(self.offset, len(output), speed, not self.released)
        if self.cross_remaining:
            count = min(len(output), self.cross_remaining)
            old, self.old_offset = self._read(self.old_offset, count, speed, True)
            total = max(1, round(self.patch.rate * .02))
            weight = np.arange(self.cross_remaining, self.cross_remaining-count, -1) / total
            data[:count] = old * weight + data[:count] * (1-weight)
            self.cross_remaining -= count
        output += data
        return not self.released or self.offset < len(self.patch.data)-1
