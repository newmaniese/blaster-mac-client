import asyncio
import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from bleak.backends.device import BLEDevice

from blaster.config import BLEConfig
from blaster.ble_client import CHAR_SCHEDULE_UUID, CHAR_SEND_UUID, IRBlasterBLE, find_device


@pytest.mark.asyncio
async def test_find_device_found() -> None:
    config = BLEConfig(device_name="IR Blaster")
    mock_device = BLEDevice(address="00:11:22:33:44:55", name="IR Blaster", details={})

    with patch("blaster.ble_client.BleakScanner.discover", new_callable=AsyncMock) as mock_discover:
        mock_discover.return_value = [mock_device]

        device = await find_device(config)

        assert device is not None
        assert device.name == "IR Blaster"
        assert device.address == "00:11:22:33:44:55"
        mock_discover.assert_called_once_with(timeout=10.0)


@pytest.mark.asyncio
async def test_find_device_not_found() -> None:
    config = BLEConfig(device_name="IR Blaster")
    mock_device = BLEDevice(address="AA:BB:CC:DD:EE:FF", name="Other Device", details={})

    with patch("blaster.ble_client.BleakScanner.discover", new_callable=AsyncMock) as mock_discover:
        mock_discover.return_value = [mock_device]

        device = await find_device(config)

        assert device is None
        mock_discover.assert_called_once_with(timeout=10.0)


@pytest.mark.asyncio
async def test_find_device_empty() -> None:
    config = BLEConfig(device_name="IR Blaster")

    with patch("blaster.ble_client.BleakScanner.discover", new_callable=AsyncMock) as mock_discover:
        mock_discover.return_value = []

        device = await find_device(config)

        assert device is None
        mock_discover.assert_called_once_with(timeout=10.0)


@pytest.mark.asyncio
async def test_find_device_case_insensitive() -> None:
    config = BLEConfig(device_name="ir blaster")
    mock_device = BLEDevice(address="00:11:22:33:44:55", name="IR Blaster", details={})

    with patch("blaster.ble_client.BleakScanner.discover", new_callable=AsyncMock) as mock_discover:
        mock_discover.return_value = [mock_device]

        device = await find_device(config)

        assert device is not None
        assert device.name == "IR Blaster"
        mock_discover.assert_called_once_with(timeout=10.0)


@pytest.mark.asyncio
async def test_find_device_partial_match() -> None:
    config = BLEConfig(device_name="Blaster")
    mock_device = BLEDevice(address="00:11:22:33:44:55", name="My IR Blaster", details={})

    with patch("blaster.ble_client.BleakScanner.discover", new_callable=AsyncMock) as mock_discover:
        mock_discover.return_value = [mock_device]

        device = await find_device(config)

        assert device is not None
        assert device.name == "My IR Blaster"
        mock_discover.assert_called_once_with(timeout=10.0)


@pytest.mark.asyncio
async def test_connect_success() -> None:
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


@pytest.mark.asyncio
async def test_connect_no_device() -> None:
    config = BLEConfig(device_name="Test Device")
    ble = IRBlasterBLE(config)

    with patch("blaster.ble_client.find_device", new_callable=AsyncMock) as mock_find:
        mock_find.return_value = None
        success = await ble.connect()

    assert success is False


@pytest.mark.asyncio
async def test_connect_exception() -> None:
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


@pytest.mark.asyncio
async def test_connect_already_connected() -> None:
    config = BLEConfig(device_name="Test Device")
    ble = IRBlasterBLE(config)
    mock_client = MagicMock()
    mock_client.is_connected = True
    ble._client = mock_client

    success = await ble.connect()

    assert success is True


@pytest.mark.asyncio
async def test_disconnect() -> None:
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


@pytest.mark.asyncio
async def test_wait_until_ready_success() -> None:
    config = BLEConfig(device_name="Test Device")
    ble = IRBlasterBLE(config)
    mock_client = MagicMock()
    mock_client.is_connected = True
    ble._client = mock_client

    with patch.object(ble, "get_saved_codes", new_callable=AsyncMock) as mock_get:
        await ble.wait_until_ready(timeout_seconds=0.1)
        mock_get.assert_called()


@pytest.mark.asyncio
async def test_wait_until_ready_timeout() -> None:
    config = BLEConfig(device_name="Test Device")
    ble = IRBlasterBLE(config)
    mock_client = MagicMock()
    mock_client.is_connected = True
    ble._client = mock_client

    with (
        patch.object(ble, "get_saved_codes", new_callable=AsyncMock, side_effect=Exception("Not ready")),
        patch("asyncio.sleep", new_callable=AsyncMock),
    ):
        with pytest.raises(TimeoutError):
            await ble.wait_until_ready(timeout_seconds=0.1)


