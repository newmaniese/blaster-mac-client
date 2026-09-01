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
from blaster.ble_client import (
    CHAR_AUTH_UUID,
    CHAR_SCHEDULE_UUID,
    CHAR_SEND_UUID,
    CHAR_STATUS_UUID,
    IRBlasterBLE,
    SCAN_TIMEOUT_SECONDS,
    find_device,
)


class _InsufficientEncryption(Exception):
    """Stand-in for bleak.exc.BleakGATTProtocolError(0x0F)."""

    def __init__(self) -> None:
        super().__init__(0x0F, "GATT Protocol Error: Insufficient Encryption")


def _discovered(*entries: tuple[str, str, str | None]) -> dict:
    """Build a discover(return_adv=True) result: (address, cached_name, advertised_name)."""
    result = {}
    for address, cached_name, advertised_name in entries:
        device = BLEDevice(address=address, name=cached_name, details={})
        adv = MagicMock()
        adv.local_name = advertised_name
        result[address] = (device, adv)
    return result


def _find_from(*entries: tuple[str, str, str | None]):
    discovered = _discovered(*entries)

    async def find(filterfunc, **_kwargs):
        for device, adv in discovered.values():
            if filterfunc(device, adv):
                return device
        return None

    return find


class TestFindDevice(unittest.IsolatedAsyncioTestCase):
    async def test_find_device_found(self) -> None:
        config = BLEConfig(device_name="IR Blaster")

        with patch("blaster.ble_client.BleakScanner.find_device_by_filter", new_callable=AsyncMock) as mock_find:
            mock_find.side_effect = _find_from(
                ("00:11:22:33:44:55", "IR Blaster", "IR Blaster")
            )

            device = await find_device(config)

            assert device is not None
            assert device.address == "00:11:22:33:44:55"
            assert mock_find.await_args.kwargs["timeout"] == SCAN_TIMEOUT_SECONDS

    async def test_find_device_not_found(self) -> None:
        config = BLEConfig(device_name="IR Blaster")

        with patch("blaster.ble_client.BleakScanner.find_device_by_filter", new_callable=AsyncMock) as mock_find:
            mock_find.side_effect = _find_from(
                ("AA:BB:CC:DD:EE:FF", "Other Device", "Other Device")
            )

            device = await find_device(config)

            assert device is None
            assert mock_find.await_args.kwargs["timeout"] == SCAN_TIMEOUT_SECONDS

    async def test_find_device_empty(self) -> None:
        config = BLEConfig(device_name="IR Blaster")

        with patch("blaster.ble_client.BleakScanner.find_device_by_filter", new_callable=AsyncMock) as mock_find:
            mock_find.return_value = None

            device = await find_device(config)

            assert device is None
            assert mock_find.await_args.kwargs["timeout"] == SCAN_TIMEOUT_SECONDS

    async def test_find_device_case_insensitive(self) -> None:
        config = BLEConfig(device_name="ir blaster")

        with patch("blaster.ble_client.BleakScanner.find_device_by_filter", new_callable=AsyncMock) as mock_find:
            mock_find.side_effect = _find_from(
                ("00:11:22:33:44:55", "IR Blaster", "IR Blaster")
            )

            device = await find_device(config)

            assert device is not None
            assert device.address == "00:11:22:33:44:55"
            assert mock_find.await_args.kwargs["timeout"] == SCAN_TIMEOUT_SECONDS

    async def test_find_device_partial_match(self) -> None:
        config = BLEConfig(device_name="Blaster")

        with patch("blaster.ble_client.BleakScanner.find_device_by_filter", new_callable=AsyncMock) as mock_find:
            mock_find.side_effect = _find_from(
                ("00:11:22:33:44:55", "My IR Blaster", "My IR Blaster")
            )

            device = await find_device(config)

            # Fix: partial match no longer allowed
            assert device is None
            assert mock_find.await_args.kwargs["timeout"] == SCAN_TIMEOUT_SECONDS

    async def test_find_device_matches_renamed_device(self) -> None:
        """macOS keeps a stale cached name after a rename; the advertisement wins."""
        config = BLEConfig(device_name="Michael's Meeting Light")

        with patch("blaster.ble_client.BleakScanner.find_device_by_filter", new_callable=AsyncMock) as mock_find:
            mock_find.side_effect = _find_from(
                ("00:11:22:33:44:55", "IR Blaster", "Michael's Meeting Light")
            )

            device = await find_device(config)

            assert device is not None
            assert device.address == "00:11:22:33:44:55"

    async def test_find_device_ignores_stale_cached_name(self) -> None:
        """A device whose cached name still matches must not be picked once renamed."""
        config = BLEConfig(device_name="IR Blaster")

        with patch("blaster.ble_client.BleakScanner.find_device_by_filter", new_callable=AsyncMock) as mock_find:
            mock_find.side_effect = _find_from(
                ("00:11:22:33:44:55", "IR Blaster", "Michael's Meeting Light")
            )

            device = await find_device(config)

            assert device is None

    async def test_find_device_skips_devices_without_advertised_name(self) -> None:
        config = BLEConfig(device_name="IR Blaster")

        with patch("blaster.ble_client.BleakScanner.find_device_by_filter", new_callable=AsyncMock) as mock_find:
            mock_find.side_effect = _find_from(
                ("AA:BB:CC:DD:EE:FF", "IR Blaster", None),
                ("00:11:22:33:44:55", "IR Blaster", "IR Blaster"),
            )

            device = await find_device(config)

            assert device is not None
            assert device.address == "00:11:22:33:44:55"

    async def test_find_device_hard_timeout(self) -> None:
        """A wedged BleakScanner.discover must not hang reconnect forever."""
        config = BLEConfig(device_name="IR Blaster")

        async def hang(*_args, **_kwargs):
            await asyncio.sleep(60)

        with (
            patch("blaster.ble_client.BleakScanner.find_device_by_filter", side_effect=hang),
            patch("blaster.ble_client.SCAN_HARD_TIMEOUT_SECONDS", 0.05),
        ):
            started = asyncio.get_running_loop().time()
            device = await find_device(config)
            elapsed = asyncio.get_running_loop().time() - started

            assert device is None
            assert elapsed < 2.0

    async def test_connect_hard_timeout(self) -> None:
        """A wedged BleakClient.connect must return False so reconnect can retry."""
        config = BLEConfig(device_name="Test Device", auth_token="test-token-123456")
        ble = IRBlasterBLE(config)
        mock_device = MagicMock()
        mock_device.name = "Test Device"
        mock_device.address = "00:11:22:33:44:55"

        async def hang_connect():
            await asyncio.sleep(60)

        mock_client = MagicMock()
        mock_client.is_connected = False
        mock_client.connect = hang_connect

        with (
            patch("blaster.ble_client.find_device", new_callable=AsyncMock) as mock_find,
            patch("blaster.ble_client.BleakClient", return_value=mock_client),
            patch("blaster.ble_client.CONNECT_HARD_TIMEOUT_SECONDS", 0.05),
        ):
            mock_find.return_value = mock_device
            started = asyncio.get_running_loop().time()
            success = await ble.connect()
            elapsed = asyncio.get_running_loop().time() - started

            assert success is False
            assert ble._client is None
            assert ble._device is mock_device
            assert elapsed < 2.0


