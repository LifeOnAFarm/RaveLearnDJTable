"""Prepared instruments and three sample-clocked loop layers."""
from collections import deque
import json
import logging
import wave as wave_module
from pathlib import Path
import uuid
import numpy as np
from .core import COLOURS, TONES, Voice, save_wav_atomic, load_wav
from .instruments import InstrumentVoice, PENTATONIC, _build, frame_positions
from .library import atomic_json

class MakerBank:
    def __init__(self, rate, learning, drum_root=None):
        self.melody = {}
        for colour, note in zip(COLOURS, PENTATONIC):
            self.melody['piano', colour] = learning['piano', colour]
            self.melody['high', colour] = learning['synth', colour]
            self.melody['synth', colour] = _build('synth', note-24, rate)
        self.drums = {}
        self.drum_names = dict(zip(TONES, ('Acoustic kit', 'Electronic kit', 'Fun percussion')))
        self.drum_samples = 0
        self.drum_errors = []
        root = Path(drum_root) if drum_root is not None else Path(__file__).resolve().parents[1]/'assets/drums/music_maker'
        manifest = root/'manifest.json'
        if manifest.exists():
            try:
                if manifest.stat().st_size > 65536: raise ValueError('Drum manifest is too large')
                definitions = json.loads(manifest.read_text(encoding='utf-8'))
                if definitions.get('sample_rate') == rate:
                    for tone in TONES:
                        kit = definitions['kits'].get(tone, {})
                        loaded = 0
                        for colour, name in kit.get('sounds', {}).items():
                            if colour not in COLOURS: continue
                            try:
                                path = (root/name).resolve()
                                if not path.is_relative_to(root.resolve()): raise ValueError('Drum path must stay inside the kit folder')
                                if path.stat().st_size > 4000000: raise ValueError('Drum file is too large')
                                data = load_wav(path, rate)
                                if not 1 <= len(data) <= rate*2: raise ValueError('Drum hits must be at most two seconds')
                                if not np.isfinite(data).all() or not np.any(data): raise ValueError('Invalid or silent drum hit')
                                self.drums[tone,colour] = data
                                self.drum_samples += 1
                                loaded += 1
                            except (OSError, ValueError, TypeError, wave_module.Error, EOFError) as exc:
                                self.drum_errors.append(f'{tone}/{colour}: {exc}')
                        if loaded: self.drum_names[tone] = str(kit.get('name', self.drum_names[tone]))[:80]
            except (OSError, ValueError, KeyError, TypeError, AttributeError) as exc:
                self.drum_errors.append(str(exc))
        rng = np.random.default_rng(431)
        for kit, tone in enumerate(TONES):
            for i, colour in enumerate(COLOURS):
                if (tone, colour) in self.drums: continue
                t = np.arange(round(rate*.65))/rate
                noise = rng.uniform(-1, 1, len(t))
                if i == 0:
                    wave = np.sin(2*np.pi*(45*t+8*(1-np.exp(-t*35))))*np.exp(-t*10)
                elif i == 1:
                    wave = (.65*noise+.35*np.sin(2*np.pi*180*t))*np.exp(-t*20)
                elif i in (2, 3):
                    wave = (noise-np.roll(noise, 1))*.4*np.exp(-t*(55 if i == 2 else 12))
                else:
                    freq = (110,155,340,700)[i-4]*(1+kit*.35)
                    wave = (np.sin(2*np.pi*freq*t)+.25*np.sin(2*np.pi*freq*1.47*t))*np.exp(-t*(12+i))
                if kit == 1: wave = np.tanh(wave*2)*.75
                if kit == 2: wave *= np.sin(2*np.pi*(220+90*i)*t)
                fade = round(rate*.002)
                wave[:fade] *= np.linspace(0,1,fade)
                self.drums[tone,colour] = np.asarray(wave*.65,dtype=np.float32)

        for error in self.drum_errors: logging.warning('Drum sample fallback: %s', error)

    def voice(self, level, tone, colour, patches):
        if level == 2: return Voice((self.drums[tone,colour],))
        patch = (self.melody if level == 1 else patches).get((tone,colour))
        return InstrumentVoice(patch) if patch is not None else None