@pytest.mark.asyncio
async def test_get_saved_codes_success() -> None:
    config = BLEConfig(device_name="Test Device")
    ble = IRBlasterBLE(config)
    mock_client = MagicMock()
    mock_client.is_connected = True
    codes = [{"index": 1, "name": "Red"}]
    mock_client.read_gatt_char = AsyncMock(return_value=json.dumps(codes).encode("utf-8"))
    ble._client = mock_client

    result = await ble.get_saved_codes()

    assert result == codes


@pytest.mark.asyncio
async def test_get_saved_codes_retry_success() -> None:
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


@pytest.mark.asyncio
async def test_get_saved_codes_failure() -> None:
    config = BLEConfig(device_name="Test Device")
    ble = IRBlasterBLE(config)
    mock_client = MagicMock()
    mock_client.is_connected = True
    mock_client.read_gatt_char = AsyncMock(return_value=b"invalid json")
    ble._client = mock_client

    with patch("asyncio.sleep", new_callable=AsyncMock):
        with pytest.raises(json.JSONDecodeError):
            await ble.get_saved_codes(retries=2)


@pytest.mark.asyncio
async def test_send_command_by_name_success() -> None:
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


@pytest.mark.asyncio
async def test_send_command_by_name_unknown() -> None:
    config = BLEConfig(device_name="Test Device")
    ble = IRBlasterBLE(config)
    mock_client = MagicMock()
    mock_client.is_connected = True
    ble._client = mock_client
    ble._name_to_index = {"red": 1}

    with pytest.raises(ValueError):
        await ble.send_command_by_name("Green")


@pytest.mark.asyncio
async def test_schedule_disconnect_command_valid() -> None:
    config = BLEConfig(device_name="IR Blaster")
    ble = IRBlasterBLE(config)
    mock_client = AsyncMock()
    mock_client.is_connected = True
    ble._client = mock_client

    await ble.schedule_disconnect_command("Off", 900)

    expected_payload = json.dumps({"delay_seconds": 900, "command": "Off"}).encode("utf-8")
    mock_client.write_gatt_char.assert_called_once_with(CHAR_SCHEDULE_UUID, expected_payload)


@pytest.mark.asyncio
async def test_schedule_disconnect_command_negative_delay() -> None:
    config = BLEConfig(device_name="IR Blaster")
    ble = IRBlasterBLE(config)
    mock_client = AsyncMock()
    mock_client.is_connected = True
    ble._client = mock_client

    with pytest.raises(ValueError, match="delay_seconds must be non-negative"):
        await ble.schedule_disconnect_command("Off", -1)

    mock_client.write_gatt_char.assert_not_called()


@pytest.mark.asyncio
async def test_schedule_disconnect_command_invalid_type() -> None:
    config = BLEConfig(device_name="IR Blaster")
    ble = IRBlasterBLE(config)
    mock_client = AsyncMock()
    mock_client.is_connected = True
    ble._client = mock_client

    with pytest.raises(TypeError, match="delay_seconds must be an integer"):
        await ble.schedule_disconnect_command("Off", "900")  # type: ignore[arg-type]
    with pytest.raises(TypeError, match="delay_seconds must be an integer"):
        await ble.schedule_disconnect_command("Off", 1.5)  # type: ignore[arg-type]

    mock_client.write_gatt_char.assert_not_called()


@pytest.mark.asyncio
async def test_send_heartbeat() -> None:
    config = BLEConfig(device_name="Test Device")
    ble = IRBlasterBLE(config)
    mock_client = MagicMock()
    mock_client.is_connected = True
    mock_client.write_gatt_char = AsyncMock()
    ble._client = mock_client

    await ble.send_heartbeat()

    expected = json.dumps({"heartbeat": True}).encode("utf-8")
    mock_client.write_gatt_char.assert_called_once_with(CHAR_SCHEDULE_UUID, expected)


@pytest.mark.asyncio
async def test_send_command_success() -> None:
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


@pytest.mark.asyncio
async def test_send_command_timeout() -> None:
    config = BLEConfig(device_name="Test Device")
    ble = IRBlasterBLE(config)
    mock_client = MagicMock()
    mock_client.is_connected = True
    mock_client.start_notify = AsyncMock()
    mock_client.stop_notify = AsyncMock()
    mock_client.write_gatt_char = AsyncMock()
    ble._client = mock_client

    with patch("asyncio.wait_for", new_callable=AsyncMock, side_effect=asyncio.TimeoutError()):
        with pytest.raises(asyncio.TimeoutError):
            await ble.send_command(1)


@pytest.mark.asyncio
async def test_send_command_invalid_index() -> None:
    config = BLEConfig(device_name="Test Device")
    ble = IRBlasterBLE(config)
    mock_client = MagicMock()
    mock_client.is_connected = True
    ble._client = mock_client

    with pytest.raises(ValueError):
        await ble.send_command(256)
