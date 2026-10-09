import unittest
from unittest.mock import patch
from types import SimpleNamespace
import numpy as np

from djtable.audio import MicrophoneBridge
from djtable.core import Engine


class MicrophoneBridgeTests(unittest.TestCase):
    def test_pool_recovers_after_overflow_and_rejects_oversize(self):
        engine = Engine(SimpleNamespace(songs=[]), rate=1000, record_seconds=3, capture=True)
        engine.record_state = 'recording'
        bridge = MicrophoneBridge(engine, max_frames=8, channels=2)
        for index in range(17):
            bridge.capture(np.full((8, 2), index, dtype=np.float32), 8, None, False)
        bridge.playback(np.zeros((8, 2), dtype=np.float32), 8, None, False)
        np.testing.assert_array_equal(engine.record_buffer[:128], np.repeat(np.arange(16), 8))
        self.assertEqual(len(bridge._free), 16)
        bridge.capture(np.zeros((9, 2), dtype=np.float32), 9, None, False)
        self.assertEqual(bridge.dropped_blocks, 2)
        bridge.capture(np.full((3, 2), .2, dtype=np.float32), 3, None, False)
        bridge.playback(np.zeros((8, 2), dtype=np.float32), 8, None, False)
        np.testing.assert_allclose(engine.record_buffer[128:131], .2)

    def test_callback_does_not_concatenate_audio(self):
        engine = Engine(SimpleNamespace(songs=[]), rate=1000, record_seconds=3, capture=True)
        engine.record_state = 'recording'
        bridge = MicrophoneBridge(engine, max_frames=8, channels=2)
        source = np.full((8, 2), .25, dtype=np.float32)
        output = np.zeros((8, 2), dtype=np.float32)
        with patch('djtable.audio.np.concatenate', side_effect=AssertionError('callback allocation')):
            for _ in range(20):
                bridge.capture(source, 8, None, False)
                bridge.playback(output, 8, None, False)
        np.testing.assert_allclose(engine.record_buffer[:160], .25)

    def test_missing_callbacks_detected_but_silent_idle_input_is_healthy(self):
        with patch('djtable.audio.time.monotonic') as clock:
            clock.return_value = 10.0
            bridge = MicrophoneBridge(SimpleNamespace(record_state='idle'))
            clock.return_value = 13.1
            self.assertTrue(bridge.input_stalled())
            bridge.capture(np.zeros((512, 1)), 512, None, False)
            self.assertFalse(bridge.input_stalled())
            self.assertFalse(bridge.blocks)
            clock.return_value = 15.9
            self.assertFalse(bridge.input_stalled())
            clock.return_value = 16.2
            self.assertTrue(bridge.input_stalled())

    def test_independent_blocks_preserve_three_seconds_across_repeated_takes(self):
        engine = Engine(SimpleNamespace(songs=[]), rate=1000, record_seconds=3,
                        capture=True, record_prompt=np.ones(10, dtype=np.float32))
        bridge = MicrophoneBridge(engine)
        output = np.zeros((128, 2), dtype=np.float32)
        for take in (.1, .3):
            engine.submit('record')
            bridge.playback(output, 128, None, False)
            self.assertEqual(engine.record_state, 'recording')
            # USB and output callbacks do not share frame counts or clock timing.
            for _ in range(15):
                block = np.full((100, 1), take, dtype=np.float32)
                bridge.capture(block, 100, None, False)
                block.fill(.9)  # PortAudio reuses input storage.
                bridge.capture(np.full((100, 1), take, dtype=np.float32), 100, None, False)
                bridge.playback(output, 128, None, False)
            self.assertEqual(engine.record_state, 'saving')
            self.assertEqual(engine.completed.popleft(), 3000)
            np.testing.assert_allclose(engine.record_buffer, take)
            engine.submit('remix_ready', np.ones(10), (), 'test', None)
            bridge.playback(output, 128, None, False)
            self.assertEqual(engine.record_state, 'idle')

    def test_prompt_is_not_captured_and_queue_is_bounded(self):
        engine = Engine(SimpleNamespace(songs=[]), capture=True)
        bridge = MicrophoneBridge(engine)
        block = np.ones((512, 1), dtype=np.float32)
        engine.record_state = 'prompt'
        bridge.capture(block, 512, None, True)
        self.assertFalse(bridge.blocks)
        engine.record_state = 'recording'
        for _ in range(20):
            bridge.capture(block, 512, None, False)
        self.assertEqual(len(bridge.blocks), 16)
        self.assertEqual(bridge.dropped_blocks, 4)
        self.assertEqual(bridge.input_status_count, 1)
