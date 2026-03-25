import asyncio
import json
import unittest
from unittest.mock import AsyncMock, MagicMock, patch

# Mock bleak before importing IRBlasterBLE
import sys
sys.modules["bleak"] = MagicMock()
sys.modules["bleak.backends.device"] = MagicMock()

from blaster.ble_client import IRBlasterBLE, CHAR_SAVED_UUID
from blaster.config import BLEConfig

class TestIRBlasterBLERetries(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.mock_ble_client = MagicMock()
        self.mock_ble_client.is_connected = True
        self.mock_ble_client.read_gatt_char = AsyncMock()

        self.config = BLEConfig(device_name="TestBlaster")
        self.blaster = IRBlasterBLE(self.config)
        self.blaster._client = self.mock_ble_client

    async def test_get_saved_codes_not_connected(self):
        self.mock_ble_client.is_connected = False
        with self.assertRaisesRegex(RuntimeError, "Not connected to IR Blaster"):
            await self.blaster.get_saved_codes()

    async def test_get_saved_codes_json_decode_error_retries(self):
        # Mock malformed JSON
        self.mock_ble_client.read_gatt_char.return_value = b"invalid json"

        with patch("blaster.ble_client.asyncio.sleep", new_callable=AsyncMock) as mock_sleep:
            with self.assertRaises(json.JSONDecodeError):
                await self.blaster.get_saved_codes(retries=3)

            self.assertEqual(self.mock_ble_client.read_gatt_char.call_count, 3)
            self.assertEqual(mock_sleep.call_count, 2)
            mock_sleep.assert_called_with(1.0)

    async def test_get_saved_codes_value_error_empty_retries(self):
        # Mock empty response
        self.mock_ble_client.read_gatt_char.return_value = b""

        with patch("blaster.ble_client.asyncio.sleep", new_callable=AsyncMock) as mock_sleep:
            with self.assertRaisesRegex(ValueError, "Saved Codes read returned empty"):
                await self.blaster.get_saved_codes(retries=3)

            self.assertEqual(self.mock_ble_client.read_gatt_char.call_count, 3)
            self.assertEqual(mock_sleep.call_count, 2)

    async def test_get_saved_codes_not_a_list_retries(self):
        # Mock JSON that is not a list
        self.mock_ble_client.read_gatt_char.return_value = b'{"not": "a list"}'

        with patch("blaster.ble_client.asyncio.sleep", new_callable=AsyncMock) as mock_sleep:
            with self.assertRaisesRegex(ValueError, "Saved Codes is not a list"):
                await self.blaster.get_saved_codes(retries=3)

            self.assertEqual(self.mock_ble_client.read_gatt_char.call_count, 3)
            self.assertEqual(mock_sleep.call_count, 2)

    async def test_get_saved_codes_succeeds_after_retry(self):
        # First attempt fails, second succeeds
        self.mock_ble_client.read_gatt_char.side_effect = [
            b"invalid json",
            b'[{"i": 0, "n": "Power"}]'
        ]

        with patch("blaster.ble_client.asyncio.sleep", new_callable=AsyncMock) as mock_sleep:
            data = await self.blaster.get_saved_codes(retries=3)

            self.assertEqual(data, [{"i": 0, "n": "Power"}])
            self.assertEqual(self.mock_ble_client.read_gatt_char.call_count, 2)
            self.assertEqual(mock_sleep.call_count, 1)
