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
    if mode in ('house', 'punk'):
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
    if mode == 'house':
        # Original, band-limited harmonic patches. Expensive synthesis happens
        # only in the loader; sustained playback uses the same lightweight loops.
        data = np.zeros(len(t))
        if tone == 'piano':
            # A thick octave-down Reese with moving harmonic notches.
            fundamental = phase * .5
            for h in range(1, min(30, int(rate*.38/(frequency*.5))) + 1):
                motion = .40*np.sin(2*np.pi*1.7*t)
                data += (np.sin(h*fundamental + motion*h*.16)
                         + np.sin(h*fundamental - motion*h*.19 + .25)) / (2*h**1.2)
            data += 1.1*np.sin(fundamental) + .25*np.sin(phase)
        elif tone == 'high':
            # Metallic FM-style growl: moving sideband strengths, bounded
            # below Nyquist by additive synthesis rather than raw distortion.
            for h in range(1, min(24, int(rate*.38/frequency)) + 1):
                formant = 3.0 + 2.0*np.sin(2*np.pi*2.4*t)
                weight = (.6/h + 1.2*np.exp(-.5*((h-formant)/1.6)**2))
                data += weight*np.sin(h*phase + .15*h)
            data *= .78 + .22*np.sin(2*np.pi*4.8*t)
            data += .9*np.sin(phase)
        else:
            # Bright fifth/octave rave stab; repeated held notes stay pitched.
            for ratio, gain in ((1, 1.0), (1.5, .45), (2, .3)):
                for h in range(1, min(16, int(rate*.38/(frequency*ratio))) + 1):
                    data += gain*np.sin(h*phase*ratio) / h**1.35
            data *= .5 + .5*np.exp(-t*12)
            data += .7*np.sin(phase)
    elif mode == 'punk':
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
