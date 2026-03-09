import pytest
from unittest.mock import AsyncMock, patch
from bleak.backends.device import BLEDevice

from blaster.config import BLEConfig
from blaster.ble_client import find_device


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
