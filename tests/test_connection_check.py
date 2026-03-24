import sys
import unittest
from unittest.mock import MagicMock

# Mock bleak before importing blaster.ble_client
mock_bleak = MagicMock()
sys.modules["bleak"] = mock_bleak
sys.modules["bleak.backends"] = MagicMock()
sys.modules["bleak.backends.device"] = MagicMock()

from blaster.ble_client import IRBlasterBLE
from blaster.config import BLEConfig

class TestConnectionCheck(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.config = BLEConfig(device_name="TestDevice")
        self.ble = IRBlasterBLE(self.config)

    async def test_wait_until_ready_raises_when_not_connected(self):
        with self.assertRaisesRegex(RuntimeError, "Not connected to IR Blaster"):
            await self.ble.wait_until_ready()

    async def test_get_saved_codes_raises_when_not_connected(self):
        with self.assertRaisesRegex(RuntimeError, "Not connected to IR Blaster"):
            await self.ble.get_saved_codes()

    async def test_send_command_by_name_raises_when_not_connected(self):
        with self.assertRaisesRegex(RuntimeError, "Not connected to IR Blaster"):
            await self.ble.send_command_by_name("Test")

    async def test_schedule_disconnect_command_raises_when_not_connected(self):
        with self.assertRaisesRegex(RuntimeError, "Not connected to IR Blaster"):
            await self.ble.schedule_disconnect_command("Off", 10)

    async def test_send_heartbeat_raises_when_not_connected(self):
        with self.assertRaisesRegex(RuntimeError, "Not connected to IR Blaster"):
            await self.ble.send_heartbeat()

    async def test_send_command_raises_when_not_connected(self):
        with self.assertRaisesRegex(RuntimeError, "Not connected to IR Blaster"):
            await self.ble.send_command(1)
