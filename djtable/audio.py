"""Bridge independently clocked microphone and speaker streams."""
from collections import deque
import time

import numpy as np


class MicrophoneBridge:
    def __init__(self, engine, max_frames=4096, channels=2):
        self.engine = engine
        self.max_frames, self.channels = max_frames, channels
        # CPython SPSC deques transfer ownership of slots. Never return a slot
        # until the consumer has copied it; NumPy may release the GIL.
        self._free = deque(np.empty((max_frames, channels), dtype=np.float32) for _ in range(16))
        self._staging = np.empty((16 * max_frames, channels), dtype=np.float32)
        self.blocks = deque()
        self.input_status_count = 0
        self.dropped_blocks = 0
        self.last_input_at = time.monotonic()

    def input_stalled(self, timeout=3.0):
        return time.monotonic() - self.last_input_at > timeout

    def capture(self, data, frames, timing, status):
        self.last_input_at = time.monotonic()
        if status:
            self.input_status_count += 1
        # Output callback owns the Engine. Input callback only supplies copies;
        # PortAudio may reuse its incoming buffer immediately after this returns.
        if self.engine.record_state == 'recording':
            if len(data) > self.max_frames or data.shape[1] > self.channels or not self._free:
                self.dropped_blocks += 1
                return
            slot = self._free.popleft()
            np.copyto(slot[:len(data), :data.shape[1]], data)
            if data.shape[1] < self.channels:
                slot[:len(data), data.shape[1]:].fill(0)
            self.blocks.append((slot, len(data)))

    def playback(self, output, frames, timing, status):
        count = 0
        recording_before = self.engine.record_state == 'recording'
        for _ in range(16):
            if not self.blocks:
                break
            slot, size = self.blocks.popleft()
            if recording_before:
                np.copyto(self._staging[count:count+size], slot[:size])
                count += size
            self._free.append(slot)
        data = self._staging[:count] if count else None
        self.engine.render(output, data, status)
        if not recording_before or self.engine.record_state != 'recording':
            # Discard prompt-era samples and the tail after recording completes.
            # Independently clocked input may provide zero, one or two blocks
            # per output callback; all available recording frames are consumed.
            for _ in range(16):
                if not self.blocks:
                    break
                slot, _ = self.blocks.popleft()
                self._free.append(slot)