def render_layer(request, bank, rate):
    level, events, patches, quantize = request
    length = rate*8
    if quantize:
        step = rate/8  # Sixteenth notes at 120 BPM.
        minimum = max(1, round(rate*.01))
        active, snapped = {}, []
        for frame, down, colour, tone in events:
            frame = max(0, min(length-1, round(round(frame/step)*step)))
            if down:
                frame = min(frame, length-minimum-1)
                active[colour] = frame
            elif colour in active:
                frame = max(frame, min(length-1, active.pop(colour)+minimum))
            snapped.append((frame, down, colour, tone))
        events = sorted(snapped, key=lambda e:e[0])
    # Long cymbals can finish across the boundary instead of being cut at 0.5 s.
    tail_frames = max(round(rate*.5), max(map(len, bank.drums.values())) if level == 2 else 0)
    out = np.zeros(length+tail_frames,dtype=np.float32)
    scratch = np.empty(512,dtype=np.float32)
    voices, tails = {}, []
    def mix_span(begin, end):
        for start in range(begin,end,512):
            stop = min(end,start+512)
            count = stop-start
            gain = 1/max(1,len(voices))**.5
            for name,voice in tuple(voices.items()):
                block = scratch[:count]
                block.fill(0)
                if not voice.mix(block,1): voices.pop(name,None)
                out[start:stop] += block*gain
            for tail in tails[:]:
                voice, remaining = tail
                size = min(count,remaining)
                block = scratch[:size]
                block.fill(0)
                alive = voice.mix(block,1)
                block *= np.arange(remaining,remaining-size,-1)/max(1,round(rate*.012))
                out[start:start+size] += block*gain
                tail[1] -= size
                if not alive or tail[1] <= 0: tails.remove(tail)
    cursor = 0
    for frame,down,colour,tone in list(events)+[(length,False,'*','')]:
        frame = max(cursor,min(length,frame))
        mix_span(cursor,frame)
        cursor = frame
        if colour == '*':
            for voice in voices.values():
                if hasattr(voice,'release'): voice.release()
        elif down:
            voice = bank.voice(level,tone,colour,patches)
            if voice is not None:
                previous = voices.get(colour)
                if hasattr(previous,'release'):
                    tails.append([previous,round(rate*.012)])
                    tails[:] = tails[-8:]
                voices[colour] = voice
        elif hasattr(voices.get(colour),'release'): voices[colour].release()
    mix_span(length,len(out))
    out[:tail_frames] += out[length:]
    return level,np.clip(out[:length],-.85,.85).astype(np.float32)

class LayerStore:
    def __init__(self, root, rate):
        self.root = Path(root)/'music_maker'
        self.rate = rate
        self.path = self.root/'layers.json'
        self.names,self.undo,self.tracks = {},None,{}

    def _load_track(self, name):
        path = self.root/name
        with wave_module.open(str(path), 'rb') as wav:
            if (wav.getnchannels(),wav.getsampwidth(),wav.getframerate(),wav.getnframes()) != (1,2,self.rate,self.rate*8):
                raise ValueError('Saved loops must be eight-second mono PCM16 at the configured rate')
        return load_wav(path,self.rate,pcm16=True)

    def load(self):
        if not self.path.exists(): return {}
        if self.path.stat().st_size > 65536: raise ValueError('Loop manifest is too large')
        state = json.loads(self.path.read_text(encoding='utf-8'))
        if not isinstance(state,dict) or not isinstance(state.get('layers'),dict):
            raise ValueError('Invalid layer manifest')
        for files in (state['layers'],{} if state.get('undo') is None else state['undo']):
            if not isinstance(files,dict): raise ValueError('Invalid undo manifest')
            for key,name in files.items():
                if key not in ('1','2','3') or not isinstance(name,str) or Path(name).name != name or not name.endswith('.wav'):
                    raise ValueError('Invalid layer manifest')
        tracks = {int(k):self._load_track(v) for k,v in state['layers'].items()}
        self.names,self.undo,self.tracks = state['layers'],state.get('undo'),tracks
        return tracks.copy()

    def apply(self, action, payload=None):
        names,undo,tracks = self.names.copy(),self.names.copy(),self.tracks.copy()
        if (action == 'clear' and not tracks) or (action == 'clear_layer' and payload not in tracks):
            return tracks  # A repeated empty clear must preserve the Undo snapshot.
        if action == 'save':
            level,data = payload
            name = uuid.uuid4().hex+'.wav'
            save_wav_atomic(self.root/name,data,self.rate)
            names[str(level)] = name
            tracks[level] = self._load_track(name)
        elif action == 'clear': names,tracks = {},{}
        elif action == 'clear_layer':
            names.pop(str(payload), None)
            tracks.pop(payload, None)
        elif action == 'undo':
            if self.undo is None: return tracks
            names = self.undo.copy()
            tracks = {int(k):self._load_track(v) for k,v in names.items()}
        else: raise ValueError('Invalid layer action')
        atomic_json(self.path,{'layers':names,'undo':undo})
        self.names,self.undo,self.tracks = names,undo,tracks
        keep = set(names.values())|set(undo.values())
        for path in self.root.glob('*.wav'):
            if path.name not in keep and len(path.stem) == 32 and all(c in '0123456789abcdef' for c in path.stem):
                try: path.unlink(missing_ok=True)
                except OSError: pass  # Cleanup cannot invalidate a committed save.
        return tracks.copy()

