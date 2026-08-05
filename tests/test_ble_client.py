import asyncio
import json
import sys
import unittest
from unittest.mock import AsyncMock, MagicMock, patch

# Mock bleak if not installed
try:
    from bleak.backends.device import BLEDevice
except ImportError:
    mock_bleak = MagicMock()
    sys.modules["bleak"] = mock_bleak
    mock_bleak_backends = MagicMock()
    sys.modules["bleak.backends"] = mock_bleak_backends
    mock_bleak_backends_device = MagicMock()
    sys.modules["bleak.backends.device"] = mock_bleak_backends_device

    class BLEDevice:
        def __init__(self, address, name, details=None):
            self.address = address
            self.name = name
            self.details = details or {}
    mock_bleak_backends_device.BLEDevice = BLEDevice

from blaster.config import BLEConfig
from blaster.ble_client import CHAR_SCHEDULE_UUID, CHAR_SEND_UUID, IRBlasterBLE, find_device


class TestFindDevice(unittest.IsolatedAsyncioTestCase):
    async def test_find_device_found(self) -> None:
        config = BLEConfig(device_name="IR Blaster")
        mock_device = BLEDevice(address="00:11:22:33:44:55", name="IR Blaster", details={})

        with patch("blaster.ble_client.BleakScanner.discover", new_callable=AsyncMock) as mock_discover:
            mock_discover.return_value = [mock_device]

            device = await find_device(config)

            assert device is not None
            assert device.name == "IR Blaster"
            assert device.address == "00:11:22:33:44:55"
            mock_discover.assert_called_once_with(timeout=10.0)

    async def test_find_device_not_found(self) -> None:
        config = BLEConfig(device_name="IR Blaster")
        mock_device = BLEDevice(address="AA:BB:CC:DD:EE:FF", name="Other Device", details={})

        with patch("blaster.ble_client.BleakScanner.discover", new_callable=AsyncMock) as mock_discover:
            mock_discover.return_value = [mock_device]

            device = await find_device(config)

            assert device is None
            mock_discover.assert_called_once_with(timeout=10.0)

    async def test_find_device_empty(self) -> None:
        config = BLEConfig(device_name="IR Blaster")

        with patch("blaster.ble_client.BleakScanner.discover", new_callable=AsyncMock) as mock_discover:
            mock_discover.return_value = []

            device = await find_device(config)

            assert device is None
            mock_discover.assert_called_once_with(timeout=10.0)

    async def test_find_device_case_insensitive(self) -> None:
        config = BLEConfig(device_name="ir blaster")
        mock_device = BLEDevice(address="00:11:22:33:44:55", name="IR Blaster", details={})

        with patch("blaster.ble_client.BleakScanner.discover", new_callable=AsyncMock) as mock_discover:
            mock_discover.return_value = [mock_device]

            device = await find_device(config)

            assert device is not None
            assert device.name == "IR Blaster"
            mock_discover.assert_called_once_with(timeout=10.0)

    async def test_find_device_partial_match(self) -> None:
        config = BLEConfig(device_name="Blaster")
        mock_device = BLEDevice(address="00:11:22:33:44:55", name="My IR Blaster", details={})

        with patch("blaster.ble_client.BleakScanner.discover", new_callable=AsyncMock) as mock_discover:
            mock_discover.return_value = [mock_device]

            device = await find_device(config)

            # Fix: partial match no longer allowed
            assert device is None
            mock_discover.assert_called_once_with(timeout=10.0)


