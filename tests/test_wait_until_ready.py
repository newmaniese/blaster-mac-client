import asyncio
import unittest
from unittest.mock import AsyncMock, MagicMock, patch
import time

class TestWaitUntilReady(unittest.IsolatedAsyncioTestCase):
    @classmethod
    def setUpClass(cls):
        # Mock bleak dependencies before importing the module under test
        # to avoid ModuleNotFoundError in environments without bleak.
        cls.sys_modules_patcher = patch.dict("sys.modules", {
            "bleak": MagicMock(),
            "bleak.backends": MagicMock(),
            "bleak.backends.device": MagicMock(),
        })
        cls.sys_modules_patcher.start()

        # Now we can safely import IRBlasterBLE
        global IRBlasterBLE, BLEConfig
        from blaster.ble_client import IRBlasterBLE
        from blaster.config import BLEConfig
        cls.IRBlasterBLE = IRBlasterBLE
        cls.BLEConfig = BLEConfig

    @classmethod
    def tearDownClass(cls):
        cls.sys_modules_patcher.stop()

    def setUp(self):
        self.config = self.BLEConfig(device_name="TestDevice")
        self.blaster = self.IRBlasterBLE(self.config)

    async def test_wait_until_ready_not_connected(self):
        """Should raise RuntimeError if client is not connected."""
        # Case 1: self._client is None
        self.blaster._client = None
        with self.assertRaisesRegex(RuntimeError, "Not connected to IR Blaster"):
            await self.blaster.wait_until_ready()

        # Case 2: self._client is not connected
        self.blaster._client = MagicMock()
        self.blaster._client.is_connected = False
        with self.assertRaisesRegex(RuntimeError, "Not connected to IR Blaster"):
            await self.blaster.wait_until_ready()

    async def test_wait_until_ready_success_immediate(self):
        """Should return immediately if get_saved_codes succeeds."""
        self.blaster._client = MagicMock()
        self.blaster._client.is_connected = True

        with patch.object(self.IRBlasterBLE, 'get_saved_codes', new_callable=AsyncMock) as mock_get_saved_codes:
            mock_get_saved_codes.return_value = [{"index": 1, "name": "test"}]

            await self.blaster.wait_until_ready()

            mock_get_saved_codes.assert_called_once_with(retries=1)

    async def test_wait_until_ready_success_after_retry(self):
        """Should retry and then succeed if get_saved_codes fails initially."""
        self.blaster._client = MagicMock()
        self.blaster._client.is_connected = True

        with patch.object(self.IRBlasterBLE, 'get_saved_codes', new_callable=AsyncMock) as mock_get_saved_codes:
            # Fails once, then succeeds
            mock_get_saved_codes.side_effect = [Exception("Read failed"), [{"index": 1, "name": "test"}]]

            with patch("asyncio.sleep", new_callable=AsyncMock) as mock_sleep:
                await self.blaster.wait_until_ready()

                self.assertEqual(mock_get_saved_codes.call_count, 2)
                mock_sleep.assert_called_once_with(0.5)

    async def test_wait_until_ready_timeout(self):
        """Should raise TimeoutError if it keeps failing until timeout."""
        self.blaster._client = MagicMock()
        self.blaster._client.is_connected = True

        timeout = 0.5

        with patch.object(self.IRBlasterBLE, 'get_saved_codes', new_callable=AsyncMock) as mock_get_saved_codes:
            mock_get_saved_codes.side_effect = Exception("Read failed")

            with patch("asyncio.sleep", new_callable=AsyncMock) as mock_sleep:
                with patch("time.monotonic") as mock_time:
                    # 1. start = 100.0 (deadline = 100.5)
                    # 2. first loop check: 100.1 < 100.5 -> True
                    # 3. second loop check: 100.6 < 100.5 -> False
                    mock_time.side_effect = [100.0, 100.1, 100.6]

                    with self.assertRaises(TimeoutError) as cm:
                        await self.blaster.wait_until_ready(timeout_seconds=timeout)

                    self.assertIn(f"BLE link not ready after {timeout}s", str(cm.exception))

                # Verify it tried at least once
                self.assertGreaterEqual(mock_get_saved_codes.call_count, 1)
                # Verify it slept before timing out
                mock_sleep.assert_called_with(0.5)
