import asyncio
import json
import unittest
from unittest.mock import AsyncMock, MagicMock, patch

from blaster.av_monitor import stream_av_events, LOG_PREDICATE, PREFIX

class TestStreamAVEvents(unittest.IsolatedAsyncioTestCase):
    async def test_state_change_yielding(self):
        """Test that stream_av_events parses NDJSON and yields only when the camera/mic state actually changes."""
        mock_proc = MagicMock()
        mock_proc.returncode = None
        mock_proc.stdout = AsyncMock()
        mock_proc.wait = AsyncMock()
        mock_proc.terminate = MagicMock()
        mock_proc.kill = MagicMock()

        log_lines = [
            json.dumps({"eventMessage": PREFIX + "cam:com.apple.FaceTime]"}).encode("utf-8") + b"\n",
            json.dumps({"eventMessage": PREFIX + "cam:com.apple.FaceTime]"}).encode("utf-8") + b"\n", # Duplicate, should not yield
            json.dumps({"eventMessage": PREFIX + "cam:com.apple.FaceTime, mic:us.zoom.xos]"}).encode("utf-8") + b"\n",
            b"" # EOF
        ]

        mock_proc.stdout.readline.side_effect = log_lines

        with patch("asyncio.create_subprocess_exec", new_callable=AsyncMock) as mock_create_subprocess:
            mock_create_subprocess.return_value = mock_proc

            gen = stream_av_events()
            results = []
            async for state in gen:
                results.append(state)

            # Assert yields
            self.assertEqual(results, [(True, False), (True, True)])

            # Assert process creation
            mock_create_subprocess.assert_called_once_with(
                "/usr/bin/log", "stream",
                "--style", "ndjson",
                "--predicate", LOG_PREDICATE,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.DEVNULL
            )

            # Clean termination
            mock_proc.terminate.assert_called_once()
            mock_proc.wait.assert_called_once()
            mock_proc.kill.assert_not_called()

    async def test_noise_filtering(self):
        """Ensure it ignores empty lines, "Filtering..." lines, malformed JSON, and JSON lacking the expected PREFIX."""
        mock_proc = MagicMock()
        mock_proc.returncode = None
        mock_proc.stdout = AsyncMock()
        mock_proc.wait = AsyncMock()
        mock_proc.terminate = MagicMock()
        mock_proc.kill = MagicMock()

        log_lines = [
            b"\n",
            b"Filtering the log data using...\n",
            b"Invalid JSON\n",
            json.dumps({"eventMessage": "Some other message"}).encode("utf-8") + b"\n",
            json.dumps({"eventMessage": PREFIX + "mic:us.zoom.xos]"}).encode("utf-8") + b"\n",
            b""
        ]

        mock_proc.stdout.readline.side_effect = log_lines

        with patch("asyncio.create_subprocess_exec", new_callable=AsyncMock) as mock_create_subprocess:
            mock_create_subprocess.return_value = mock_proc

            gen = stream_av_events()
            results = []
            async for state in gen:
                results.append(state)

            # Should only yield the valid mic state
            self.assertEqual(results, [(False, True)])

    async def test_termination_fallback_process_lookup_error(self):
        """Verify that if proc.terminate() throws ProcessLookupError, proc.kill() is NOT invoked."""
        mock_proc = MagicMock()
        mock_proc.returncode = None
        mock_proc.stdout = AsyncMock()
        mock_proc.stdout.readline.return_value = b"" # Immediate EOF
        mock_proc.wait = AsyncMock()
        mock_proc.terminate = MagicMock(side_effect=ProcessLookupError)
        mock_proc.kill = MagicMock()

        with patch("asyncio.create_subprocess_exec", new_callable=AsyncMock) as mock_create_subprocess:
            mock_create_subprocess.return_value = mock_proc

            gen = stream_av_events()
            async for _ in gen:
                pass # Consume stream

            mock_proc.terminate.assert_called_once()
            mock_proc.wait.assert_not_called()
            mock_proc.kill.assert_not_called()

    async def test_termination_fallback_timeout_error(self):
        """Verify that if await asyncio.wait_for(proc.wait(), timeout=2.0) throws an asyncio.TimeoutError, proc.kill() is invoked."""
        mock_proc = MagicMock()
        mock_proc.returncode = None
        mock_proc.stdout = AsyncMock()
        mock_proc.stdout.readline.return_value = b"" # Immediate EOF

        # We need to simulate timeout on wait
        async def mock_wait_timeout():
            raise asyncio.TimeoutError()

        mock_proc.wait = AsyncMock(side_effect=mock_wait_timeout)
        mock_proc.terminate = MagicMock()
        mock_proc.kill = MagicMock()

        with patch("asyncio.create_subprocess_exec", new_callable=AsyncMock) as mock_create_subprocess:
            mock_create_subprocess.return_value = mock_proc

            gen = stream_av_events()
            async for _ in gen:
                pass # Consume stream

            mock_proc.terminate.assert_called_once()
            mock_proc.wait.assert_called_once()
            mock_proc.kill.assert_called_once()