class LoopSession:
    def __init__(self, rate, bank):
        self.rate,self.bank = rate,bank
        self.length,self.clock,self.position = rate*8,0,0.0
        self.playing = False
        self.tracks,self.prepared = {},{}
        self.state = 'idle'
        self.record_down = self.song_down = None
        self.song_held = False
        self.song_level = 1
        self.clear_all_armed = False
        self.record_level,self.start,self.events = 1,0,[]
        self.patches = {}
        self.quantize = True
        self.jobs = deque()
        self.retired = deque()
        self.error = None
        t = np.arange(round(rate*.04))/rate
        self.click = np.asarray(.25*np.sin(2*np.pi*1200*t)*np.exp(-t*90),dtype=np.float32)
        self.click_voice,self.next_click = None,0

    def set_tracks(self, tracks):
        self.tracks = tracks
        grid = np.arange(self.length+1,dtype=np.float64) if tracks else None
        self.prepared = {key:(grid,np.append(data.astype(np.float64)/32768,data[0]/32768)*.65) for key,data in tracks.items()}
        if tracks:
            # Interpolation is linear: prepare the full arrangement on the worker
            # so playback needs one resample, irrespective of the number of layers.
            combined = np.zeros(self.length+1,dtype=np.float64)
            for _, data in self.prepared.values(): combined += data
            self.prepared[0] = (grid, combined)

    def busy(self): return self.state != 'idle'

    def status(self):
        return dict(state=self.state,playing=self.playing,layers=sorted(self.tracks),progress=round(self.position/self.length,3),quantize=self.quantize,error=self.error,level=self.record_level,
                    drum_kits=self.bank.drum_names,drum_samples=self.bank.drum_samples,drum_errors=self.bank.drum_errors,
                    clear_hint='Release to clear all layers' if self.clear_all_armed else
                    f'Release to clear Level {self.song_level}' if self.song_held else None)

    def finish(self):
        if self.state == 'capturing':
            if any(e[1] for e in self.events):
                end = max(0,min(self.length-1,self.clock-self.start))
                self.events.extend((end,False,colour,'') for colour in COLOURS)
                self.jobs.append(('render',(self.record_level,tuple(self.events),self.patches,self.quantize)))
                self.state = 'preparing'
            else: self.state = 'idle'
        elif self.state == 'counting': self.state = 'idle'
        self.record_down = None

    def event(self, down, colour, tone=''):
        if self.state == 'capturing' and len(self.events)<256:
            self.events.append((max(0,min(self.length-1,self.clock-self.start)),down,colour,tone))

    def button(self, kind, down, level, patches):
        if kind == 'record':
            if down and not self.busy():
                self.record_down,self.record_level,self.patches = self.clock,level,patches.copy()
            elif not down:
                tap = self.record_down is not None and self.state == 'idle'
                self.finish()
                return tap and level == 3
        else:
            if down and not self.busy() and self.record_down is None:
                self.song_down,self.song_held,self.clear_all_armed = self.clock,False,False
                self.song_level = level
            elif not down and self.song_down is not None:
                held = self.clock-self.song_down
                if not self.busy():
                    if held >= self.rate*2:
                        all_layers = held >= self.rate*5
                        self.jobs.append(('clear' if all_layers else 'clear_layer', None if all_layers else self.song_level))
                        self.state = 'preparing'
                        if all_layers: self.playing,self.position = False,0
                    else: self.playing = not self.playing
                self.song_down = None
                self.song_held = self.clear_all_armed = False
        return False

    def advance(self, count):
        if self.record_down is not None and self.state == 'idle' and self.clock-self.record_down>=self.rate*.4:
            self.state,self.start,self.next_click = 'counting',self.clock+self.rate*2,self.clock
            self.position,self.events = 0,[]
        if self.song_down is not None and not self.song_held and self.clock-self.song_down>=self.rate*2 and not self.busy():
            self.song_held,self.click_voice = True,Voice((self.click,))
        if self.song_down is not None and not self.clear_all_armed and self.clock-self.song_down>=self.rate*5 and not self.busy():
            self.clear_all_armed,self.click_voice = True,Voice((self.click,self.click))
        if self.state == 'counting':
            if self.clock>=self.start:
                self.state,self.playing,self.position = 'capturing',True,0
                self.start = self.clock  # Align events to the actual callback start.
            elif self.clock>=self.next_click:
                self.click_voice = Voice((self.click,))
                self.next_click += self.rate//2
        if self.state == 'capturing' and self.clock-self.start>=self.length: self.finish()
        self.clock += count

    def mix(self, output, speed):
        if self.click_voice is not None and not self.click_voice.mix(output,1): self.click_voice = None
        if not self.playing or not self.prepared or self.state == 'counting': return
        speed = 1 if self.state == 'capturing' else speed
        direct = speed == 1 and self.position == int(self.position)
        positions = None if direct else (frame_positions(len(output))*speed+self.position)%self.length
        selected = ((key,value) for key,value in self.prepared.items() if key not in (0,self.record_level)) if self.state == 'capturing' else ((0,self.prepared[0]),)
        for key,(grid,data) in selected:
            if direct:
                begin = int(self.position)
                count = min(len(output),self.length-begin)
                output[:count] += data[begin:begin+count]
                if count<len(output): output[count:] += data[:len(output)-count]
            else: output += np.interp(positions,grid,data)
        self.position = (self.position+len(output)*speed)%self.length
