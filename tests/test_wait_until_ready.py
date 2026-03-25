import asyncio
import unittest
from unittest.mock import AsyncMock, MagicMock, patch
import sys
import time

# Mock bleak before importing IRBlasterBLE
mock_bleak = MagicMock()
sys.modules["bleak"] = mock_bleak
sys.modules["bleak.backends"] = MagicMock()
sys.modules["bleak.backends.device"] = MagicMock()
sys.modules["bleak.exc"] = MagicMock()

from blaster.ble_client import IRBlasterBLE
from blaster.config import BLEConfig

class TestWaitUntilReady(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.config = BLEConfig(device_name="TestDevice")
        self.blaster = IRBlasterBLE(self.config)
        self.blaster._client = MagicMock()
        self.blaster._client.is_connected = True

    async def test_wait_until_ready_success_first_try(self):
        """Test that wait_until_ready returns immediately on success."""
        with patch.object(self.blaster, "get_saved_codes", new_callable=AsyncMock) as mock_get:
            await self.blaster.wait_until_ready(timeout_seconds=1.0)
            mock_get.assert_called_once_with(retries=1)

    async def test_wait_until_ready_success_after_retries(self):
        """Test that wait_until_ready retries and eventually succeeds."""
        with patch.object(self.blaster, "get_saved_codes", new_callable=AsyncMock) as mock_get:
            # Fail twice, then succeed
            mock_get.side_effect = [Exception("Fail"), Exception("Fail"), [{"i": 0, "n": "Test"}]]

            with patch("asyncio.sleep", new_callable=AsyncMock) as mock_sleep:
                await self.blaster.wait_until_ready(timeout_seconds=5.0)

            self.assertEqual(mock_get.call_count, 3)
            self.assertEqual(mock_sleep.call_count, 2)

    async def test_wait_until_ready_timeout(self):
        """Test that wait_until_ready raises TimeoutError on persistent failure."""
        with patch.object(self.blaster, "get_saved_codes", new_callable=AsyncMock) as mock_get:
            mock_get.side_effect = Exception("Persistent Fail")

            # Use a short timeout and mock sleep to speed up the test
            with patch("asyncio.sleep", new_callable=AsyncMock) as mock_sleep:
                # We need to make time.monotonic() advance so the loop terminates
                with patch("time.monotonic") as mock_time:
                    mock_time.side_effect = [
                        0,    # deadline calculation
                        0.1,  # first loop check
                        0.6,  # second loop check
                        1.1,  # third loop check (exceeds timeout)
                    ]
                    with self.assertRaises(TimeoutError):
                        await self.blaster.wait_until_ready(timeout_seconds=1.0)

            # Should have called get_saved_codes multiple times
            self.assertGreater(mock_get.call_count, 1)

    async def test_wait_until_ready_not_connected(self):
        """Test that wait_until_ready raises RuntimeError if not connected."""
        self.blaster._client.is_connected = False
        with self.assertRaises(RuntimeError):
            await self.blaster.wait_until_ready(timeout_seconds=1.0)
