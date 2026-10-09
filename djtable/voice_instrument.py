"""Prepare a short microphone take off the audio thread; reuse held-note playback."""
import wave
from pathlib import Path

import numpy as np

from .core import COLOURS, load_wav, prime_audio_buffers, save_wav_atomic
from .instruments import InstrumentVoice, PENTATONIC, Patch

CAPTURE_SECONDS = 1.5
VOICE_TONES = {'piano': 0, 'high': 0, 'synth': -7}


def voice_character(take, rate, tone):
    """Render character/timbre once in the worker, before keyboard transposition."""
    original = np.asarray(take, dtype=np.float64)
    if tone == 'piano':
        return original
    t = np.arange(len(original), dtype=np.float64)/rate
    if tone == 'high':
        # Metallic sidebands and coarse sample/level stepping make a talking
        # robot. A little dry signal keeps consonants recognizable.
        held = original[(np.arange(len(original))//max(1, round(rate/6000))*max(1, round(rate/6000))).astype(int)]
        crushed = np.round(held*32)/32
        carrier = .75*np.cos(2*np.pi*90*t) + .25*np.cos(2*np.pi*135*t)
        changed = .12*original + .88*crushed*carrier
    else:
        # Saturation, asymmetric harmonics, a moving short comb/chorus and
        # throat flutter give a rough monster texture, beyond its lower pitch.
        driven = np.tanh(original*9)
        driven += .35*driven**2
        delay = rate*(.014+.004*np.sin(2*np.pi*4.5*t))
        echoed = np.interp(np.arange(len(original))-delay, np.arange(len(original)), driven, left=0)
        changed = (.55*driven+.45*echoed)*(.78+.22*np.cos(2*np.pi*32*t))
    changed -= changed.mean()
    # Nonlinear effects generate harmonics: band-limit before even the top
    # key's +16 semitones and the platter's +2-semitone bend.
    padding = min(round(rate*.05), len(changed)-1)
    padded = np.pad(changed, (padding, padding), mode='reflect')
    hz = np.fft.rfftfreq(len(padded), 1/rate)
    cutoff = min(6000, rate*.40 / 2**((18+VOICE_TONES[tone])/12))
    highpass = (hz/70)**4
    response = highpass/(1+highpass)/(1+(hz/cutoff)**12)
    changed = np.fft.irfft(np.fft.rfft(padded)*response, n=len(padded))[padding:padding+len(changed)].copy()
    desired = float(np.sqrt(np.mean(original*original)))
    rms = float(np.sqrt(np.mean(changed*changed)))
    changed *= min(32, desired/max(rms, 1e-8), .65/max(float(np.max(np.abs(changed))), 1e-8))
    fade = min(round(rate*.012), len(changed)//2)
    changed[:fade] *= np.linspace(0, 1, fade)
    changed[-fade:] *= np.linspace(1, 0, fade)
    return changed


def level_take(take):
    """Voice instrument level: close to the keyboard instruments, peaks below 0.8."""
    rms = float(np.sqrt(np.mean(take*take)))
    peak = float(np.max(np.abs(take)))
    return (take * min(32, .30 / max(rms, 1e-8), .80 / max(peak, 1e-8))).astype(np.float32)


def prepare_take(recording, rate):
    take = np.asarray(recording, dtype=np.float32)
    if take.ndim != 1 or not round(.1 * rate) <= len(take) <= round(CAPTURE_SECONDS * rate):
        raise ValueError('Record a short sound after the beep')
    if not np.isfinite(take).all():
        raise ValueError('Microphone supplied invalid audio; the previous voice is kept')
    take = take.copy()
    take -= take.mean()
    from .remix import remove_beep
    take = remove_beep(take, rate)
    # Smooth band limits before upsampling pitch. Leave room for the highest
    # key (+16 semitones) and platter (+2), so highs do not fold into the voice.
    padding = min(round(rate * .05), len(take) - 1)
    padded = np.pad(take, (padding, padding), mode='reflect')
    hz = np.fft.rfftfreq(len(padded), 1 / rate)
    highpass = (hz / 80) ** 4
    cutoff = min(6000, rate * .40 / 2 ** (18 / 12))
    response = highpass / (1 + highpass) / (1 + (hz / cutoff) ** 12)
    take = np.fft.irfft(np.fft.rfft(padded) * response, n=len(padded))[padding:padding+len(take)].astype(np.float32)
    window = max(1, round(.01 * rate))
    frames = len(take) // window
    levels = np.sqrt(np.mean(take[:frames*window].reshape(frames, window) ** 2, axis=1))
    # Gentle trim: soft word endings (s, f, fading vowels) sit far below the loudest
    # syllable, so only near-silence counts. The first 50 ms are ignored when finding
    # the start, in case the end of the beep's ring-down was caught.
    active = np.flatnonzero(levels >= max(.0005, float(levels.max()) * .02))
    active = active[active >= 5] if np.count_nonzero(active >= 5) >= 8 else active
    if len(active) < 8:
        raise ValueError('No clear sound heard. Speak closer after the beep; your previous voice is kept')
    start = max(0, (int(active[0])-4) * window)
    end = min(len(take), (int(active[-1])+15) * window)
    take = level_take(take[start:end].copy())
    fade_in = min(round(rate*.012), len(take)//4)
    fade_out = min(round(rate*.06), len(take)//3)
    take[:fade_in] *= np.linspace(0, 1, fade_in)
    take[-fade_out:] *= np.linspace(1, 0, fade_out) ** 2
    return take


def build_voice_patches(take, rate):
    """Pitch intervals are relative to the recording, not automatic tuning to C."""
    original = np.asarray(take, dtype=np.float64)
    grid = np.arange(len(original), dtype=np.float64)
    patches = {}
    for tone, shift in VOICE_TONES.items():
        source = voice_character(original, rate, tone)
        for colour, semitone in zip(COLOURS, PENTATONIC):
            pitched = np.interp(np.arange(0, len(source), 2 ** ((semitone+shift)/12)), grid, source).astype(np.float32)
            # Both ends are faded; holding repeats the whole utterance. Release
            # crossfades the current waveform into this silent tail in 20 ms.
            data = np.concatenate((pitched, np.zeros(max(1, round(rate*.04)), dtype=np.float32)))
            patches[tone, colour] = Patch(data, 0, len(pitched), rate)
    prime_audio_buffers(patches)
    scratch = np.zeros(512, dtype=np.float32)
    for patch in patches.values():
        voice = InstrumentVoice(patch)
        for bend in (1, 2**(2/12), 2**(-2/12)):
            scratch.fill(0)
            voice.mix(scratch, bend)
        voice.release()
        voice.mix(scratch)
    return patches


class VoiceInstrumentStore:
    def __init__(self, data_dir, rate):
        self.path = Path(data_dir) / 'voice_instrument' / 'take.wav'
        self.rate = rate

    def load(self):
        if not self.path.exists():
            return {}, 0.0
        with wave.open(str(self.path), 'rb') as wav:
            if (wav.getnframes() > round(CAPTURE_SECONDS * self.rate)
                    or wav.getframerate() != self.rate or wav.getnchannels() != 1
                    or wav.getsampwidth() != 2 or wav.getnframes() < round(.08*self.rate)):
                raise ValueError('Saved voice format or length is invalid; record a replacement')
        take = level_take(load_wav(self.path, self.rate))  # Older takes were saved quieter.
        return build_voice_patches(take, self.rate), len(take)/self.rate

    def create(self, recording):
        take = prepare_take(recording, self.rate)
        patches = build_voice_patches(take, self.rate)
        # The old on-disk take survives errors and interrupted writes. Publish
        # the new patches only after the replacement has been saved atomically.
        save_wav_atomic(self.path, take, self.rate)
        return patches, len(take)/self.rate
