
import sys
from unittest.mock import MagicMock

# Mock bleak before importing IRBlasterBLE
mock_bleak = MagicMock()
sys.modules["bleak"] = mock_bleak
sys.modules["bleak.backends"] = MagicMock()
sys.modules["bleak.backends.device"] = MagicMock()

import unittest
from unittest.mock import AsyncMock, patch
from blaster.ble_client import IRBlasterBLE
from blaster.config import BLEConfig

class TestIRBlasterBLELookup(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.config = BLEConfig(device_name="TestDevice")
        self.blaster = IRBlasterBLE(self.config)
        self.blaster._client = MagicMock()
        self.blaster._client.is_connected = True

    @patch("blaster.ble_client.IRBlasterBLE.get_saved_codes", new_callable=AsyncMock)
    @patch("blaster.ble_client.IRBlasterBLE.send_command", new_callable=AsyncMock)
    async def test_send_command_by_name_full_format(self, mock_send, mock_get_codes):
        # Test "index" and "name"
        mock_get_codes.return_value = [{"index": 1, "name": "Power"}]
        await self.blaster.send_command_by_name("Power")
        mock_send.assert_called_once_with(1)

    @patch("blaster.ble_client.IRBlasterBLE.get_saved_codes", new_callable=AsyncMock)
    @patch("blaster.ble_client.IRBlasterBLE.send_command", new_callable=AsyncMock)
    async def test_send_command_by_name_compact_format(self, mock_send, mock_get_codes):
        # Test "i" and "n"
        mock_get_codes.return_value = [{"i": 2, "n": "Mute"}]
        await self.blaster.send_command_by_name("Mute")
        mock_send.assert_called_once_with(2)

    @patch("blaster.ble_client.IRBlasterBLE.get_saved_codes", new_callable=AsyncMock)
    @patch("blaster.ble_client.IRBlasterBLE.send_command", new_callable=AsyncMock)
    async def test_send_command_by_name_mixed_format(self, mock_send, mock_get_codes):
        # Test precedence: "index" should win over "i"
        mock_get_codes.return_value = [{"index": 3, "i": 4, "name": "VolUp"}]
        await self.blaster.send_command_by_name("VolUp")
        mock_send.assert_called_once_with(3)

    @patch("blaster.ble_client.IRBlasterBLE.get_saved_codes", new_callable=AsyncMock)
    @patch("blaster.ble_client.IRBlasterBLE.send_command", new_callable=AsyncMock)
    async def test_send_command_by_name_case_insensitive(self, mock_send, mock_get_codes):
        mock_get_codes.return_value = [{"index": 5, "name": "Play"}]
        await self.blaster.send_command_by_name("play")
        mock_send.assert_called_once_with(5)

if __name__ == "__main__":
    unittest.main()
