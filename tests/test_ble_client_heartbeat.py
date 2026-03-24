import sys
import json
import unittest
from unittest.mock import AsyncMock, MagicMock

# Mock bleak before importing blaster.ble_client
mock_bleak = MagicMock()
sys.modules["bleak"] = mock_bleak
sys.modules["bleak.backends"] = MagicMock()
sys.modules["bleak.backends.device"] = MagicMock()

from blaster.ble_client import IRBlasterBLE, CHAR_SCHEDULE_UUID
from blaster.config import BLEConfig

class TestIRBlasterBLEHeartbeat(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.config = BLEConfig(device_name="TestDevice")
        self.ble = IRBlasterBLE(self.config)

    async def test_send_heartbeat_success(self):
        # Setup mock client
        mock_client = AsyncMock()
        mock_client.is_connected = True
        self.ble._client = mock_client

        # Call send_heartbeat
        await self.ble.send_heartbeat()

        # Verify write_gatt_char was called with correct arguments
        expected_payload = json.dumps({"heartbeat": True}).encode("utf-8")
        mock_client.write_gatt_char.assert_called_once_with(
            CHAR_SCHEDULE_UUID, expected_payload
        )

    async def test_send_heartbeat_not_connected_none(self):
        # Client is None by default
        self.ble._client = None

        with self.assertRaisesRegex(RuntimeError, "Not connected to IR Blaster"):
            await self.ble.send_heartbeat()

    async def test_send_heartbeat_not_connected_false(self):
        # Setup mock client that is disconnected
        mock_client = MagicMock()
        mock_client.is_connected = False
        self.ble._client = mock_client

        with self.assertRaisesRegex(RuntimeError, "Not connected to IR Blaster"):
            await self.ble.send_heartbeat()

if __name__ == "__main__":
    unittest.main()