class TestIRBlasterBLE(unittest.IsolatedAsyncioTestCase):
    async def test_connect_success(self) -> None:
        config = BLEConfig(device_name="Test Device")
        ble = IRBlasterBLE(config)
        mock_device = MagicMock()
        mock_device.name = "Test Device"

        mock_client = MagicMock()
        mock_client.is_connected = False
        mock_client.connect = AsyncMock()

        with (
            patch("blaster.ble_client.find_device", new_callable=AsyncMock) as mock_find,
            patch("blaster.ble_client.BleakClient", return_value=mock_client) as mock_client_cls,
        ):
            mock_find.return_value = mock_device
            success = await ble.connect()

        assert success is True
        mock_client.connect.assert_called_once()
        assert ble._client is mock_client
        mock_client_cls.assert_called_once()

    async def test_connect_no_device(self) -> None:
        config = BLEConfig(device_name="Test Device")
        ble = IRBlasterBLE(config)

        with patch("blaster.ble_client.find_device", new_callable=AsyncMock) as mock_find:
            mock_find.return_value = None
            success = await ble.connect()

        assert success is False

    async def test_connect_exception(self) -> None:
        config = BLEConfig(device_name="Test Device")
        ble = IRBlasterBLE(config)

        mock_client = MagicMock()
        mock_client.connect = AsyncMock(side_effect=Exception("Connect error"))

        with (
            patch("blaster.ble_client.find_device", new_callable=AsyncMock) as mock_find,
            patch("blaster.ble_client.BleakClient", return_value=mock_client),
        ):
            mock_find.return_value = MagicMock()
            success = await ble.connect()

        assert success is False
        assert ble._client is None

    async def test_connect_already_connected(self) -> None:
        config = BLEConfig(device_name="Test Device")
        ble = IRBlasterBLE(config)
        mock_client = MagicMock()
        mock_client.is_connected = True
        ble._client = mock_client

        success = await ble.connect()

        assert success is True

    @patch("asyncio.create_task")
    async def test_handle_disconnect_with_callback(self, mock_create_task: MagicMock) -> None:
        config = BLEConfig(device_name="Test Device")
        ble = IRBlasterBLE(config)
        mock_callback = MagicMock()
        mock_coro = MagicMock()
        mock_callback.return_value = mock_coro
        ble.set_disconnect_callback(mock_callback)
        mock_client = MagicMock()

        ble._handle_disconnect(mock_client)

        mock_create_task.assert_called_once_with(mock_coro)
        mock_callback.assert_called_once()

    @patch("asyncio.create_task")
    async def test_handle_disconnect_without_callback(self, mock_create_task: MagicMock) -> None:
        config = BLEConfig(device_name="Test Device")
        ble = IRBlasterBLE(config)
        mock_client = MagicMock()

        ble._handle_disconnect(mock_client)

        mock_create_task.assert_not_called()

    async def test_disconnect(self) -> None:
        config = BLEConfig(device_name="Test Device")
        ble = IRBlasterBLE(config)
        mock_client = MagicMock()
        mock_client.is_connected = True
        mock_client.disconnect = AsyncMock()
        ble._client = mock_client
        ble._device = MagicMock()

        await ble.disconnect()

        mock_client.disconnect.assert_called_once()
        assert ble._client is None
        assert ble._device is None

    async def test_wait_until_ready_success(self) -> None:
        config = BLEConfig(device_name="Test Device")
        ble = IRBlasterBLE(config)
        mock_client = MagicMock()
        mock_client.is_connected = True
        ble._client = mock_client

        with patch.object(ble, "get_saved_codes", new_callable=AsyncMock) as mock_get:
            await ble.wait_until_ready(timeout_seconds=0.1)
            mock_get.assert_called()

    async def test_wait_until_ready_timeout(self) -> None:
        config = BLEConfig(device_name="Test Device")
        ble = IRBlasterBLE(config)
        mock_client = MagicMock()
        mock_client.is_connected = True
        ble._client = mock_client

        with (
            patch.object(ble, "get_saved_codes", new_callable=AsyncMock, side_effect=Exception("Not ready")),
            patch("asyncio.sleep", new_callable=AsyncMock),
        ):
            with self.assertRaises(TimeoutError):
                await ble.wait_until_ready(timeout_seconds=0.1)

    async def test_get_saved_codes_success(self) -> None:
        config = BLEConfig(device_name="Test Device")
        ble = IRBlasterBLE(config)
        mock_client = MagicMock()
        mock_client.is_connected = True
        codes = [{"index": 1, "name": "Red"}]
        mock_client.read_gatt_char = AsyncMock(return_value=json.dumps(codes).encode("utf-8"))
        ble._client = mock_client

        result = await ble.get_saved_codes()

        assert result == codes

    async def test_get_saved_codes_retry_success(self) -> None:
        config = BLEConfig(device_name="Test Device")
        ble = IRBlasterBLE(config)
        mock_client = MagicMock()
        mock_client.is_connected = True
        codes = [{"index": 1, "name": "Red"}]
        mock_client.read_gatt_char = AsyncMock(side_effect=[b"", json.dumps(codes).encode("utf-8")])
        ble._client = mock_client

        with patch("asyncio.sleep", new_callable=AsyncMock):
            result = await ble.get_saved_codes(retries=2)

        assert result == codes
        assert mock_client.read_gatt_char.call_count == 2

    async def test_get_saved_codes_failure(self) -> None:
        config = BLEConfig(device_name="Test Device")
        ble = IRBlasterBLE(config)
        mock_client = MagicMock()
        mock_client.is_connected = True
        mock_client.read_gatt_char = AsyncMock(return_value=b"invalid json")
        ble._client = mock_client

        with patch("asyncio.sleep", new_callable=AsyncMock):
            with self.assertRaises(json.JSONDecodeError):
                await ble.get_saved_codes(retries=2)

    async def test_get_saved_codes_value_error_retries(self) -> None:
        config = BLEConfig(device_name="Test Device")
        ble = IRBlasterBLE(config)
        mock_client = MagicMock()
        mock_client.is_connected = True
        mock_client.read_gatt_char = AsyncMock(return_value=b'{"not": "a list"}')
        ble._client = mock_client

        with patch("asyncio.sleep", new_callable=AsyncMock) as mock_sleep:
            with self.assertRaises(ValueError):
                await ble.get_saved_codes(retries=2)
            assert mock_client.read_gatt_char.call_count == 2
            assert mock_sleep.call_count == 1

    async def test_send_command_by_name_success(self) -> None:
        config = BLEConfig(device_name="Test Device")
        ble = IRBlasterBLE(config)
        mock_client = MagicMock()
        mock_client.is_connected = True
        ble._client = mock_client
        codes = [{"index": 1, "name": "Red"}, {"i": 2, "n": "Blue"}]

        with patch.object(ble, "get_saved_codes", new_callable=AsyncMock, return_value=codes):
            with patch.object(ble, "send_command", new_callable=AsyncMock, return_value="OK:Red") as mock_send:
                res = await ble.send_command_by_name("Red")
                assert res == "OK:Red"
                mock_send.assert_called_with(1)

                res = await ble.send_command_by_name("Blue")
                assert res == "OK:Red"
                mock_send.assert_called_with(2)
                ble.get_saved_codes.assert_called_once()

    async def test_send_command_by_name_unknown(self) -> None:
        config = BLEConfig(device_name="Test Device")
        ble = IRBlasterBLE(config)
        mock_client = MagicMock()
        mock_client.is_connected = True
        ble._client = mock_client
        ble._name_to_index = {"red": 1}

        with self.assertRaises(ValueError):
            await ble.send_command_by_name("Green")

    async def test_schedule_disconnect_command_valid(self) -> None:
        config = BLEConfig(device_name="IR Blaster")
        ble = IRBlasterBLE(config)
        mock_client = AsyncMock()
        mock_client.is_connected = True
        ble._client = mock_client

        await ble.schedule_disconnect_command("Off", 900)

        expected_payload = json.dumps({"delay_seconds": 900, "command": "Off"}).encode("utf-8")
        mock_client.write_gatt_char.assert_called_once_with(CHAR_SCHEDULE_UUID, expected_payload)

    async def test_schedule_disconnect_command_negative_delay(self) -> None:
        config = BLEConfig(device_name="IR Blaster")
        ble = IRBlasterBLE(config)
        mock_client = AsyncMock()
        mock_client.is_connected = True
        ble._client = mock_client

        with self.assertRaisesRegex(ValueError, "delay_seconds must be non-negative"):
            await ble.schedule_disconnect_command("Off", -1)

        mock_client.write_gatt_char.assert_not_called()

    async def test_schedule_disconnect_command_invalid_type(self) -> None:
        config = BLEConfig(device_name="IR Blaster")
        ble = IRBlasterBLE(config)
        mock_client = AsyncMock()
        mock_client.is_connected = True
        ble._client = mock_client

        with self.assertRaisesRegex(TypeError, "delay_seconds must be an integer"):
            await ble.schedule_disconnect_command("Off", "900")  # type: ignore[arg-type]
        with self.assertRaisesRegex(TypeError, "delay_seconds must be an integer"):
            await ble.schedule_disconnect_command("Off", 1.5)  # type: ignore[arg-type]

        mock_client.write_gatt_char.assert_not_called()

    async def test_schedule_disconnect_command_requires_connection(self) -> None:
        config = BLEConfig(device_name="IR Blaster")
        ble = IRBlasterBLE(config)

        with self.assertRaisesRegex(RuntimeError, "Not connected to IR Blaster"):
            await ble.schedule_disconnect_command("Off", 60)

        mock_client = AsyncMock()
        mock_client.is_connected = False
        ble._client = mock_client
        with self.assertRaisesRegex(RuntimeError, "Not connected to IR Blaster"):
            await ble.schedule_disconnect_command("Off", 60)

    async def test_send_command_success(self) -> None:
        config = BLEConfig(device_name="Test Device")
        ble = IRBlasterBLE(config)
        mock_client = MagicMock()
        mock_client.is_connected = True
        mock_client.start_notify = AsyncMock()
        mock_client.stop_notify = AsyncMock()
        mock_client.write_gatt_char = AsyncMock()
        ble._client = mock_client

        async def mock_write(_uuid: str, _payload: bytes) -> None:
            callback = mock_client.start_notify.call_args[0][1]
            callback(0, bytearray(b"OK:1"))

        mock_client.write_gatt_char.side_effect = mock_write

        result = await ble.send_command(1)

        assert result == "OK:1"
        mock_client.start_notify.assert_called_once()
        mock_client.stop_notify.assert_called_once()
        mock_client.write_gatt_char.assert_called_once_with(CHAR_SEND_UUID, bytes([1]))

    async def test_send_command_decode_error(self) -> None:
        config = BLEConfig(device_name="Test Device")
        ble = IRBlasterBLE(config)
        mock_client = MagicMock()
        mock_client.is_connected = True
        mock_client.start_notify = AsyncMock()
        mock_client.stop_notify = AsyncMock()
        mock_client.write_gatt_char = AsyncMock()
        ble._client = mock_client

        async def mock_write(_uuid: str, _payload: bytes) -> None:
            callback = mock_client.start_notify.call_args[0][1]
            mock_data = MagicMock(spec=bytearray)
            mock_data.decode.side_effect = UnicodeDecodeError("utf-8", b"", 0, 1, "mock error")
            callback(0, mock_data)

        mock_client.write_gatt_char.side_effect = mock_write

        result = await ble.send_command(1)

        assert result == "ERR:decode"
        mock_client.start_notify.assert_called_once()
        mock_client.stop_notify.assert_called_once()
        mock_client.write_gatt_char.assert_called_once_with(CHAR_SEND_UUID, bytes([1]))

    async def test_send_command_generic_exception(self) -> None:
        config = BLEConfig(device_name="Test Device")
        ble = IRBlasterBLE(config)
        mock_client = MagicMock()
        mock_client.is_connected = True
        mock_client.start_notify = AsyncMock()
        mock_client.stop_notify = AsyncMock()
        mock_client.write_gatt_char = AsyncMock()
        ble._client = mock_client

        async def mock_write(_uuid: str, _payload: bytes) -> None:
            callback = mock_client.start_notify.call_args[0][1]
            mock_data = MagicMock(spec=bytearray)
            mock_data.decode.side_effect = Exception("Mock generic exception")
            callback(0, mock_data)

        mock_client.write_gatt_char.side_effect = mock_write

        result = await ble.send_command(1)

        assert result == "ERR:internal"
        mock_client.start_notify.assert_called_once()
        mock_client.stop_notify.assert_called_once()
        mock_client.write_gatt_char.assert_called_once_with(CHAR_SEND_UUID, bytes([1]))

    async def test_send_command_timeout(self) -> None:
        config = BLEConfig(device_name="Test Device")
        ble = IRBlasterBLE(config)
        mock_client = MagicMock()
        mock_client.is_connected = True
        mock_client.start_notify = AsyncMock()
        mock_client.stop_notify = AsyncMock()
        mock_client.write_gatt_char = AsyncMock()
        ble._client = mock_client

        with patch("asyncio.wait_for", new_callable=AsyncMock, side_effect=asyncio.TimeoutError()):
            with self.assertRaises(asyncio.TimeoutError):
                await ble.send_command(1)

    async def test_send_command_invalid_index(self) -> None:
        config = BLEConfig(device_name="Test Device")
        ble = IRBlasterBLE(config)
        mock_client = MagicMock()
        mock_client.is_connected = True
        ble._client = mock_client

        with self.assertRaises(ValueError):
            await ble.send_command(256)
