"""Recording remix DSP and bounded disk storage, run outside the audio callback."""
import logging
from pathlib import Path
import random
import wave

import numpy as np

from .core import load_wav, save_wav_atomic


BEEP_HZ = 882.0  # The record prompt's beep.


def remove_beep(take, rate):
    """Notch out the prompt beep (and its first overtone): a trace of it can reach the
    microphone, and voice processing raises quiet takes by up to 30 dB."""
    take = np.asarray(take, dtype=np.float64)
    hz = np.fft.rfftfreq(len(take), 1 / rate)
    notch = np.ones_like(hz)
    for centre in (BEEP_HZ, 2 * BEEP_HZ):
        notch *= 1 - np.exp(-.5 * ((hz - centre) / 12) ** 2)  # About 30 Hz wide: far narrower than a voice.
    return np.fft.irfft(np.fft.rfft(take) * notch, n=len(take)).astype(np.float32)


def level_clip(data, target_rms=.22):
    """Lift quiet clips and gently compress peaks without hard clipping."""
    data = np.asarray(data, dtype=np.float32)
    rms = float(np.sqrt(np.mean(data * data))) if len(data) else 0.0
    gain = min(12.0, target_rms / max(rms, 1e-8))
    return (.95 * np.tanh(data * gain / .95)).astype(np.float32)


def clean_voice(recording, rate):
    """Speech-band filtered take with a minimum-level check (shared by remix and scratch)."""
    voice = np.asarray(recording, dtype=np.float32).copy()
    if not len(voice) or not np.isfinite(voice).all():
        raise ValueError('No usable microphone recording')
    voice -= voice.mean()
    voice = remove_beep(voice, rate)
    peak = float(np.max(np.abs(voice)))
    if peak < 0.00001:
        raise ValueError('Microphone recording was silent; check microphone wiring and channel')
    # Offline speech-band filtering: stop subsonic movement/DC drift and HF hiss
    # consuming the gain budget. Padding keeps the FFT's circular seam outside
    # the retained recording. Smooth responses avoid sharp cutoff ringing.
    padding = min(len(voice), round(rate * .1))
    padded = np.pad(voice, (padding, padding), mode='reflect')
    frequencies = np.fft.rfftfreq(len(padded), 1 / rate)
    highpass = (frequencies / 120) ** 4
    highpass = highpass / (1 + highpass)
    lowpass = 1 / (1 + (frequencies / min(6500, rate * .4)) ** 8)
    filtered_band = np.fft.irfft(np.fft.rfft(padded) * highpass * lowpass, n=len(padded))
    voice = filtered_band[padding:padding + len(voice)].astype(np.float32)
    frame_size = max(1, round(rate * .02))
    frames = len(voice) // frame_size
    levels = np.sqrt(np.mean(voice[:frames * frame_size].reshape(frames, frame_size) ** 2, axis=1)) if frames else np.array([])
    # A faint noise floor must not turn into a loud 'message'. This is a minimum
    # input-level check, not speech recognition; real speech still needs listening.
    if np.count_nonzero(levels >= .0001) * .02 < .10:
        raise ValueError('Microphone signal too weak: speak close to the uncovered sound hole and check connections')
    return voice


