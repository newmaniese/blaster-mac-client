import json
import unittest
import sys
from unittest.mock import AsyncMock, MagicMock

# Mock bleak before importing IRBlasterBLE
mock_bleak = MagicMock()
sys.modules["bleak"] = mock_bleak
sys.modules["bleak.backends"] = MagicMock()
sys.modules["bleak.backends.device"] = MagicMock()

from blaster.ble_client import IRBlasterBLE, CHAR_SCHEDULE_UUID
from blaster.config import BLEConfig

class TestBLEHeartbeat(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.config = BLEConfig(device_name="TestDevice")
        self.blaster = IRBlasterBLE(self.config)
        self.mock_client = AsyncMock()
        self.blaster._client = self.mock_client

    async def test_send_heartbeat_success(self):
        """Test send_heartbeat when connected."""
        self.mock_client.is_connected = True

        await self.blaster.send_heartbeat()

        expected_payload = json.dumps({"heartbeat": True}).encode("utf-8")
        self.mock_client.write_gatt_char.assert_called_once_with(
            CHAR_SCHEDULE_UUID, expected_payload
        )

    async def test_send_heartbeat_not_connected(self):
        """Test send_heartbeat raises RuntimeError when not connected."""
        self.mock_client.is_connected = False

        with self.assertRaisesRegex(RuntimeError, "Not connected to IR Blaster"):
            await self.blaster.send_heartbeat()

        self.mock_client.write_gatt_char.assert_not_called()

    async def test_send_heartbeat_no_client(self):
        """Test send_heartbeat raises RuntimeError when _client is None."""
        self.blaster._client = None

        with self.assertRaisesRegex(RuntimeError, "Not connected to IR Blaster"):
            await self.blaster.send_heartbeat()

    async def test_schedule_disconnect_command_success(self):
        """Test schedule_disconnect_command when connected."""
        self.mock_client.is_connected = True
        command_name = "PowerOff"
        delay = 60

        await self.blaster.schedule_disconnect_command(command_name, delay)

        expected_payload = json.dumps({
            "delay_seconds": delay,
            "command": command_name
        }).encode("utf-8")
        self.mock_client.write_gatt_char.assert_called_once_with(
            CHAR_SCHEDULE_UUID, expected_payload
        )

    async def test_schedule_disconnect_command_not_connected(self):
        """Test schedule_disconnect_command raises RuntimeError when not connected."""
        self.mock_client.is_connected = False

        with self.assertRaisesRegex(RuntimeError, "Not connected to IR Blaster"):
            await self.blaster.schedule_disconnect_command("Off", 10)

        self.mock_client.write_gatt_char.assert_not_called()
