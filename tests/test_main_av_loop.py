import asyncio
import sys
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch, AsyncMock

# Inject bleak mocks before importing project files
import sys
sys.modules['bleak'] = MagicMock()
sys.modules['bleak.backends'] = MagicMock()
sys.modules['bleak.backends.device'] = MagicMock()

from blaster.__main__ import run


class TestMainAVLoop(unittest.IsolatedAsyncioTestCase):
    @patch("blaster.__main__.Config")
    @patch("blaster.__main__.IRBlasterBLE")
    @patch("blaster.__main__.get_initial_state")
    @patch("blaster.__main__.stream_av_events")
    @patch("blaster.__main__.execute_specs")
    async def test_av_loop_restarts_on_error(
        self,
        mock_execute_specs,
        mock_stream_av_events,
        mock_get_initial_state,
        mock_IRBlasterBLE,
        mock_Config,
    ):
        mock_get_initial_state.return_value = (False, False)

        mock_ble = MagicMock()
        mock_ble.connect = AsyncMock(return_value=True)
        mock_ble.wait_until_ready = AsyncMock()
        mock_ble.schedule_disconnect_command = AsyncMock()
        mock_ble.disconnect = AsyncMock()
        mock_IRBlasterBLE.return_value = mock_ble

        mock_config = MagicMock()
        mock_config.events.Idle = []
        mock_config.events.HeartbeatStopped = None
        mock_config.events.OnConnect = []
        mock_Config.load.return_value = mock_config

        # We want stream_av_events to raise an exception the first time it is called,
        # then the second time, we yield a normal event, then we block forever to let the
        # main loop spin without finishing (until cancelled).

        call_count = 0

        async def fake_stream():
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                # Fail immediately on first call
                raise RuntimeError("Stream failed!")
            elif call_count == 2:
                # Succeed and yield on second call
                yield (True, False)
                # then block forever so the loop doesn't just infinitely restart
                await asyncio.Future()

        mock_stream_av_events.side_effect = fake_stream

        # Run the main task
        task = asyncio.create_task(run(Path("fake_config.yaml")))

        # Allow the task to start, fail the first stream, and restart
        await asyncio.sleep(1.5)

        # Cancel the task
        task.cancel()

        # When task is cancelled, wait for it to finish gracefully
        # The run() function handles CancelledError and shuts down cleanly
        try:
            await task
        except asyncio.CancelledError:
            pass

        # Check that stream_av_events was called at least twice
        self.assertGreaterEqual(call_count, 2)


if __name__ == "__main__":
    unittest.main()