def make_remix(recording, beat, rate, seconds=16, repeats=4, pitch=2.0, voice=None):
    """Speed/pitch up speech, repeat it, and duck a smoothly looped backing."""
    if not len(beat):
        raise ValueError('No usable backing beat')
    if voice is None:
        voice = clean_voice(recording, rate)
    # Low-pass before speeding up to avoid folding high frequencies into speech.
    taps = np.arange(63) - 31
    cutoff = .45 / pitch
    kernel = 2 * cutoff * np.sinc(2 * cutoff * taps) * np.hamming(63)
    kernel /= kernel.sum()
    filtered = np.convolve(voice, kernel, mode='full')[31:31 + len(voice)]
    voice = np.interp(np.arange(0, len(voice), pitch), np.arange(len(voice)), filtered).astype(np.float32)
    rms = float(np.sqrt(np.mean(voice * voice)))
    gain = min(1024, .22 / max(rms, 1e-8), .8 / max(float(np.max(np.abs(voice))), 1e-8))
    logging.info('Filtered voice: rms=%.7f gain=%.1fx', rms, gain)
    voice *= gain
    fade = min(round(rate * .01), len(voice) // 2)
    if fade:
        voice[:fade] *= np.linspace(0, 1, fade)
        voice[-fade:] *= np.linspace(1, 0, fade)
    length = round(seconds * rate)
    bed = level_clip(beat, target_rms=.25)
    cross = min(round(rate * .01), len(bed) // 4)
    step = len(bed) - cross
    backing = np.zeros(length, dtype=np.float32)
    for start in range(0, length, step):
        part = bed[:min(len(bed), length - start)].copy()
        if cross and start:
            n = min(cross, len(part))
            part[:n] *= np.linspace(0, 1, cross)[:n]
        if cross and len(part) == len(bed):
            part[-cross:] *= np.linspace(1, 0, cross)
        backing[start:start + len(part)] += part
    speech = np.zeros(length, dtype=np.float32)
    duck = np.full(length, 1.0, dtype=np.float32)
    slot = (length - 2 * rate) // repeats
    if len(voice) > slot:
        raise ValueError('Recording is too long for four spaced repeats')
    for repeat in range(repeats):
        start = rate + repeat * slot
        end = start + len(voice)
        speech[start:end] += voice
        ramp = min(round(rate * .04), start, length - end)
        duck[start:end] = .45
        if ramp:
            duck[start-ramp:start] = np.linspace(1.0, .45, ramp)
            duck[end:end+ramp] = np.linspace(.45, 1.0, ramp)
    result = backing * duck + speech
    fade = min(round(rate * .03), length // 2)
    result[:fade] *= np.linspace(0, 1, fade)
    result[-fade:] *= np.linspace(1, 0, fade)
    result *= min(1, .95 / max(float(np.max(np.abs(result))), 1e-8))
    return result.astype(np.float32)


class RemixStore:
    """Remixes are one-and-done: each plays once after recording and is not kept."""
    def __init__(self, beats_dir, directory, rate, keep=5, prompt_path=None):
        self.rate = rate
        self.directory = Path(directory)
        self.beats = sorted(Path(beats_dir).glob('[0-9][0-9]_*.wav'))
        if not self.beats:
            raise ValueError(f'No numbered backing WAVs in {beats_dir}')
        # Load prompt once; a silent tail lets the beep and speaker ring-down finish before capture.
        self.prompt = np.concatenate((level_clip(load_wav(prompt_path or Path(beats_dir) / 'Voicemail Sound Effect.wav', rate)),
                                      np.zeros(round(rate * .45), dtype=np.float32)))  # Beep ring-down and output latency.
        self.last_beat = None

    @property
    def songs(self):
        return ()  # Nothing saved for the platter to replay.

    def create(self, recording):
        # Keep only the latest dry take for hardware/gain diagnosis.
        raw = np.asarray(recording, dtype=np.float32)
        logging.info('Microphone take: frames=%d peak=%.7f rms=%.7f mean=%.7f clipped=%d',
                     len(raw), float(np.max(np.abs(raw))), float(np.sqrt(np.mean(raw * raw))),
                     float(raw.mean()), int(np.count_nonzero(np.abs(raw) >= .99)))
        try:
            save_wav_atomic(self.directory.parent / 'last_recording.wav', raw, self.rate)
        except OSError:
            logging.exception('Could not save dry microphone diagnostic')
        choices = [path for path in self.beats if path != self.last_beat] or self.beats
        beat_path = random.choice(choices)
        remix = make_remix(recording, load_wav(beat_path, self.rate), self.rate)
        self.last_beat = beat_path
        return remix, (), beat_path.stem, None