class TestIRBlasterBLE(unittest.IsolatedAsyncioTestCase):
    async def test_connect_requires_auth_token(self) -> None:
        ble = IRBlasterBLE(BLEConfig(device_name="Test Device"))

        with patch("blaster.ble_client.find_device", new_callable=AsyncMock) as mock_find:
            success = await ble.connect()

        assert success is False
        assert "auth token is not configured" in (ble.last_connection_error or "")
        mock_find.assert_not_awaited()

    async def test_authenticate_writes_token_and_reads_confirmation(self) -> None:
        config = BLEConfig(
            device_name="Test Device",
            auth_token="test-token-123456",
        )
        ble = IRBlasterBLE(config)
        client = MagicMock()
        client.write_gatt_char = AsyncMock()
        client.read_gatt_char = AsyncMock(return_value=b"OK")

        await ble._authenticate(client)

        client.write_gatt_char.assert_awaited_once_with(
            CHAR_AUTH_UUID,
            b"test-token-123456",
            response=True,
        )
        client.read_gatt_char.assert_awaited_once_with(CHAR_AUTH_UUID)

    async def test_authenticate_rejects_bad_token(self) -> None:
        config = BLEConfig(
            device_name="Test Device",
            auth_token="test-token-123456",
        )
        ble = IRBlasterBLE(config)
        client = MagicMock()
        client.write_gatt_char = AsyncMock()
        client.read_gatt_char = AsyncMock(return_value=b"ERR")

        with self.assertRaisesRegex(PermissionError, "token was rejected"):
            await ble._authenticate(client)

    async def test_authenticate_retries_while_macos_pairs(self) -> None:
        """macOS answers the first write with Insufficient Encryption while it pairs."""
        config = BLEConfig(device_name="Test Device", auth_token="test-token-123456")
        ble = IRBlasterBLE(config)
        client = MagicMock()
        client.is_connected = True
        client.write_gatt_char = AsyncMock(
            side_effect=[_InsufficientEncryption(), _InsufficientEncryption(), None]
        )
        client.read_gatt_char = AsyncMock(return_value=b"OK")

        with patch("blaster.ble_client.AUTH_RETRY_INTERVAL_SECONDS", 0.0):
            await ble._authenticate(client)

        assert client.write_gatt_char.await_count == 3

    async def test_authenticate_gives_up_when_encryption_never_completes(self) -> None:
        config = BLEConfig(device_name="Test Device", auth_token="test-token-123456")
        ble = IRBlasterBLE(config)
        client = MagicMock()
        client.is_connected = True
        client.write_gatt_char = AsyncMock(side_effect=_InsufficientEncryption())
        client.read_gatt_char = AsyncMock(return_value=b"OK")

        with (
            patch("blaster.ble_client.AUTH_RETRY_INTERVAL_SECONDS", 0.0),
            patch("blaster.ble_client.AUTH_ENCRYPTION_TIMEOUT_SECONDS", 0.05),
        ):
            with self.assertRaisesRegex(RuntimeError, "was not encrypted"):
                await ble._authenticate(client)

        client.read_gatt_char.assert_not_awaited()

    async def test_authenticate_does_not_retry_unrelated_errors(self) -> None:
        config = BLEConfig(device_name="Test Device", auth_token="test-token-123456")
        ble = IRBlasterBLE(config)
        client = MagicMock()
        client.is_connected = True
        client.write_gatt_char = AsyncMock(side_effect=ValueError("bad handle"))

        with self.assertRaisesRegex(ValueError, "bad handle"):
            await ble._authenticate(client)

        assert client.write_gatt_char.await_count == 1

    async def test_authenticate_stops_retrying_when_link_drops(self) -> None:
        config = BLEConfig(device_name="Test Device", auth_token="test-token-123456")
        ble = IRBlasterBLE(config)
        client = MagicMock()
        client.is_connected = False
        client.write_gatt_char = AsyncMock(side_effect=_InsufficientEncryption())

        with self.assertRaises(_InsufficientEncryption):
            await ble._authenticate(client)

        assert client.write_gatt_char.await_count == 1

    async def test_connect_success(self) -> None:
        config = BLEConfig(device_name="Test Device", auth_token="test-token-123456")
        ble = IRBlasterBLE(config)
        mock_device = MagicMock()
        mock_device.name = "Test Device"

        mock_client = MagicMock()
        mock_client.is_connected = True
        mock_client.connect = AsyncMock()

        with (
            patch("blaster.ble_client.find_device", new_callable=AsyncMock) as mock_find,
            patch("blaster.ble_client.BleakClient", return_value=mock_client) as mock_client_cls,
            patch.object(ble, "_authenticate", new_callable=AsyncMock),
        ):
            mock_find.return_value = mock_device
            success = await ble.connect()

        assert success is True
        mock_client.connect.assert_called_once()
        assert ble._client is mock_client
        mock_client_cls.assert_called_once()

    async def test_connect_no_device(self) -> None:
        config = BLEConfig(device_name="Test Device", auth_token="test-token-123456")
        ble = IRBlasterBLE(config)

        with patch("blaster.ble_client.find_device", new_callable=AsyncMock) as mock_find:
            mock_find.return_value = None
            success = await ble.connect()

        assert success is False

    async def test_connect_exception(self) -> None:
        config = BLEConfig(device_name="Test Device", auth_token="test-token-123456")
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
        config = BLEConfig(device_name="Test Device", auth_token="test-token-123456")
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
        ble._client = mock_client

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

    async def test_get_disconnect_timeout_state_interrupted(self) -> None:
        config = BLEConfig(device_name="IR Blaster")
        ble = IRBlasterBLE(config)
        mock_client = MagicMock()
        mock_client.is_connected = True
        mock_client.read_gatt_char = AsyncMock(
            return_value=json.dumps(
                {
                    "state": "interrupted",
                    "remaining_seconds": 742,
                    "command": "Off",
                }
            ).encode()
        )
        ble._client = mock_client

        result = await ble.get_disconnect_timeout_state()

        assert result == {
            "state": "interrupted",
            "remaining_seconds": 742,
            "command": "Off",
        }
        mock_client.read_gatt_char.assert_awaited_once_with(CHAR_STATUS_UUID)

    async def test_get_disconnect_timeout_state_rejects_command_result(self) -> None:
        """A send overwrites the snapshot, so a status string must not parse as one."""
        config = BLEConfig(device_name="IR Blaster")
        ble = IRBlasterBLE(config)
        mock_client = MagicMock()
        mock_client.is_connected = True
        mock_client.read_gatt_char = AsyncMock(return_value=b"OK:Green")
        ble._client = mock_client

        with self.assertRaises(ValueError):
            await ble.get_disconnect_timeout_state()

    async def test_get_disconnect_timeout_state_rejects_invalid_payload(self) -> None:
        config = BLEConfig(device_name="IR Blaster")
        ble = IRBlasterBLE(config)
        mock_client = MagicMock()
        mock_client.is_connected = True
        mock_client.read_gatt_char = AsyncMock(
            return_value=b'{"state":"interrupted","remaining_seconds":-1,"command":"Off"}'
        )
        ble._client = mock_client

        with self.assertRaisesRegex(ValueError, "remaining_seconds"):
            await ble.get_disconnect_timeout_state()

    async def test_send_heartbeat(self) -> None:
        config = BLEConfig(device_name="IR Blaster")
        ble = IRBlasterBLE(config)
        mock_client = MagicMock()
        mock_client.is_connected = True
        mock_client.write_gatt_char = AsyncMock()
        ble._client = mock_client

        await ble.send_heartbeat()

        expected = json.dumps({"heartbeat": True}).encode("utf-8")
        mock_client.write_gatt_char.assert_called_once_with(CHAR_SCHEDULE_UUID, expected)

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
